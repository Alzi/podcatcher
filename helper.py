"""Some helper classes
"""

import os.path
import sqlite3
from datetime import datetime

LOG_PATH = "logs/"
DB_PATH = "C:/Daten/Projekte/Python-Projekte/podcatcher/src/database.sq3"

class Logger(object):
    """Simple notes- and errors-logger
    """
    def __init__(self):
        logpath = os.path.join(LOG_PATH, "logs.txt")
        self.fileHandler = open(logpath,"a")
    
    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.fileHandler.close()

    def write(self, data):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.fileHandler.write("%s:\t%s\n" % (now,data))

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


def log(message):
    with Logger() as l:
        l.write(message)        