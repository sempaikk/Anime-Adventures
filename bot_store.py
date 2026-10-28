"""Shared settings and audit state for the active bot services."""

from pathlib import Path
import sqlite3
import time


class BotStore:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=1)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA busy_timeout=1000')
        if self.connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            self.connection.close()
            raise sqlite3.DatabaseError('Database integrity failed; existing data was preserved.')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS bot_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bot_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,actor_id TEXT NOT NULL,
                reason TEXT NOT NULL,created_at REAL NOT NULL);
        ''')

    def rows(self, sql, args=()):
        return [dict(row) for row in self.connection.execute(sql, args)]

    def get(self, key):
        row = self.connection.execute('SELECT value FROM bot_meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def set(self, key, value):
        with self.connection:
            self.connection.execute('INSERT OR REPLACE INTO bot_meta VALUES(?,?)', (key, str(value)))

    def audit(self, kind, actor_id, reason):
        cursor = self.connection.execute('INSERT INTO bot_audit(kind,actor_id,reason,created_at) VALUES(?,?,?,?)',
                                         (kind, str(actor_id), reason, self.clock()))
        return cursor.lastrowid

    def cleanup(self):
        with self.connection:
            self.connection.execute('DELETE FROM bot_audit WHERE id NOT IN(SELECT id FROM bot_audit ORDER BY id DESC LIMIT 1000)')

    def close(self):
        self.connection.close()
