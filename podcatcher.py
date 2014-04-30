# -*- coding: UTF-8 -*-
"""
podcatcher.py is a simple commandline tool to manage podcast feeds

"""

import sqlite3
from datetime import datetime
from hashlib import sha256
import urllib2
import sys
import os
import re

from Lib import feedparser
from mutagen.id3 import ID3, TXXX
from mutagen.mp4 import MP4
from mutagen import File as mutagen_File

__author__ = "Marc Wesemeier, Wackernheim, Germany"
__date__ = "2014-04-17"
__license__ = "WTFPL V2"
__version__ = "0.0.1"
__maintainer__ = "Marc Wesemeier"
__email__ = "projectleviathan@arcor.de"
__status__ = "Development"

URLS = [
"http://www.kuechenstud.io/kuechenradio/feed/mp3",
"http://in-trockenen-buechern.de:80/feed/mp3/",
"http://feeds.feedburner.com/WrintFerngespraeche",
"http://feeds.feedburner.com/WrintOrtsgespraeche",
"http://feeds.feedburner.com/WrintRealitaetsabgleich",
"http://www.staatsbuergerkunde-podcast.de/feed/mp3-rss",
"http://wir.muessenreden.de/feed/podcast",
"http://spoileralert.bildungsangst.de/feed/opus",
"http://feeds.feedburner.com/WrintHolgerRuftAn",
"http://feeds.feedburner.com/DieWrintheit",
"http://1337kultur.de/feed/podcast-ogg/",
"http://web.ard.de/radiotatort/rss/podcast.xml",
"http://www.alternativlos.org/ogg.rss",
"http://bartocast.de/?feed=podcast",
"http://www.hoaxilla.de/podcast/bth.xml",
"http://feeds.feedburner.com/cre-podcast",
"http://feeds.feedburner.com/dancarlin/history?format=xml",
"http://feeds.feedburner.com/datenschorle?format=podcast",
"http://feedpress.me/dbp",
"feed://fnordfunk.de/?feed=podcast",
"http://feeds.feedburner.com/fokus-europa-oga",
"http://www.hoaxilla.de/podcast/hoaxilla.xml",
"http://feeds.feedburner.com/UnbenannterPodcastberEsoterikUndhnlichen",
"http://klabautercast.de/feed/podcast",
"http://feeds.feedburner.com/mikrodilettanten",
"http://feeds.feedburner.com/NotSafeForWorkPodcast",
"http://www.psycho-talk.de/feed/oga",
"http://feeds.feedburner.com/raumzeit-podcast",
"http://pcast.sr-online.de/feeds/diskurs/feed.xml",
"http://pcast.sr-online.de/feeds/fragen/feed.xml",
"http://schallrauch.hoersuppe.de/sur/opus",
"http://www.hoaxilla.de/podcast/skeptoskop.xml",
"http://feeds.feedburner.com/soziopodaudio",
"http://kaliban.podspot.de/rss",
"http://feeds.feedburner.com/sternengeschichten",
"http://trojaalert.bildungsangst.de/feed/opus",
"http://feeds.feedburner.com/VorgedachtPodcast",
"http://vorzeiten.net/opus",
"http://www.wikigeeks.de/feed/ogg",
"http://80erman.podcaster.de/younginthe80s.rss",
"http://feeds.feedburner.com/MonoxydDieWahrheit",
"http://anyca.st/feed/ogg",
"http://n00bcore.de/feed/mp3"
]

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
"text/html"
]

#set STATUS_OLDER_POST if post is > this days old
DAYS_OLDER_POST = 14

#minutes that should be between update-attempts
UPDATE_TIME = 120	

DB_PATH = "database.db"
LOG_PATH = "logs/"
MEDIA_PATH = "C:/Daten/Foobar/Podcasts/"
STATUS_UPDATE_CAST = 0
STATUS_NOTACTIVE_CAST = 1
STATUS_ARCHIVED_CAST = 2

STATUS_DOWNLOADED_POST = 0
STATUS_NEW_POST = 1
STATUS_OLDER_POST = 2

#------------------------------------------- -------------------------------------------------------------
#------------------------------------------- class DB ----------------------------------------------------
#------------------------------------------- -------------------------------------------------------------

class DB(object):
	"""simple handler of sqlite3 queries.
	"""
	def __init__(self,filepath=DB_PATH):
		self.conn = sqlite3.connect(filepath)
		self.cursor = self.conn.cursor()

	def __enter__(self):
		"""for using pythons with-statement.
		"""
		return self

	def __exit__(self, type, value, traceback):
		"""called after pythons with-stamement.
		"""
		self.conn.close()

	def sql(self, sql, parameters=()):
		"""execute query and return result if present.
		"""
		self.cursor.execute(sql,parameters)
		self.conn.commit()
		return self.cursor.fetchall()

