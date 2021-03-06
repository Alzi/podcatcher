#!/usr/bin/env python2
# -*- coding: UTF-8 -*-

"""
podcatcher.py is a simple commandline tool to manage podcast feeds

author:      Marc Wesemeier, Wackernheim, Germany
date:        2014-04-17
license:     WTFPL V2
email:       projectleviathan@arcor.de
status:      Development
"""

# import sqlite3
from datetime import date, datetime, timedelta
from hashlib import sha256
from thread import start_new_thread, allocate_lock
import urllib2
import time
import socket
import sys
import os
import re
import argparse

from mutagen.id3 import ID3, TXXX
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen import File as mutagen_File

import feedparser
import db

from helper import log, DB

AUDIO_MIME_TYPES = [
"audio/mpeg",
"audio/ogg",
"audio/ogg;codecs=opus",
"audio/ogg;codecs=vorbis",
"audio/opus",
"audio/mp3",
"audio/x-m4a",
"audio/mp4"
]

KNOWN_MIME_TYPES = [
"text/html",
"video/mpeg",
"no_type"
]

#set STATUS_OLDER_POST if post is > this days old
DAYS_OLDER_POST = 14

#minutes that should be between update-attempts
UPDATE_TIME = 120   

# DB_PATH = "C:/Daten/Projekte/Python-Projekte/podcatcher/src/database.sq3"
MEDIA_PATH = "C:/Daten/Foobar/Podcasts/"
STATUS_UPDATE_CAST = 0
STATUS_NOTACTIVE_CAST = 1
STATUS_ARCHIVED_CAST = 2

STATUS_DOWNLOADED_POST = 0
STATUS_NEW_POST = 1
STATUS_OLDER_POST = 2
STATUS_NO_AUDIO_POST = 3

lock = allocate_lock()
update_result = {}
thread_started = False
num_of_threads = 0

