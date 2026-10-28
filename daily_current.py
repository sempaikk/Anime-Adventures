"""Keep the current daily source across restarts and cache expiration."""


class DailyCurrent:
    def __init__(self, relay):
        self.relay, self.db = relay, relay.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS daily_current(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), event_id TEXT NOT NULL,
            source_message TEXT NOT NULL, created_at REAL NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS daily_source_head(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), source_message TEXT NOT NULL)''')
        # Existing verified source events seed the guard before any new polling.
        self.db.execute('''INSERT OR IGNORE INTO daily_current
            SELECT 1,id,source_message,created_at FROM daily_events
            ORDER BY length(source_message) DESC,source_message DESC,created_at DESC,rowid DESC LIMIT 1''')
        self.db.execute('''INSERT OR IGNORE INTO daily_source_head
            SELECT singleton,source_message FROM daily_current''')
        current = self.current()
        if current:
            self.remember(current['event_id'], current['source_message'], current['created_at'])
        self.db.commit()

    def current(self):
        return self.db.execute('SELECT * FROM daily_current WHERE singleton=1').fetchone()

    def older(self, source_message, created_at):
        current = self.current()
        head = self.db.execute('SELECT source_message FROM daily_source_head WHERE singleton=1').fetchone()
        return bool((head and int(source_message) < int(head['source_message']))
                    or (current and int(source_message) == int(current['source_message'])
                        and created_at < current['created_at']))

    def observe(self, source_message):
        head = self.db.execute('SELECT source_message FROM daily_source_head WHERE singleton=1').fetchone()
        if head is None or int(source_message) > int(head['source_message']):
            # Seeing a new source is not a receive acknowledgment. Keep old jobs
            # blocked even if downloading the new image needs another attempt.
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO daily_source_head VALUES(1,?)', (source_message,))

    def active_id(self):
        row = self.db.execute('''SELECT c.event_id FROM daily_current c JOIN daily_source_head h
            ON h.singleton=c.singleton AND h.source_message=c.source_message''').fetchone()
        return row['event_id'] if row else None

    def known(self, event_id):
        return self.active_id() == event_id

    def remember(self, event_id, source_message, created_at):
        # Called in the same transaction as validated bytes and delivery jobs.
        current = self.current()
        if current is None or current['event_id'] != event_id:
            self.db.execute('INSERT OR REPLACE INTO daily_current VALUES(1,?,?,?)',
                            (event_id, source_message, created_at))
        self.db.execute("UPDATE daily_jobs SET state='superseded' WHERE event_id<>? AND state='pending'",
                        (event_id,))