class Logger(object):
	"""Simple notes- and errors-logger
	"""
	def __init__(self, logType="Note"):
		if logType == "Note":
			logpath = os.path.join(LOG_PATH, "notes.txt")
		elif logType == "Error":
			logpath = os.path.join(LOG_PATH, "errors.txt")
		self.fileHandler = open(logpath,"a")
	
	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		self.fileHandler.close()

	def write(self, data):
		now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		self.fileHandler.write("%s:\t%s\n%s\n" % (now,data,60*'-'))

#------------------------------------------- -------------------------------------------------------------
#------------------------------------------- class Post --------------------------------------------------
#------------------------------------------- -------------------------------------------------------------

class Post(object):
	"""Handle the data from one show
	"""
	def __init__(self, entry, feedId):
		self.entry = entry
		self.feedId = feedId
		self.has_audio = False

		self.title = self._getTitle()
		self.subtitle = self._getSubtitle()
		self.author = self._getAuthor()
		self.published = self._getPublished()
		self.url = self._extractMediaLinks()	#FIXME: multiple Media-Links aren't handled
		self.hash = self._getHash()

		self.daysOld = self._getDaysSincePublished()

	def download(self):
		"""download media to hard drive
		"""
		url = self.mediaLinks[0][0]
		filename = os.path.basename(url)
		if not filename in os.listdir(MEDIA_PATH):
			data = downloadAudio(url)
			path = os.path.join(MEDIA_PATH,filename)
			with open (path,"wb") as fh:
				fh.write(data)
			self._tagFile(path)
		else:
			print "File allready downloaded!"
		self._setStatusDownloaded()

	def _tagFile(self, path):
		"""use mutagen to set (ID-3)-Tags inside audio file
		PODCAST_STATUS = new
		useful for foobar2000's dynamic-playlist function
		"""
		try:
			audio = ID3(path)
		except:
			try:
				audio = MP4(path)
			except:
				try:
					audio = mutagen_File(path)
				except:
					print "Couldn't tag audio-file."
				else:
					audio[u"PODCAST_STATUS"] = u"new"
					audio.save()
			else:
				audio['----:com.apple.iTunes:PODCAST_STATUS'] = "new"
				audio.save()
		else:
			audio.add(TXXX(encoding=3,desc=u"PODCAST_STATUS",text=u"new"))
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
			return True
		return False

	def save(self):
		"""save post to database
		"""
		if self.url:
			if not self.is_saved():
				print "Writing post to db: %s" % makePrintable(self.title)
				with DB() as dbHandler:
					if self.daysOld > DAYS_OLDER_POST:
						status = STATUS_OLDER_POST
					else:
						status = STATUS_NEW_POST
					dbHandler.sql (
						"INSERT INTO shows VALUES (?,?,?,?,?,?,?,?,?)",
						(
							None, self.feedId, self.title, self.subtitle, 
							self.author, self.url, self.published, 
							status, self.hash
						)
					)
			else:
				print "allready in db."
		else:
			print "this post has no audio file\n%s" % self.title

	def _getDaysSincePublished(self):
		"""calculate days between today and date of publishing 
		"""
		today = datetime.now()
		published = string2DateTime(self.published)
		diff = today-published
		return diff.days

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
		if self.entry.title:
			return self.entry.title
		else:
			return u"no-title"

	def _getSubtitle(self):
		"""Get subtitle-data from feed-entry.
		"""
		if self.entry.subtitle:
			return self.entry.subtitle
		else:
			return u"no-subtitle"

	def _extractMediaLinks(self):
		"""try to find media-infos of this feed-post
		"""
		self.mediaLinks = []
		newTypes = set()
		for link in self.entry.links:
			if link.type in AUDIO_MIME_TYPES:
				self.mediaLinks.append((link.href,link.type))
				self.has_audio = True
			elif link.type in KNOWN_MIME_TYPES:
				pass
			else:
				newTypes.add(link.type)
		if newTypes:
			with Logger() as log:
				log.write("New MimeType(s) found:\n%s" % newTypes)
		if not self.mediaLinks:
			self.has_audio = False
			return None
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
			oldString = "%s %s %s %s %s" % (published[0],published[1],published[2],published[3],published[4])
			date = datetime.strptime( oldString, "%a, %d %b %Y %H:%M:%S" )
			newString = date.strftime("%Y-%m-%d %H:%M:%S")
			published = unicode(newString)
		return published

	def _getAuthor(self):
		"""Get author-data from feed-entry.
		"""
		if self.entry.author:
			return self.entry.author
		else:
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

#------------------------------------------- -------------------------------------------------------------
#------------------------------------------- class Cast -------------------------------------------------
#------------------------------------------- -------------------------------------------------------------