class Post(object):
    """Handle data corresponding to one certain show
    """
    def __init__(self, feedId):
        """initialize
        """
        self.feedId = feedId
        self.has_audio = False
        self.id = None
        self.title = "no-title"
        self.subtitle = "no-subtitle"
        self.author = "no-author"
        self.published = ""
        self.media_link = ""
        self.hash = None
        self.status = None
        
    def fromRssEntry(self, entry):
        """get data from rss-entry
        """
        self.has_audio = False
        self.entry = entry
        self.title = self._getTitle()
        self.subtitle = self._getSubtitle()
        self.author = self._getAuthor()
        self.published = self._getPublished()
        self.media_link = self._extractMediaLinks() 
        self.hash = self._getHash()
        self.status = STATUS_NEW_POST
        self.daysOld = self._getDaysSincePublished()

    def fromDbRow(self, row):
        """get data from database-row
        """
        self.has_audio = True
        self.feedId, self.id, self.title, self.subtitle,\
            self.author, self.published, self.media_link,\
            self.hash, self.status = row
        # self.feedId = int(self.feedId)
        self.daysOld = self._getDaysSincePublished()

    def download(self):
        """download media to hard drive
        """
        cast = Cast(self.feedId)
        dirname = cast.short_title
        print('Downloading: %s[%s] "%s"' % (
            makePrintable(self.title), self.feedId, 
            makePrintable(dirname))
        )
        filename = os.path.basename(self.media_link)
        filename = filename.split('?')[0]

        targetPath = os.path.join(MEDIA_PATH, dirname)

        if dirname not in os.listdir(MEDIA_PATH):
            os.mkdir(targetPath)

        if not filename in os.listdir(targetPath):
            data = downloadAudio(self.media_link)
            path = os.path.join(targetPath,filename)
            with open (path,"wb") as fh:
                fh.write(data)
            self._tagFile(path, makePrintable(self.title))
        else:
            print "File allready downloaded!"
        self._setStatusDownloaded()

    def _tagFile(self, path, title):
        """use mutagen to set (ID-3)-Tags inside audio file
        PODCAST_STATUS = new
        useful for foobar2000's dynamic-playlist function
        FIXME: this sucks! Make it better!
        """
        try:
            audio = ID3(path)
        except:
            try:
                audio = MP4(path)
            except:
                try:
                    audio = MP3(path, ID3=EasyID3)
                except:
                    try:
                        audio = mutagen_File(path)
                    except:
                        print "Couldn't tag audio-file."
                    else: #mutagen_file
                        print 'Tagging: FILE passed'
                        print 'adding tags...'
                        try:
                            audio.add_tags()
                        except:
                            print 'failed.'
                        try:
                            print 'setting title...'
                            audio["title"] = os.path.basename(path)
                        except:
                            print "Couldn't tag audio-file."
                        else:
                            print 'setting podcast_status...'
                            try:
                                audio['podcast_status'] = 'new'
                                audio.save()
                            except:
                                print "Couldn't tag audio-file."
                else: #MP3
                    print 'Tagging MP3 passed'
                    print 'now trying to add title...'
                    try:
                        audio.add_tags()
                        audio['title'] = title
                        print "Title added (%s)" % title
                    except mutagen.id3.error:
                        print "Couldn't tag audio-file."
                    else:
                        print 'Tagging: saving and recalling...'
                        audio.save()
                        #now it should be taggable by ID3-class
                        self._tagFile(path, title)
                        #TODO: Test if recursion could crash 13.06.2014
                        #not yet crashed 19.11.2014
            else:#MP4
                print 'Tagging: MP4 passed'
                audio['----:com.apple.iTunes:PODCAST_STATUS'] = "new"
                audio.save()
        else:#ID3
            print 'Tagging: ID3 passed'
            audio.add(TXXX(encoding=3,desc="PODCAST_STATUS",text="new"))
            audio.save()
            
    def is_saved(self):
        """check if post is allready stored to database
        """
        with DB() as dbHandler:
            result = dbHandler.sql (
                "SELECT id FROM shows WHERE feed_id=? AND hash=?",
                (self.feedId, self.hash)
            )
        if result:
            self.id = result[0][0]
            return True
        return False

    def save(self):
        """save post to database
        """
        if not self.is_saved():
            if not self.media_link:
                status = STATUS_NO_AUDIO_POST;
            elif self.daysOld > DAYS_OLDER_POST:
                status = STATUS_OLDER_POST
            else:
                status = STATUS_NEW_POST
            with DB() as dbHandler:
                dbHandler.sql (
                    "INSERT INTO shows VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        None, self.feedId, self.title, self.subtitle, 
                        self.author, self.media_link, self.published, 
                        status, self.hash
                    )
                )
                self.id = dbHandler.getLastId()

    def _getDaysSincePublished(self):
        """calculate days between today and date of publishing 
        """
        today = datetime.now()
        published = string2DateTime(self.published)
        diff = today-published
        return diff.days

    def update(self):
        if self.daysOld > DAYS_OLDER_POST:
            status = STATUS_OLDER_POST
        else:
            status = STATUS_NEW_POST
        with DB() as dbHandler:
            dbHandler.sql(
                "UPDATE shows SET status=? WHERE id=? AND status<>?",
                (status, self.id, STATUS_DOWNLOADED_POST)
            )

    def _setStatusDownloaded(self):
        """set the status_flag inside database to STATUS_DOWNLOADED_POST
        """
        with DB() as dbHandler:
            dbHandler.sql(
                "UPDATE shows SET status=? WHERE hash=?",
                (STATUS_DOWNLOADED_POST, self.hash)
            )

    def _getTitle(self):
        """Get title-data from feed-entry.
        """
        try:
            return self.entry.title
        except:
            return u"no-title"

    def _getSubtitle(self):
        """Get subtitle-data from feed-entry.
        """
        try:
            return self.entry.subtitle
        except:
            return u"no-subtitle"

    def _extractMediaLinks(self):
        """try to find media-infos of this feed-post
        """
        self.mediaLinks = []
        newTypes = set()
        for link in self.entry.links:
            linktype = 'no_audio'
            linktype = link.get('type', 'no_type')
            if linktype in AUDIO_MIME_TYPES:
                self.mediaLinks.append((link.href,linktype))
                self.has_audio = True
            elif linktype not in KNOWN_MIME_TYPES:
                newTypes.add(linktype)
        if newTypes:
            print("New MimeType(s) found:\n%s" % newTypes)
        if not self.mediaLinks:
            self.has_audio = False
            return "no audio"
        else:
            return self.mediaLinks[0][0]

    def _getPublished(self):
        """Get published-data from feed-entry.
        """
        try:
            published = self.entry.published
        except:
            published = u'no date'
        else:
            published = published.split()
            oldString = "%s %s %s %s %s" % (
                published[0], published[1], published[2][:3],
                published[3],published[4]
            )
            date = datetime.strptime( oldString, "%a, %d %b %Y %H:%M:%S" )
            newString = date.strftime("%Y-%m-%d %H:%M:%S")
            published = unicode(newString)
        return published

    def _getAuthor(self):
        """Get author-data from feed-entry.
        """
        try:
            return self.entry.author
        except:
            return u'no author'

    def _getHash(self):
        """Create a hash over 'title', 'author' & 'published'
        informations. This exists mainly to test something like 
        this and to make the DB-search eassier.
        """
        m = sha256()
        m.update(unicode.encode(self.title,'utf-8'))
        m.update(unicode.encode(self.author,'utf-8'))
        m.update(unicode.encode(self.published,'utf-8'))
        return m.hexdigest()


