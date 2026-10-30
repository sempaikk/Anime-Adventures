"""Bounded optional tools. Additive tables never replace relay state or consent."""

import hashlib
import json
import math
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MODULES = ('knowledge', 'planning', 'parties', 'reminders', 'events')
LIMITS = {'favorite': 20, 'team': 5, 'goal': 10, 'owned': 100, 'run': 30, 'template': 5}


def packed(value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if len(data.encode()) > 8192:
        raise ValueError('This entry is too large. Shorten it before saving.')
    return data


def timezone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('Use an IANA timezone, for example America/Sao_Paulo or Europe/London.') from None


class AdventureStore:
    def __init__(self, base):
        self.base, self.db = base, base.connection
        self.clock = lambda: base.clock()
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS bot_tool_settings(
          guild TEXT PRIMARY KEY,data TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS bot_tool_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,guild TEXT NOT NULL,actor TEXT NOT NULL,
          before_data TEXT NOT NULL,after_data TEXT NOT NULL,created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS bot_tool_history_guild ON bot_tool_history(guild,id);
        CREATE TABLE IF NOT EXISTS bot_tool_data(
          user TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,data TEXT NOT NULL,
          updated REAL NOT NULL,PRIMARY KEY(user,kind,name));
        CREATE TABLE IF NOT EXISTS bot_tool_preferences(
          user TEXT PRIMARY KEY,timezone TEXT NOT NULL DEFAULT 'UTC',quiet_start INTEGER,
          quiet_end INTEGER,feed_alerts INTEGER NOT NULL DEFAULT 0,alert_guild TEXT);
        CREATE TABLE IF NOT EXISTS bot_tool_parties(
          id TEXT PRIMARY KEY,guild TEXT NOT NULL,channel TEXT NOT NULL,owner TEXT NOT NULL,
          mode TEXT NOT NULL,starts REAL NOT NULL,capacity INTEGER NOT NULL,requirements TEXT NOT NULL,
          expires REAL NOT NULL,state TEXT NOT NULL DEFAULT 'draft',version INTEGER NOT NULL DEFAULT 1,
          message TEXT,event TEXT,created REAL NOT NULL,attempted REAL NOT NULL DEFAULT 0,
          rendered INTEGER NOT NULL DEFAULT 0,render_after REAL NOT NULL DEFAULT 0,
          event_done INTEGER NOT NULL DEFAULT 0,event_retry REAL NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS bot_tool_party_expiry ON bot_tool_parties(state,expires);
        CREATE TABLE IF NOT EXISTS bot_tool_members(
          party TEXT NOT NULL,user TEXT NOT NULL,joined REAL NOT NULL,ready INTEGER NOT NULL DEFAULT 0,
          position INTEGER NOT NULL,PRIMARY KEY(party,user),UNIQUE(party,position));
        CREATE TABLE IF NOT EXISTS bot_tool_reminders(
          id TEXT PRIMARY KEY,user TEXT NOT NULL,guild TEXT NOT NULL,body TEXT NOT NULL,due REAL NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending',generation INTEGER NOT NULL DEFAULT 1,
          attempted REAL NOT NULL DEFAULT 0,message TEXT,dm TEXT,nonce TEXT NOT NULL,
          error TEXT NOT NULL DEFAULT '',created REAL NOT NULL,purpose TEXT NOT NULL DEFAULT 'manual',
          next_try REAL NOT NULL DEFAULT 0,bundle TEXT,digest TEXT NOT NULL DEFAULT '[]',
          source_ref TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS bot_tool_reminder_due ON bot_tool_reminders(state,due);
        CREATE INDEX IF NOT EXISTS bot_tool_reminder_user ON bot_tool_reminders(user,created);
        CREATE TABLE IF NOT EXISTS bot_tool_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,detail TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS bot_case_followup(
          kind TEXT NOT NULL,case_id INTEGER NOT NULL,guild TEXT NOT NULL,assigned TEXT,
          answer TEXT NOT NULL DEFAULT '',appeal TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1,
          image BLOB,image_type TEXT,image_expires REAL,updated REAL NOT NULL,
          PRIMARY KEY(kind,case_id,guild));
        CREATE TABLE IF NOT EXISTS bot_feature_gates(
          module TEXT PRIMARY KEY,guilds TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
        ''')
        with self.db:
            self.db.execute("UPDATE bot_tool_reminders SET state='uncertain' WHERE state='sending'")

    def rows(self, sql, args=()):
        return self.base.rows(sql, args)

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def budget(self):
        pages = self.db.execute('PRAGMA page_count').fetchone()[0] - self.db.execute('PRAGMA freelist_count').fetchone()[0]
        if pages * self.db.execute('PRAGMA page_size').fetchone()[0] >= 112 * 1024 * 1024:
            raise ValueError('Optional tools are temporarily full. Existing feeds and saved entries are preserved.')
        if self.one('SELECT count(*) n FROM bot_tool_data')['n'] >= 50000:
            raise ValueError('Optional storage is full. Remove an old entry before saving another.')

    def settings(self, guild):
        row = self.one('SELECT * FROM bot_tool_settings WHERE guild=?', (str(guild),))
        data = {'modules': [x for x in MODULES if x!='events'], 'party_channel': None, 'quiet_start': None, 'quiet_end': None, 'timezone': 'UTC'}
        if row:
            data.update(json.loads(row['data']))
        return data, row['version'] if row else 0

    def enabled(self, guild, module):
        gate = self.one('SELECT guilds FROM bot_feature_gates WHERE module=?', (module,))
        if gate:
            allowed = json.loads(gate['guilds'])
            if '*' not in allowed and str(guild) not in allowed:
                return False
        return module in self.settings(guild)[0]['modules']

    def require(self, guild, module):
        if not self.enabled(guild, module):
            raise ValueError('This tool is disabled in this server or is awaiting pilot release.')

    def configure(self, guild, actor, data, expected):
        allowed = {'modules', 'party_channel', 'quiet_start', 'quiet_end', 'timezone'}
        if set(data) - allowed or not isinstance(data.get('modules'), list) or set(data['modules']) - set(MODULES):
            raise ValueError('Only the documented tool settings can be imported.')
        timezone(data.get('timezone', 'UTC'))
        for field in ('quiet_start', 'quiet_end'):
            v = data.get(field)
            if v is not None and (type(v) is not int or not 0 <= v <= 23):
                raise ValueError('Quiet hours must be whole hours from 0 to 23.')
        if (data.get('quiet_start') is None) != (data.get('quiet_end') is None):
            raise ValueError('Provide both quiet-hour boundaries, or neither.')
        if data.get('party_channel') is not None and not str(data['party_channel']).isdigit():
            raise ValueError('Choose an existing server channel.')
        with self.db:
            before, version = self.settings(guild)
            if version != expected:
                raise ValueError('Settings changed. Reopen the review before confirming.')
            self.budget()
            self.db.execute('INSERT INTO bot_tool_settings VALUES(?,?,?) ON CONFLICT(guild) DO UPDATE SET data=excluded.data,version=excluded.version', (str(guild), packed(data), version + 1))
            self.db.execute('INSERT INTO bot_tool_history(guild,actor,before_data,after_data,created) VALUES(?,?,?,?,?)', (str(guild), str(actor), packed(before), packed(data), self.clock()))
            self.db.execute('DELETE FROM bot_tool_history WHERE id NOT IN (SELECT id FROM bot_tool_history ORDER BY id DESC LIMIT 500)')
        return version + 1

    def save(self, user, kind, name, data):
        if kind not in LIMITS or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('Choose a supported entry type and a name in 1 to 80 characters.')
        name = name.strip()
        value = packed(data)
        with self.db:
            if not self.one('SELECT 1 FROM bot_tool_data WHERE user=? AND kind=? AND name=?', (str(user), kind, name)):
                self.budget()
                n = self.one('SELECT count(*) n FROM bot_tool_data WHERE user=? AND kind=?', (str(user), kind))['n']
                if n >= LIMITS[kind]:
                    raise ValueError(f'You can keep {LIMITS[kind]} {kind} entries. Remove one first.')
            self.db.execute('INSERT INTO bot_tool_data VALUES(?,?,?,?,?) ON CONFLICT(user,kind,name) DO UPDATE SET data=excluded.data,updated=excluded.updated', (str(user), kind, name, value, self.clock()))

    def entries(self, user, kind):
        return self.rows('SELECT name,data,updated FROM bot_tool_data WHERE user=? AND kind=? ORDER BY updated DESC', (str(user), kind))

    def remove(self, user, kind, name):
        with self.db:
            return self.db.execute('DELETE FROM bot_tool_data WHERE user=? AND kind=? AND name=?', (str(user), kind, name)).rowcount

    def preferences(self, user):
        return self.one('SELECT * FROM bot_tool_preferences WHERE user=?', (str(user),)) or {'timezone': 'UTC', 'quiet_start': None, 'quiet_end': None, 'feed_alerts': 0}

    def set_preferences(self, user, zone, start=None, end=None, alerts=False, guild=None):
        timezone(zone)
        if (start is None) != (end is None) or any(type(v) is not int or not 0 <= v <= 23 for v in (start, end) if v is not None):
            raise ValueError('Use two quiet-hour boundaries from 0 to 23, or leave both empty.')
        with self.db:
            self.budget()
            if alerts and not self.preferences(user)['feed_alerts'] and self.one('SELECT count(*) n FROM bot_tool_preferences WHERE feed_alerts=1')['n']>=2000:
                raise ValueError('Source-alert subscriptions are temporarily full. Manual reminders and other preferences remain available.')
            self.db.execute('INSERT OR REPLACE INTO bot_tool_preferences VALUES(?,?,?,?,?,?)', (str(user), zone, start, end, int(bool(alerts)), str(guild) if guild else None))

    def reminder(self, user, guild, text, due):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 300 or not math.isfinite(due) or not self.clock() + 30 <= due <= self.clock() + 366 * 86400:
            raise ValueError('Use a message in 1 to 300 characters and a time from 30 seconds to one year ahead.')
        with self.db:
            self.require(guild, 'reminders')
            self.budget()
            if self.one("SELECT count(*) n FROM bot_tool_reminders WHERE user=? AND purpose='manual' AND state IN ('pending','sending','uncertain')", (str(user),))['n'] >= 5:
                raise ValueError('You can keep five active reminders. Cancel one first.')
            if self.one('SELECT count(*) n FROM bot_tool_reminders')['n'] >= 20000:
                raise ValueError('The reminder queue is full. Try later.')
            ident = secrets.token_hex(6)
            nonce = str(int.from_bytes(hashlib.sha256(('reminder:' + ident).encode()).digest()[:8], 'big') >> 1)
            self.db.execute('INSERT INTO bot_tool_reminders(id,user,guild,body,due,nonce,created) VALUES(?,?,?,?,?,?,?)', (ident, str(user), str(guild), text.strip(), due, nonce, self.clock()))
            return ident

    def cancel(self, user, ident):
        with self.db:
            old=self.one('SELECT state FROM bot_tool_reminders WHERE id=? AND user=?',(ident,str(user)))
            result=self.db.execute("UPDATE bot_tool_reminders SET state='cancelled',generation=generation+1 WHERE id=? AND user=? AND state IN ('pending','sending','uncertain')", (ident, str(user))).rowcount
            if result and old['state'] in ('sending','uncertain'):
                self.db.execute("UPDATE bot_tool_reminders SET state='cancelled',generation=generation+1 WHERE bundle=? AND user=? AND state='pending'",(ident,str(user)))
            elif result:
                self.db.execute("UPDATE bot_tool_reminders SET bundle=NULL WHERE bundle=? AND user=? AND state='pending'",(ident,str(user)))
            return result

    def snooze(self, user, ident, seconds=600):
        old = self.one('SELECT * FROM bot_tool_reminders WHERE id=? AND user=?', (ident, str(user)))
        if not old:
            raise ValueError('Choose one of your reminders.')
        self.require(old['guild'],'reminders')
        self.budget()
        if old['state'] in ('sending','uncertain'):
            raise ValueError('This reminder is still being confirmed. Cancel it first before explicitly requesting a new one.')
        with self.db:
            self.db.execute("UPDATE bot_tool_reminders SET state='cancelled',generation=generation+1 WHERE id=? AND user=?",(ident,str(user)))
            self.db.execute("UPDATE bot_tool_reminders SET bundle=NULL WHERE bundle=? AND user=? AND state='pending'",(ident,str(user)))
            return self.reminder(user, old['guild'], old['body'], self.clock() + seconds)

    def bundle_due(self):
        """One bounded recovery digest per person, without losing per-item receipts."""
        with self.db:
            users=self.rows("SELECT user,guild,purpose FROM bot_tool_reminders WHERE state='pending' AND bundle IS NULL AND due<=? AND next_try<=? GROUP BY user,guild,purpose HAVING count(*)>1 ORDER BY min(due) LIMIT 4",(self.clock(),self.clock()))
            for actor in users:
                rows=self.rows("SELECT * FROM bot_tool_reminders WHERE user=? AND guild=? AND purpose=? AND state='pending' AND bundle IS NULL AND due<=? AND next_try<=? ORDER BY due,id LIMIT 7",(actor['user'],actor['guild'],actor['purpose'],self.clock(),self.clock()))
                if len(rows)<2 or self.clock()-rows[0]['due']<=300 and not all(r['purpose']=='feed' for r in rows):
                    continue
                root=rows[0]['id']
                existing=json.loads(rows[0]['digest'])
                children=[r['id'] for r in rows[1:]]
                self.db.execute('UPDATE bot_tool_reminders SET digest=? WHERE id=?',(json.dumps(list(dict.fromkeys(existing+children))),root))
                for child in children:
                    self.db.execute('UPDATE bot_tool_reminders SET bundle=? WHERE id=? AND state=\'pending\'',(root,child))

    def party(self, guild, channel, owner, mode, starts, capacity, requirements=''):
        if not 1 <= len(mode.strip()) <= 60 or len(requirements) > 300 or type(capacity) is not int or not 2 <= capacity <= 12:
            raise ValueError('Use a mode in 1 to 60 characters, 2 to 12 places and a short description.')
        if not math.isfinite(starts) or not self.clock() <= starts <= self.clock() + 30 * 86400:
            raise ValueError('Choose a start time within the next 30 days.')
        with self.db:
            self.require(guild, 'parties')
            self.budget()
            if self.one("SELECT count(*) n FROM bot_tool_parties WHERE guild=? AND state IN ('draft','open')", (str(guild),))['n'] >= 20:
                raise ValueError('This server already has 20 open or draft groups.')
            if self.one("SELECT count(*) n FROM bot_tool_parties WHERE owner=? AND state IN ('draft','open')", (str(owner),))['n'] >= 3:
                raise ValueError('Close one of your three active groups first.')
            ident = secrets.token_hex(6)
            self.db.execute('INSERT INTO bot_tool_parties(id,guild,channel,owner,mode,starts,capacity,requirements,expires,created) VALUES(?,?,?,?,?,?,?,?,?,?)', (ident, str(guild), str(channel), str(owner), mode.strip(), starts, capacity, requirements.strip(), starts + 7200, self.clock()))
            self.db.execute('INSERT INTO bot_tool_members VALUES(?,?,?,0,0)', (ident, str(owner), self.clock()))
            return ident

    def party_record(self, ident, guild):
        row = self.one('SELECT * FROM bot_tool_parties WHERE id=? AND guild=?', (ident, str(guild)))
        if not row:
            raise ValueError('This group is unavailable in this server.')
        return row

    def members(self, ident):
        return self.rows('SELECT * FROM bot_tool_members WHERE party=? ORDER BY position', (ident,))

    def join(self, ident, guild, user, *, ready=False, leave=False,unready=False):
        with self.db:
            self.require(guild, 'parties')
            row = self.party_record(ident, guild)
            if row['state'] != 'open' or row['expires'] <= self.clock():
                raise ValueError('This group has closed or expired.')
            if leave:
                if str(user) == row['owner']:
                    raise ValueError('The organizer must close the group instead.')
                self.db.execute('DELETE FROM bot_tool_members WHERE party=? AND user=?', (ident, str(user)))
            else:
                # SQLite serialization and the UNIQUE key make a final-slot click
                # atomic. Additional people enter the ordered waiting list.
                if len(self.members(ident)) >= row['capacity'] + 12 and not self.one('SELECT 1 FROM bot_tool_members WHERE party=? AND user=?', (ident, str(user))):
                    raise ValueError('The group and waiting list are full.')
                self.db.execute('INSERT OR IGNORE INTO bot_tool_members(party,user,joined,ready,position) SELECT ?,?,?,0,COALESCE(max(position),-1)+1 FROM bot_tool_members WHERE party=?', (ident, str(user), self.clock(),ident))
                if ready or unready:
                    self.db.execute('UPDATE bot_tool_members SET ready=? WHERE party=? AND user=?', (int(ready), ident, str(user)))
            self.db.execute('UPDATE bot_tool_parties SET version=version+1 WHERE id=?', (ident,))

    def export_user(self, user):
        return {'entries': self.rows('SELECT kind,name,data,updated FROM bot_tool_data WHERE user=?', (str(user),)), 'preferences': self.preferences(user), 'reminders': self.rows('SELECT id,body,due,state,error FROM bot_tool_reminders WHERE user=?', (str(user),)), 'group_participation':self.rows('SELECT p.id,p.guild,p.mode,p.starts,p.state,m.ready FROM bot_tool_parties p JOIN bot_tool_members m ON m.party=p.id WHERE m.user=?',(str(user),)), 'organized_groups':self.rows('SELECT id,guild,channel,mode,starts,capacity,requirements,state FROM bot_tool_parties WHERE owner=?',(str(user),))}

    def erase_user(self, user):
        with self.db:
            self.db.execute('DELETE FROM bot_tool_data WHERE user=?', (str(user),))
            self.db.execute('DELETE FROM bot_tool_preferences WHERE user=?', (str(user),))
            self.db.execute("UPDATE bot_tool_reminders SET state='cancelled',body='',generation=generation+1 WHERE user=?", (str(user),))
            self.db.execute("UPDATE bot_tool_parties SET state='closed',version=version+1 WHERE owner=?", (str(user),))
            self.db.execute('DELETE FROM bot_tool_members WHERE user=?', (str(user),))

    def cleanup(self):
        with self.db:
            self.db.execute("UPDATE bot_tool_parties SET state='expired',version=version+1 WHERE state IN ('draft','open') AND expires<?", (self.clock(),))
            self.db.execute('DELETE FROM bot_tool_members WHERE party IN (SELECT id FROM bot_tool_parties WHERE expires<?)', (self.clock() - 7 * 86400,))
            self.db.execute('DELETE FROM bot_tool_parties WHERE expires<?', (self.clock() - 7 * 86400,))
            self.db.execute("DELETE FROM bot_tool_reminders WHERE state NOT IN ('pending','sending','uncertain') AND created<?", (self.clock() - 30 * 86400,))
            self.db.execute('UPDATE bot_case_followup SET image=NULL,image_type=NULL WHERE image_expires<?', (self.clock(),))
            self.db.execute('DELETE FROM bot_case_followup WHERE updated<?', (self.clock() - 30 * 86400,))
            self.db.execute('DELETE FROM bot_tool_events WHERE id NOT IN (SELECT id FROM bot_tool_events ORDER BY id DESC LIMIT 1000)')

    def record(self, kind, detail):
        with self.db:
            self.db.execute('INSERT INTO bot_tool_events(kind,detail,created) VALUES(?,?,?)', (kind[:50], packed(detail), self.clock()))
