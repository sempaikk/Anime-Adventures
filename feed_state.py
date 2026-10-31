"""Bounded source history and private delivery diagnostics, independent of image bytes."""

import hashlib
import json


class FeedState:
    def __init__(self, feed):
        self.feed, self.db = feed, feed.db
        feed.query('''CREATE TABLE IF NOT EXISTS banner_seen(
            source_message TEXT NOT NULL, signature TEXT NOT NULL, observed REAL NOT NULL,
            PRIMARY KEY(source_message,signature))''')
        feed.query('''CREATE TABLE IF NOT EXISTS banner_diagnostics(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), polled REAL NOT NULL DEFAULT 0,
            observed REAL NOT NULL DEFAULT 0, received REAL NOT NULL DEFAULT 0,
            source_message TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
            skipped INTEGER NOT NULL DEFAULT 0)''')
        feed.query('INSERT OR IGNORE INTO banner_diagnostics(singleton) VALUES(1)')
        columns={row[1] for row in feed.query('PRAGMA table_info(banner_diagnostics)')}
        for name,definition in (('received_source',"TEXT NOT NULL DEFAULT ''"),('received_version','REAL NOT NULL DEFAULT 0'),('observed_at','REAL NOT NULL DEFAULT 0')):
            if name not in columns:
                feed.query('ALTER TABLE banner_diagnostics ADD COLUMN '+name+' '+definition)
        feed.query('CREATE TABLE IF NOT EXISTS banner_source_floor(singleton INTEGER PRIMARY KEY CHECK(singleton=1), source_message TEXT NOT NULL)')
        feed.query('CREATE TABLE IF NOT EXISTS banner_retracted(source_message TEXT PRIMARY KEY, observed REAL NOT NULL)')
        feed.query('''CREATE TABLE IF NOT EXISTS banner_delivery_summary(
            channel_id TEXT PRIMARY KEY, confirmed REAL NOT NULL, source_message TEXT NOT NULL,
            latency REAL NOT NULL)''')
        # Seed from confirmed data before the normal cache expiry can remove it.
        for row in feed.query('SELECT source_message,images,created_at FROM banner_events').fetchall():
            self.remember(row['source_message'], json.loads(row['images']), row['created_at'])
        self.db.commit()

    @staticmethod
    def signature(images):
        return hashlib.sha256(':'.join(sorted(images)).encode()).hexdigest()

    def known(self, message_id, images):
        return bool(self.feed.query('SELECT 1 FROM banner_seen WHERE source_message=? AND signature=?',
            (message_id, self.signature(images))).fetchone())

    def obsolete(self, message_id):
        if self.feed.query('SELECT 1 FROM banner_retracted WHERE source_message=?', (message_id,)).fetchone():
            return True
        row = self.feed.query('SELECT source_message FROM banner_source_floor WHERE singleton=1').fetchone()
        return bool(row and int(message_id) <= int(row[0]))

    def retract(self, message_id):
        with self.db:
            self.feed.query('INSERT OR REPLACE INTO banner_retracted VALUES(?,?)', (message_id, self.feed.clock()))
            self.feed.query("UPDATE banner_jobs SET state='superseded' WHERE state='pending' AND event_id IN (SELECT id FROM banner_events WHERE source_message=?)", (message_id,))
            self.feed.query('DELETE FROM banner_retracted WHERE source_message NOT IN (SELECT source_message FROM banner_retracted ORDER BY observed DESC LIMIT 2048)')

    def remember(self, message_id, images, created):
        self.feed.query('INSERT OR IGNORE INTO banner_seen VALUES(?,?,?)',
            (message_id, self.signature(images), created))

    def observe(self, message_id, created):
        old=self.feed.query('SELECT source_message,observed FROM banner_diagnostics WHERE singleton=1').fetchone()
        if old['source_message'] and (int(message_id)<int(old['source_message']) or (message_id==old['source_message'] and created<=old['observed'])):
            return
        self.feed.query('UPDATE banner_diagnostics SET observed=?,source_message=?,observed_at=? WHERE singleton=1',
            (created, message_id,self.feed.clock()))
        self.db.commit()

    def poll(self):
        # A healthy metadata poll is not proof that a failed image download was
        # repaired. Retain reception/resource errors until current bytes verify.
        self.feed.query("""UPDATE banner_diagnostics SET polled=?,error=CASE
            WHEN error IN ('source_unavailable','authorized_source_unavailable','connecting',
                           'reader_failed','login_failed','account_action_required') THEN ''
            ELSE error END WHERE singleton=1""", (self.feed.clock(),))
        self.db.commit()

    def error(self, reason):
        # Controlled short reason codes only; never serialize exceptions or URLs.
        self.feed.query('UPDATE banner_diagnostics SET error=? WHERE singleton=1', (reason[:60],))
        self.db.commit()

    def received(self, skipped=0, *, message_id=None, created=None):
        old=self.feed.query('SELECT source_message,observed FROM banner_diagnostics WHERE singleton=1').fetchone()
        message_id = message_id or old['source_message']
        created = created if created is not None else old['observed']
        if old['source_message'] and (int(message_id) < int(old['source_message']) or
                (message_id == old['source_message'] and created < old['observed'])):
            return False
        self.feed.query("UPDATE banner_diagnostics SET received=?,skipped=?,error='',received_source=?,received_version=? WHERE singleton=1",
                        (self.feed.clock(), skipped,message_id, created))
        return True

    def confirmed(self, job):
        event = self.feed.query('SELECT source_message,created_at FROM banner_events WHERE id=?', (job['event_id'],)).fetchone()
        if event:
            self.feed.query('INSERT OR REPLACE INTO banner_delivery_summary VALUES(?,?,?,?)',
                (job['channel_id'], self.feed.clock(), event['source_message'], max(0, self.feed.clock()-event['created_at'])))

    def prune(self):
        # Keep a small global source history, not one image archive per server.
        removed = self.feed.query('''SELECT source_message FROM banner_seen WHERE rowid NOT IN
            (SELECT rowid FROM banner_seen ORDER BY length(source_message) DESC,source_message DESC,observed DESC LIMIT 2048)''').fetchall()
        if removed:
            old = self.feed.query('SELECT source_message FROM banner_source_floor WHERE singleton=1').fetchone()
            floor = max([int(row[0]) for row in removed] + ([int(old[0])] if old else []))
            self.feed.query('INSERT OR REPLACE INTO banner_source_floor VALUES(1,?)', (str(floor),))
        self.feed.query('''DELETE FROM banner_seen WHERE rowid NOT IN
            (SELECT rowid FROM banner_seen ORDER BY length(source_message) DESC,source_message DESC,observed DESC LIMIT 2048)''')
        self.feed.query('DELETE FROM banner_delivery_summary WHERE channel_id NOT IN (SELECT channel_id FROM banner_targets)')

    def snapshot(self, guild_id=None):
        result = dict(self.feed.query('SELECT * FROM banner_diagnostics WHERE singleton=1').fetchone())
        target = self.feed.target(guild_id) if guild_id is not None else None
        if target:
            row = self.feed.query('SELECT * FROM banner_delivery_summary WHERE channel_id=?', (target['channel_id'],)).fetchone()
            result['delivery'] = dict(row) if row else None
        pending = self.feed.query("SELECT count(*) n,min(e.created_at) oldest FROM banner_jobs j JOIN banner_events e ON e.id=j.event_id JOIN banner_targets t ON t.channel_id=j.channel_id WHERE j.state IN ('pending','sending','uncertain')"
            + (' AND j.guild_id=?' if guild_id is not None else ''), (str(guild_id),) if guild_id is not None else ()).fetchone()
        result.update(pending=pending['n'], oldest=pending['oldest'])
        return result

    def network_summary(self):
        rows=self.feed.query("SELECT j.state,count(*) n FROM banner_jobs j JOIN banner_targets t ON t.channel_id=j.channel_id GROUP BY j.state").fetchall()
        states={r['state']:r['n'] for r in rows}
        timings=sorted(r[0] for r in self.feed.query('SELECT latency FROM banner_delivery_summary ORDER BY confirmed DESC LIMIT 4096'))
        return {'targets':self.feed.query('SELECT count(*) FROM banner_targets').fetchone()[0],
            'pending':sum(states.get(k,0) for k in ('pending','sending','uncertain')),
            'blocked':sum(states.get(k,0) for k in ('unavailable','oversize','rejected')),
            'p95':timings[max(0,(95*len(timings)+99)//100-1)] if timings else None}