class Podcast(object):
    """rewrite of old 'Cast' class
    """
    def __init__(self, cast_id):
        self.cast_id = cast_id
        self.data = db.get_cast_data(cast_id)
        rss = feedparser.parse(self.data['url'])
        title = rss.feed.get('title', 'noTitle')
        updated = rss.feed.get('updated_parsed', 'noDate')
        logo = rss.feed.get('logo', 'noLogo')
        image = rss.feed.get('image', 'noImage')

        print (title, time.strftime("%Y-%m-%d %H:%M:%S", updated), logo, image)
        print (rss.entries[0].get('title', 'no_title'))
        print (rss.entries[1].get('title', 'no_title').encode('utf-8'))




class Cast(object):
    """Handle all data corresponding to a cast
    """
    def __init__(self, feedId=None):
        self.feedId = feedId
        self.rss = None
        self.allPosts = {}
        if self.feedId != None:
            self.title = self._getTitle()
            self.short_title = self._get_short_title()
            self._getAllPosts()

    def change_url(self, new_url):
        """change url of this cast inside DB
        """
        db.change_feed_url(self.feedId, new_url)

    def get_image(self):
        """check for image and download it to folder as
        'cover.jpg'"""
        self.rss = self._fetchFeed()
        image = self.rss.feed.get('image', None)
        if image:
            image_path = image.get('href', None)
            if image_path:
                data = downloadAudio(image_path)
                # newly added casts have no folder yet
                if self.short_title not in os.listdir(MEDIA_PATH):
                    os.mkdir(os.path.join(MEDIA_PATH, self.short_title))
                target_path = os.path.join(
                    MEDIA_PATH, 
                    self.short_title,
                    'cover.jpg')
                with open (target_path,"wb") as fh:
                    fh.write(data)
                print ('Image saved under: \n%s' % target_path)
        else:
            print ('No Image found')

    def getLatestPost(self):
        """alias-function to get the single latest post
        """
        return self.getLatestPosts()

    def listAll(self):
        print "------------ %s(%s) ------------\n" % (
            makePrintable(self.title), self.feedId
        )
        with DB() as dbHandler:
            result = dbHandler.sql("SELECT id, title, published, status \
                FROM shows WHERE feed_id=? ORDER BY published DESC",
                (self.feedId,)
            )
        for row in result:
            status = row[3]
            if status == STATUS_DOWNLOADED_POST:
                status = "downloaded"
            elif status == STATUS_NEW_POST:
                status = "new"
            elif status == STATUS_NO_AUDIO_POST:
                status = "no audio"
            else:
                status = "older"
            print "(%05d) [%s] %s /'%s'" % (
                row[0], row[2], makePrintable(row[1]), status
            )

    def getPost(self, post_id):
        with DB() as dbHandler:
            result = dbHandler.sql("SELECT feed_id, id, title, subtitle,\
                author, published, media_link, hash, status\
                FROM shows WHERE id=?",(post_id,)
            )
        post = Post(self.feedId)
        post.fromDbRow(result[0])
        return post

    def getLatestPosts(self, limit=1):
        """return the latest post as Post-Instance
        """
        post = Post(self.feedId)
        with DB() as dbHandler:
            result = dbHandler.sql("SELECT feed_id, id, title, subtitle, \
                author, published, media_link, hash, status \
                FROM shows WHERE feed_id=? AND status<>? AND status <>? \
                ORDER BY published DESC LIMIT ?",
                (self.feedId, STATUS_DOWNLOADED_POST, 
                    STATUS_NO_AUDIO_POST, limit
                )
            )
        if result:
            postList = []
            for row in result:
                post = Post(self.feedId)
                post.fromDbRow(row)
                postList.append(post)
            if limit == 1:
                post = postList[0]
                return post
            else:
                return postList
        else:
            print "No new posts."
            return None

    def update(self):
        """Main-function to look for new posts.
        """
        global lock, update_result, thread_started, num_of_threads

        lock.acquire()
        update_result[self.feedId] = {}
        update_result[self.feedId]['title'] = self.title
        update_result[self.feedId]['posts'] = []
        thread_started = True
        num_of_threads += 1
        lock.release()

        self.rss = self._fetchFeed()
        numOfUpdates = 0

        for entry in self.rss.entries:
            post = Post(self.feedId)
            post.fromRssEntry(entry)
            # try:
            # except:
            #     print ("{}creating Post failed [{}]".format("\n", self.feedId))
            #     print (sys.exc_info())
            if not self._isInsideDB(post):
                numOfUpdates += 1
                lock.acquire()
                post.save()
                update_result[self.feedId]['posts'].append(
                    makePrintable("(%s):%s"%(post.id, post.title))
                )
                lock.release()
        if not numOfUpdates:
            lock.acquire()
            update_result[self.feedId]['posts'] = None
            lock.release()

        self._markOlderPosts()
        self._updated()
        lock.acquire()
        num_of_threads -= 1
        print ("(%s) updated." % self.title)
        # sys.stdout.write(".")
        lock.release()
        
    def _markOlderPosts(self):
        then = now(DAYS_OLDER_POST)[1]
        with DB() as dbHandler:
            dbHandler.sql(
                "UPDATE shows set status=? WHERE published <? \
                AND feed_id=? AND status<>? AND status <>?",
                (STATUS_OLDER_POST, then, self.feedId, 
                 STATUS_DOWNLOADED_POST, STATUS_NO_AUDIO_POST
                )
            )

    def _updated(self):
        """update last_updated inside DB to now
        """
        with DB() as dbHandler:
            dbHandler.sql(
                "UPDATE casts SET last_updated=? WHERE id=?",
                (now()[1], self.feedId)
            )

    def _isInsideDB(self, post):
        # TODO: implement update-activity on site 
        # (same date, changed title; same title changed date)
        if post.hash in self.allPosts.values():
            return True
        return False

    def _getAllPosts(self):
        with DB() as dbHandler:
            result = dbHandler.sql(
                "SELECT id, hash FROM shows WHERE feed_id=?",
                (self.feedId,)
            )
        for row in result:
            self.allPosts[row[0]] = row[1]

    def _fetchFeed(self):
        """Use feedparser module to get the feed-data
        from one podcast.
        """
        with DB() as dbHandler:
            result = dbHandler.sql(
                "SELECT url FROM casts WHERE id=?",
                (self.feedId,)
            )
        url = result[0][0]
        return feedparser.parse(url)

    def _getTitle(self):
        """read title from database and make it printable
        """
        with DB() as dbHandler:
            title = dbHandler.sql(
                "SELECT title FROM casts WHERE id=?",
                (self.feedId,)
            )
        if title:
            return makePrintable(title[0][0])
        else:
            raise IndexError("Feed-id does not exist.")
    
    def _get_short_title(self):
        """read short_title from database
        """
        with DB() as dbHandler:
            title = dbHandler.sql(
                "SELECT short_title FROM casts WHERE id=?",
                (self.feedId,)
            )
        if title:
            return title[0][0]
        else:
            raise IndexError("Feed-id does not exist.")      