class Cast(object):
	"""Handle all data corresponding to a cast
	"""
	def __init__(self, feedId):
		self.feedId = feedId
		self.title = self._getTitle()
		self.rss = None

	def getLatestPost(self):
		"""return the latest post as Post()
		"""
		if not self.rss:
			self.rss = self._fetchFeed()
		return Post(self.rss.entries[0], self.feedId)

	def showLatestPost(self):
		"""Helper function
		print out the latest post
		"""
		with DB() as dbHandler:
			result = dbHandler.sql(
				"SELECT id, title, published FROM shows WHERE feed_id=? AND status<>? ORDER BY published DESC LIMIT 1",
				(self.feedId,STATUS_DOWNLOADED_POST)
			)
		if result:
			newestPost = result[0]
			try:
				print "Published at %s:\n#%s: '%s'\n" % (
					makePrintable(newestPost[2]), newestPost[0], newestPost[1]
				)
			except:
				print "Encoding-problem couldn't print."
				raise
		else:
			print "No data."

	def update(self):
		"""Main-function to look for new posts.
		"""
		print "Updating %s..." % (self.title)
		self.rss = self._fetchFeed()
		numOfUpdates = 0
		for entry in self.rss.entries:
			post = Post(entry, self.feedId, True)
			if post.is_saved():
				break;
			else:
				print "New post: %s" % (post.published)
				numOfUpdates += 1
				post.save()
		if not numOfUpdates:
			print "Nothing new."
		else:
			now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
			with DB() as dbHandler:
				dbHandler.sql(
					"UPDATE casts SET last_updated=? WHERE id=?",
					(now, self.feedId)
				)

	def _getMinutesSinceLastUpdate(self):
		"""return minutes since last update
		"""
		with DB() as dbHandler:
			last_updated = dbHandler.sql(
				"SELECT last_updated FROM casts WHERE feedId=?",
				(self.feedId,))
		last_updated = string2DateTime(last_updated[0][0])
		#FIXME:finish!

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
		return makePrintable(title[0][0])

#------------------------------------------- -------------------------------------------------------------
#-------------------------------------------------- functions --------------------------------------------
#------------------------------------------- -------------------------------------------------------------

def makePrintable(unprintable):
	"""change unprintable characters into '-'
	"""
	return "".join(
		[['{?}',x][re.match(u"[\[\]\w -.:@~/äöüÄÖÜß]",x)!=None] for x in unprintable ]
	)

def string2DateTime(dtString):
	"""return our string-format as datetime-object
	"""
	return datetime.strptime(dtString, "%Y-%m-%d %H:%M:%S")

def now():
	now = datetime.now()
	nowString = now.strftime("%Y-%m-%d %H:%M:%S")
	return (now,nowString)

def addPodcast(url):
	"""add a new feed-url to database
	"""
	try:
		f = feedparser.parse(url)
	except:
		print ("Couldn't parse. (%s)" % url)
	title = f.feed.title
	now = datetime.now()
	today = now.strftime("%Y-%m-%d %H:%M")
	data = (None, title, url, today, STATUS_UPDATE_CAST)
	with DB() as dbHandler:
		dbHandler.sql(
			"INSERT INTO casts VALUES (?,?,?,?,?)",
			data
		)

def getPodcasts():
	"""Get (id, title, url) tuple-list from all active
	podcasts from DB.
	"""
	with DB() as dbHandler:
		results = dbHandler.sql(
			"SELECT id, title, url, filepath FROM casts WHERE status=?",
			(STATUS_UPDATE_CAST,)
		)
	return results

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
	response = urllib2.urlopen(url, None, 5)
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

#------------------------------------------- -------------------------------------------------------------
#------------------------------------------- Helper Functions --------------------------------------------
#------------------------------------------- -------------------------------------------------------------

def updateAll():
	"""update all podcasts with the status_flag
	set to STATUS_UPDATE_CAST
	"""
	castsToUpdate = getPodcasts()
	for data in castsToUpdate:
		feedId = data[0]
		if feedId > 11:
			cast = Cast(feedId)
			cast.update()

def getNewPosts():
	"""return all new that are not older than DAYS_OLDER_POST
	"""
	with DB() as dbHandler:
		result = dbHandler.sql(
			"SELECT P.title, P.published, F.title, F.id FROM shows AS P JOIN casts AS F ON F.id=P.feed_id WHERE P.status=? ORDER BY F.id, P.published",
			(STATUS_NEW_POST,)
		)
	lastCast = ""
	for line in result:
		if lastCast != line[2]:
			print "---------------------------------------\n%s(%s):" % (makePrintable(line[2]), line[3])
			lastCast = line[2]
		print "'%s'\n(%s)" % (makePrintable(line[0]), makePrintable(line[1]))

def createTableFeeds():
	"""database-init: table casts
	"""
	with DB() as dbHandler:
		dbHandler.sql(
			"CREATE TABLE casts (id INTEGER PRIMARY KEY \
			AUTOINCREMENT, title TEXT, url TEXT,\
			last_updated TEXT, status INT)"
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

def main():
	casts = getPodcasts
	for cast in casts:
		feedId = cast[0]
		title = cast[1]

if __name__ == '__main__':
	# createTableShows()
	updateAll()