"""Database module to handle all database functions of podcatcher
"""

import sqlite3

DB_PATH = "C:/Daten/Projekte/Python-Projekte/podcatcher/src/database.sq3"

ST_UPDATE_DAILY = 0
ST_UPDATE_WEEKLY = 1
ST_NO_UPDATE = 2

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
        """called after with-stamement block.
        """
        self.conn.close()

    def getLastId(self):
        return self.cursor.lastrowid

    def sql(self, sql, parameters=()):
        """execute query and return result if present.
        """
        self.cursor.execute(sql,parameters)
        self.conn.commit()
        return self.cursor.fetchall()

# def createTableCasts():
#     """database-init: table casts
#     """
#     with DB() as dbHandler:
#         dbHandler.sql(
#             "CREATE TABLE casts (id INTEGER PRIMARY KEY \
#             AUTOINCREMENT, title TEXT, url TEXT,\
#             last_updated TEXT, short_title TEXT, status INT)"
#         )

# def createTableShows():
#     """database-init: table shows
#     """
#     with DB() as dbHandler:
#         dbHandler.sql(
#             "CREATE TABLE shows (id INTEGER PRIMARY KEY AUTOINCREMENT, \
#                 feed_id TEXT, title TEXT, subtitle TEXT, author TEXT, \
#                 media_link TEXT, published TEXT, status INT, hash TEXT)"
#         )

def get_cast_data(cast_id):
    with DB() as db_handler:
        result = db_handler.sql(
            'SELECT title, short_title, url, last_updated \
            FROM casts WHERE id=?',
            str(cast_id)
        )
    if result:
        data = {
            'title': result[0][0],
            'short_title': result[0][1],
            'url': result[0][2],
            'last_updated': result[0][3]
        }
        return data
    else:
        raise KeyError("Cast with id %d doesn't exist." % cast_id)

def get_ids_for_update(status):
    sql_add = ''
    if status == ST_UPDATE_WEEKLY:
        pass

    with DB() as db_handler:
        result = db_handler.sql(
            'SELECT id from casts WHERE status = ?',
            str(STATUS_UPDATE))