#------------------------------------------- -------------------------------------------------------------
#-------------------------------------------------- functions --------------------------------------------
#------------------------------------------- -------------------------------------------------------------

def makePrintable(unprintable):
    """change unprintable characters into '-'
    """
    return "".join(
        #match returns either none or not none -> (0,1)
        #known characters are therefor selecting the x in the two-item-list
        #unkown characters select the '{?}'
        #finally everything is joined together
        #an example of bad, cause unreadable code! :]
        [['{?}',x][re.match(u"[\[\]\w -.:@~/äöüÄÖÜß]",x)!=None] for x in unprintable ]
    )

def string2DateTime(dtString):
    """return our string-format as datetime-object
    """
    return datetime.strptime(dtString, "%Y-%m-%d %H:%M:%S")

def now(daysInThePast=0):
    now = datetime.now()
    if daysInThePast:
        delta = timedelta(days=daysInThePast)
        now -= delta
    nowString = now.strftime("%Y-%m-%d %H:%M:%S")
    return (now,nowString)

def removeCast(feedId):
    """remove cast and it's posts from database
    """
    cast = Cast(feedId);
    print "This will remove '%s' and %d posts from database." % (
        makePrintable(cast.title), len(cast.allPosts)
    )
    answer = raw_input("Continue? (y/n)")
    if answer == 'y':
        with DB() as dbHandler:
            dbHandler.sql(
                "DELETE FROM shows WHERE feed_id=?",
                (feedId,)
            )
            dbHandler.sql(
                "DELETE FROM casts WHERE id=?",
                (feedId,)
            )
        print "deleted."
    else:
        print "ok, deletion canceled."

def get_active_podcasts():
    """Get (id, title, url) tuple-list from all active
    podcasts from DB.
    """
    with DB() as dbHandler:
        results = dbHandler.sql(
            "SELECT id, title, url FROM casts WHERE status=?",
            (STATUS_UPDATE_CAST,)
        )
    return results

def list_podcasts():
    """Print all podcasts to screen
    """
    casts = get_active_podcasts()
    for cast in casts:
        print "(%03d) %s" % (cast[0], makePrintable(cast[1]))

def progressReport(bytesSoFar, chunkSize, totalSize):
    """Write download-progress to stdout.
    """
    percent = float(bytesSoFar) / totalSize
    percent = round(percent*100, 2)
    sys.stdout.write(
        "Downloaded %d of %d bytes (%0.2f%%)\r" % 
        (bytesSoFar, totalSize, percent)
    )
    if bytesSoFar >= totalSize:
        sys.stdout.write('\nready.\n')

def downloadAudio(url, chunkSize=32768):
    """Download audio-data via http.
    """
    requ = urllib2.Request(url, headers={'User-Agent':'Fussels Podcatcher'})
    response = urllib2.urlopen(requ, None, 5)
    totalSize = response.info().getheader('Content-Length').strip()
    totalSize = int(totalSize)
    bytesSoFar = 0
    data = None

    while 1:
        chunk = response.read(chunkSize)
        if not data:
            data = chunk
            bytesSoFar += len(chunk)
        else:
            data += chunk
            bytesSoFar += len(chunk)
        if not chunk:
            break
        progressReport(bytesSoFar, chunkSize, totalSize)
    return data

def downloadLatest(feedId, number=1):
    """download the latest post, or number of 
    posts from podcast with this feedId
    """
    cast = Cast(feedId)
    posts = cast.getLatestPosts(number)
    if number == 1:
        posts.download()
    else:
        for post in posts:
            post.download()

def getCast(cast_id):
    try:
        feed_id = int(cast_id)
    except ValueError:
        feed_id = searchCast(cast_id)
    if feed_id:
        try:
            cast = Cast(feed_id)
        except IndexError:
            print "No subscription with this cast-id."
            return None
        else:
            return cast
    else:
        print "Cast with that name not found."
        return None

def searchCast(cast_name):
    with DB() as dbHandler:
        result = dbHandler.sql(
            "SELECT id FROM casts WHERE title LIKE ?",
            ("%%%s%%" % cast_name, )
        )
        if result:
            if len(result[0]) == 1:
                return int(result[0][0])
        return None

def getNewPosts():
    """return all new that are not older than DAYS_OLDER_POST
    """
    with DB() as dbHandler:
        result = dbHandler.sql(
            "SELECT P.title, P.published, F.title, F.id, P.id \
            FROM shows AS P JOIN casts AS F ON F.id=P.feed_id \
            WHERE P.status=? ORDER BY F.id, P.published",
            (STATUS_NEW_POST,)
        )
    lastCast = ""
    for line in result:
        if lastCast != line[2]:
            print "---------------------------------------\n%s(%s):" % (
                makePrintable(line[2]), line[3]
            )
            lastCast = line[2]
        print "[%06d]'%s'\n(%s)" % (line[4], makePrintable(line[0]), 
            makePrintable(line[1])
        )

def print_results_to_screen():
    global update_result
    for index in sorted(update_result):
        if update_result[index]['posts']:
            print "-----------------------------------------\n(%d)%s" % (
                index, update_result[index]['title']
            )
            for postTitle in update_result[index]['posts']:
                print "\t%s"%postTitle
            print "-----------------------------------------\n"

#---------------------------  database helper ----------------------            

def createTableCasts():
    """database-init: table casts
    """
    with DB() as dbHandler:
        dbHandler.sql(
            "CREATE TABLE casts (id INTEGER PRIMARY KEY \
            AUTOINCREMENT, title TEXT, url TEXT,\
            last_updated TEXT, short_title TEXT, status INT)"
        )

def createTableShows():
    """database-init: table shows
    """
    with DB() as dbHandler:
        dbHandler.sql(
            "CREATE TABLE shows (id INTEGER PRIMARY KEY AUTOINCREMENT, \
                feed_id TEXT, title TEXT, subtitle TEXT, author TEXT, \
                media_link TEXT, published TEXT, status INT, hash TEXT)"
        )

def export_cast_urls():
    with DB() as dbHandler:
        result = dbHandler.sql(
            'SELECT url, short_title FROM casts')
    if len(result) > 0:
        with open('url_export.txt', 'w') as fh:
            for entry in result:
                fh.write("{0};{1}\n".format(entry[1], entry[0]))

def create_all_dirs():
    """Create all directories according to the short_title of the Cast
    """
    with DB() as dbHandler:
        results = dbHandler.sql(
            "SELECT short_title FROM casts WHERE status=?",
            (STATUS_UPDATE_CAST,)
        )
    for result in results:
        if result[0] not in os.listdir(MEDIA_PATH):
            os.mkdir(os.path.join(MEDIA_PATH, result[0]))

#---------------------------  command-line funcs -------------------

def commandUpdateAll(args):
    """update all podcasts with the status_flag set to STATUS_UPDATE_CAST
    """
    global update_result, thread_started, num_of_threads
    
    if (args.feedId == 'all'):
        print("updating podcasts...")
        castsToUpdate = get_active_podcasts()
        allThreads = []
        for data in castsToUpdate:
            feedId = data[0]
            cast = Cast(feedId)
            start_new_thread(cast.update,())

        while not thread_started:
            pass

        while num_of_threads > 0:
            pass
    else:
        cast = Cast(args.feedId)
        cast.update()

    print("\nready.")
    print_results_to_screen()

def updateCast(args):
   """Update only one crertain cast
   """
   cast = Cast(args.feedId)
   cast.update()

def commandAddPodcast(args):
    """add a new feed-url to database
    """
    try:
        cast = feedparser.parse(args.url)
    except:
        log("Couldn't parse. (%s)" % args.url)
    else:
        with DB() as dbHandler:
            dbHandler.sql(
                "INSERT INTO casts (\
                    title, url, last_updated, status, short_title\
                    ) VALUES (?,?,?,?,?)", (
                        cast.feed.title, 
                        args.url, 
                        now()[1], 
                        STATUS_UPDATE_CAST, 
                        args.short_title
                    )
            )
            feedId = dbHandler.getLastId()
        cast = Cast(feedId)
        cast.update()
        cast.get_image()

def commandChangeUrl(args):
    """change url of stored feed
    """
    cast = Cast(args.id)
    cast.change_url(args.new_url)
    # print args.id, args.new_url

def commandStatus(args):
    if args.new:
        getNewPosts()
    elif args.cast_id:
        cast = getCast(args.cast_id)
        if cast:
            cast.listAll()
        else:
            "Cast with this id or name not found."
    elif args.casts:
        list_podcasts()

def commandGet(args):
    if args.casts:
        for cast_id in args.casts:
            cast = getCast(cast_id)
            if cast:
                post = cast.getLatestPosts(1)
                post.download()
            else:
                "Cast with this id or name not found."
    
    elif args.all:
        print 'I should download all new casts,'
        print 'but I need some implementation. :('

    elif args.shows:
        for show_id in args.shows:
            post = Cast().getPost(show_id)
            post.download()
    
    elif args.image:
        cast = Cast(args.image)
        cast.get_image()

def commandRemove(args):
    for cast_id in args.ids:
        removeCast(cast_id)

def commandReset(args):
    answer = raw_input('Do you really want to rewrite the database?(y/n) ')
    if answer == 'y':
        createTableCasts()
        createTableShows()
    else:
        print 'nevermind'
    

def main(args):
    socket.setdefaulttimeout(5)

    parser = argparse.ArgumentParser(
        description='A command line Podcast downloader for RSS XML feeds'
    )
    commands = parser.add_subparsers()
    
    #command add
    command_add = commands.add_parser('add')
    command_add.add_argument('url', help='xml-feed url')
    command_add.add_argument(
        'short_title', help='shortname (used as foldername)'
    )
    command_add.set_defaults(func=commandAddPodcast)

    #command update
    command_update = commands.add_parser('update')
    command_update.add_argument(
        'feedId', 
        help='feed-id to update or \'all\'')
    command_update.set_defaults(func=commandUpdateAll)
    
    #command status
    command_status = commands.add_parser('status')
    command_status.add_argument(
        '-n', '--new', help='show all new casts', action='store_true'
    )
    command_status.add_argument(
        '-l', '--list', dest='cast_id', help='list all posts with this id'
    )
    command_status.add_argument(
        '-c', '--casts', help='list all podcasts', action='store_true'
    )
    command_status.set_defaults(func=commandStatus)

    #command get
    command_get = commands.add_parser('get')
    get_group = command_get.add_mutually_exclusive_group()
    get_group.add_argument(
        '-c',
        '--casts',
        type=int, 
        help='one ore more cast ids to download',
        nargs="+")
    get_group.add_argument(
        '-a', '--all', 
        action='store_true',
        help='flag to download all new podcasts'
    )
    get_group.add_argument(
        '-s', '--shows', 
        type=int,
        help='get one particular show with this id',
        nargs='+'
    )
    get_group.add_argument(
        '-i', '--image', 
        type=int,
        help='get image of the show with this id',
    )
    command_get.set_defaults(func=commandGet)

    #command changeUrl
    command_change = commands.add_parser('change_url')
    command_change.add_argument( 'id', help='change url of this cast-id')
    command_change.add_argument('new_url', help='new feed-url')
    command_change.set_defaults(func=commandChangeUrl)
    
    #command remove
    command_remove = commands.add_parser('remove')
    command_remove.add_argument(
        'ids',
        help='one ore more cast-ids to remove',
        nargs='+',
        type=int
    )
    command_remove.set_defaults(func=commandRemove)

    #command reset
    command_reset = commands.add_parser('reset')
    command_reset.set_defaults(func=commandReset)    

    arguments = parser.parse_args(args)
    arguments.func(arguments)
    
if __name__ == '__main__':
    main(sys.argv[1:])
    # export_cast_urls()
    # log('good day!')^
    # cast = Podcast(9)
    # print cast.data['short_title']

