"""Durable relay state in the existing database; originals always stay with their authors."""

import json
import hashlib
from global_moderation import ModerationStore

RETENTION = 30 * 86400
CONTENT_TTL = 3600
CONSENT_VERSION = 1


class GlobalStore(ModerationStore):
    def __init__(self, base):
        self.base, self.db = base, base.connection
        self.clock = lambda: base.clock()
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS global_channels(
          guild_id TEXT PRIMARY KEY,channel_id TEXT UNIQUE NOT NULL,hook_id TEXT NOT NULL,
          active INTEGER NOT NULL,generation INTEGER NOT NULL,panel_id TEXT,enabled_at REAL NOT NULL,
          cursor TEXT NOT NULL DEFAULT '0',error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS global_hooks(
          hook_id TEXT PRIMARY KEY,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,token TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS global_consents(user_id TEXT PRIMARY KEY,version INTEGER NOT NULL,accepted REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS global_messages(
          id TEXT PRIMARY KEY,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,user_id TEXT NOT NULL,
          payload TEXT NOT NULL,fingerprint TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
          deleted INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL,
          checked REAL NOT NULL DEFAULT 0,expires REAL NOT NULL,error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS global_deliveries(
          source_id TEXT NOT NULL,channel_id TEXT NOT NULL,guild_id TEXT NOT NULL,hook_id TEXT NOT NULL,
          state TEXT NOT NULL,receipts TEXT NOT NULL DEFAULT '[]',revision INTEGER NOT NULL DEFAULT 0,
          suppressed INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,
          next_try REAL NOT NULL DEFAULT 0,attempted REAL NOT NULL DEFAULT 0,
          uncertain INTEGER NOT NULL DEFAULT -1,error TEXT NOT NULL DEFAULT '',attempt_payload TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY(source_id,channel_id));
        CREATE INDEX IF NOT EXISTS global_queue ON global_deliveries(state,next_try);
        CREATE INDEX IF NOT EXISTS global_actor ON global_messages(user_id,created);
        CREATE INDEX IF NOT EXISTS global_message_expiry ON global_messages(expires);
        CREATE INDEX IF NOT EXISTS global_payload_cleanup ON global_messages(updated) WHERE payload<>'{}';
        CREATE TABLE IF NOT EXISTS global_receipts(
          message_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS global_receipt_source ON global_receipts(source_id);
        CREATE TABLE IF NOT EXISTS global_blocks(
          scope TEXT NOT NULL,kind TEXT NOT NULL,target TEXT NOT NULL,actor TEXT NOT NULL,
          reason TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(scope,kind,target));
        CREATE TABLE IF NOT EXISTS global_reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL,reporter TEXT NOT NULL,
          guild_id TEXT NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL,reviewed INTEGER NOT NULL DEFAULT 0,
          UNIQUE(source_id,reporter));
        CREATE TABLE IF NOT EXISTS global_prompts(
          notice_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,user_id TEXT NOT NULL,
          guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS global_invitations(
          user_id TEXT PRIMARY KEY,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,
          generation INTEGER NOT NULL,dm_channel_id TEXT NOT NULL DEFAULT '',
          message_id TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,attempted REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS global_limits(
          key TEXT PRIMARY KEY,window REAL NOT NULL,count INTEGER NOT NULL,fingerprint TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS global_attempts(
          user_id TEXT NOT NULL,guild_id TEXT NOT NULL,state TEXT NOT NULL,reason TEXT NOT NULL,
          updated REAL NOT NULL,PRIMARY KEY(user_id,guild_id));
        CREATE INDEX IF NOT EXISTS global_attempt_expiry ON global_attempts(updated);
        """)
        self.init_moderation()
        # A previous process may have stopped after Discord accepted a request.
        # Recover that attempt before sending anything else to this destination.
        with self.db:
            self.db.execute(
                "UPDATE global_deliveries SET state='uncertain' WHERE state='sending'"
            )

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def attempt(self, user, guild, state, reason):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO global_attempts VALUES(?,?,?,?,?)',
                           (str(user),str(guild),state,reason[:300],self.clock()))
            self.db.execute('DELETE FROM global_attempts WHERE updated<?', (self.clock()-3600,))
            self.db.execute('DELETE FROM global_attempts WHERE rowid NOT IN (SELECT rowid FROM global_attempts ORDER BY updated DESC LIMIT 5000)')

    def last_attempt(self, user, guild):
        return self.one('SELECT * FROM global_attempts WHERE user_id=? AND guild_id=? AND updated>?',
                        (str(user),str(guild),self.clock()-3600))

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def channel(self, guild):
        return self.one("SELECT * FROM global_channels WHERE guild_id=?", (str(guild),))

    def source(self, channel):
        return self.one(
            "SELECT * FROM global_channels WHERE channel_id=? AND active=1",
            (str(channel),),
        )

    def channels(self):
        return self.rows("SELECT * FROM global_channels ORDER BY guild_id")

    def hook(self, ident):
        return self.one("SELECT * FROM global_hooks WHERE hook_id=?", (str(ident),))

    def configure(self, guild, channel, hook, token, cursor):
        gid, cid, hid = str(guild), str(channel), str(hook)
        old = self.channel(gid)
        same = bool(
            old and old["active"] and old["channel_id"] == cid and old["hook_id"] == hid
        )
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO global_hooks VALUES(?,?,?,?)",
                (hid, gid, cid, token),
            )
            self.db.execute(
                """INSERT INTO global_channels VALUES(?,?,?,?,?,NULL,?,?, '')
              ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,hook_id=excluded.hook_id,
              active=1,generation=excluded.generation,panel_id=CASE WHEN channel_id=excluded.channel_id
              THEN panel_id ELSE NULL END,enabled_at=excluded.enabled_at,cursor=excluded.cursor,error=''""",
                (
                    gid,
                    cid,
                    hid,
                    1,
                    int(old["generation"]) + 1 if old else 1,
                    old["enabled_at"] if same else self.clock(),
                    old["cursor"] if same else str(cursor),
                ),
            )
            if old and old["channel_id"] != cid:
                self.db.execute(
                    "UPDATE global_deliveries SET state='cancelled' WHERE channel_id=? AND state IN ('queued','preparing','uncertain','sending') AND source_id IN (SELECT id FROM global_messages WHERE deleted=0)",
                    (old["channel_id"],),
                )
            # A reconfiguration never imports the other channel's old conversation.
            self.db.execute(
                "UPDATE global_deliveries SET state='cancelled' WHERE state IN ('queued','preparing','uncertain','sending') AND source_id IN (SELECT id FROM global_messages WHERE guild_id=? AND channel_id<>? AND deleted=0)",
                (gid, cid),
            )

    def active(self, guild, enabled):
        with self.db:
            self.db.execute(
                "UPDATE global_channels SET active=?,generation=generation+1,error='' WHERE guild_id=?",
                (int(enabled), str(guild)),
            )
            if not enabled:
                self.db.execute(
                    "UPDATE global_deliveries SET state='cancelled' WHERE state IN ('queued','preparing','uncertain','sending') AND source_id IN (SELECT id FROM global_messages WHERE deleted=0) AND (guild_id=? OR source_id IN (SELECT id FROM global_messages WHERE guild_id=?))",
                    (str(guild), str(guild)),
                )

    def remove_guild(self, guild):
        gid = str(guild)
        self.active(gid, False)
        with self.db:
            self.db.execute("DELETE FROM global_channels WHERE guild_id=?", (gid,))
            self.db.execute("DELETE FROM global_hooks WHERE guild_id=?", (gid,))
            self.db.execute("DELETE FROM global_prompts WHERE guild_id=?", (gid,))

    def consented(self, user):
        return bool(
            self.one(
                "SELECT 1 FROM global_consents WHERE user_id=? AND version=?",
                (str(user), CONSENT_VERSION),
            )
        )

    def invitation(self, user):
        return self.one(
            "SELECT * FROM global_invitations WHERE user_id=?", (str(user),)
        )

    def claim_invitation(self, user, cfg):
        # Reserve before awaiting Discord, including failures/restarts. Never DM
        # the same person again just because they send another message.
        with self.db:
            result = self.db.execute(
                "INSERT OR IGNORE INTO global_invitations(user_id,guild_id,channel_id,generation,status,attempted) VALUES(?,?,?,?,'sending',?)",
                (
                    str(user),
                    cfg["guild_id"],
                    cfg["channel_id"],
                    cfg["generation"],
                    self.clock(),
                ),
            )
        return result.rowcount == 1

    def consent(self, user, enabled=True):
        with self.db:
            if enabled:
                self.db.execute(
                    "INSERT INTO global_consents VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET version=excluded.version,accepted=excluded.accepted WHERE version<>excluded.version",
                    (str(user), CONSENT_VERSION, self.clock()),
                )
            else:
                self.db.execute(
                    "DELETE FROM global_consents WHERE user_id=?", (str(user),)
                )
                self.db.execute(
                    "UPDATE global_deliveries SET state='cancelled' WHERE state IN ('queued','preparing','uncertain','sending') AND source_id IN (SELECT id FROM global_messages WHERE user_id=? AND deleted=0)",
                    (str(user),),
                )

    def blocked(self, user, guild, source_guild=None):
        return bool(self.restriction(user, guild, source_guild)) or bool(
            self.one(
                """SELECT 1 FROM global_blocks WHERE
          (kind='user' AND target=? AND scope IN ('*',?)) OR
          (kind='guild' AND scope='*' AND target IN (?,?))""",
                (str(user), str(guild), str(guild), str(source_guild or guild)),
            )
        )

    def block(self, scope, kind, target, actor, reason, *, enabled=True):
        if kind not in ("user", "guild") or (kind == "guild" and str(scope) != "*"):
            raise ValueError('Choose a valid restriction.')
        if not str(target).isdecimal() or not 0 < int(target) < 2**64:
            raise ValueError('Enter a valid Discord ID.')
        if not 5 <= len(reason.strip()) <= 500:
            raise ValueError('Explain the reason in 5 to 500 characters.')
        with self.db:
            if enabled:
                self.db.execute(
                    "INSERT OR REPLACE INTO global_blocks VALUES(?,?,?,?,?,?)",
                    (
                        str(scope),
                        kind,
                        str(target),
                        str(actor),
                        reason.strip(),
                        self.clock(),
                    ),
                )
            else:
                self.db.execute(
                    "DELETE FROM global_blocks WHERE scope=? AND kind=? AND target=?",
                    (str(scope), kind, str(target)),
                )
                self.db.execute(
                    "DELETE FROM global_restrictions WHERE scope=? AND kind=? AND target=?",
                    (str(scope), kind, str(target)),
                )
            self.base.audit("global-moderation", actor, reason.strip())

    def limit(self, key, maximum, seconds, fingerprint=""):
        now = self.clock()
        row = self.one("SELECT * FROM global_limits WHERE key=?", (key,))
        if row and now - row["window"] < seconds:
            if row["count"] >= maximum or (
                fingerprint and row["fingerprint"] == fingerprint
            ):
                return False
            with self.db:
                self.db.execute(
                    "UPDATE global_limits SET count=count+1,fingerprint=? WHERE key=?",
                    (fingerprint, key),
                )
        else:
            with self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO global_limits VALUES(?,?,1,?)",
                    (key, now, fingerprint),
                )
        return True

    def message(self, ident):
        return self.one("SELECT * FROM global_messages WHERE id=?", (str(ident),))

    def resolve(self, guild, channel, ident):
        row = self.message(ident)
        if row and row["guild_id"] == str(guild) and row["channel_id"] == str(channel):
            return row
        receipt = self.one(
            "SELECT source_id FROM global_receipts WHERE message_id=? AND guild_id=? AND channel_id=?",
            (str(ident), str(guild), str(channel)),
        )
        if receipt:
            return self.message(receipt["source_id"])
        return None

    def accept(self, message, data, *, confirmed_first=False):
        ident, gid, cid, uid = map(
            str, (message.id, message.guild.id, message.channel.id, message.author.id)
        )
        cfg = self.source(cid)
        if (
            self.network_paused()
            or not cfg
            or cfg["guild_id"] != gid
            or self.blocked(uid, gid)
        ):
            raise ValueError('This chat is paused or participation is blocked.')
        old = self.message(ident)
        fingerprint = data["fingerprint"]
        if old and (old["user_id"] != uid or old["channel_id"] != cid):
            raise ValueError('The message source does not match the record.')
        if old and old["expires"] <= self.clock():
            raise ValueError("This message's synchronization window has ended.")
        if old and (old["deleted"] or old["fingerprint"] == fingerprint):
            return old, False
        if not old:
            destinations = [
                d
                for d in self.channels()
                if d["active"]
                and d["guild_id"] != gid
                and not self.blocked(uid, d["guild_id"], gid)
            ]
            if not self.consented(uid):
                raise ValueError(
                    'Confirm your participation before sharing messages.'
                )
            accepted = self.one(
                "SELECT accepted FROM global_consents WHERE user_id=?", (uid,)
            )["accepted"]
            if message.created_at.timestamp() < accepted and not confirmed_first:
                raise ValueError(
                    'Messages written before confirmation are not shared automatically.'
                )
            used_pages = (
                self.db.execute("PRAGMA page_count").fetchone()[0]
                - self.db.execute("PRAGMA freelist_count").fetchone()[0]
            )
            if (
                used_pages * self.db.execute("PRAGMA page_size").fetchone()[0]
                >= 128 * 1024 * 1024
                or self.one(
                    "SELECT COUNT(*) AS n FROM global_deliveries WHERE state IN ('queued','preparing','uncertain','sending')"
                )["n"]
                + len(destinations)
                > 50000
            ):
                raise ValueError(
                    'The chat is busy. Wait a moment before sending again.'
                )
            own_pending = self.one(
                "SELECT COUNT(*) AS n FROM global_deliveries d JOIN global_messages m ON m.id=d.source_id WHERE m.guild_id=? AND d.state IN ('queued','preparing','uncertain','sending')",
                (gid,),
            )["n"]
            if own_pending + len(destinations) > max(1000, len(destinations) * 20):
                raise ValueError(
                    'This server already has many pending deliveries. Wait for them to finish before sharing more messages.'
                )
        with self.db:
            if old:
                self.db.execute(
                    "UPDATE global_messages SET payload=?,fingerprint=?,revision=revision+1,updated=?,checked=?,error='' WHERE id=?",
                    (
                        json.dumps(data, ensure_ascii=False),
                        fingerprint,
                        self.clock(),
                        self.clock(),
                        ident,
                    ),
                )
                self.db.execute(
                    "UPDATE global_deliveries SET state='preparing',attempts=0,next_try=0,error='' WHERE source_id=? AND suppressed=0 AND state<>'cancelled'",
                    (ident,),
                )
            else:
                self.db.execute(
                    "INSERT INTO global_messages(id,guild_id,channel_id,user_id,payload,fingerprint,created,updated,checked,expires) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        ident,
                        gid,
                        cid,
                        uid,
                        json.dumps(data, ensure_ascii=False),
                        fingerprint,
                        self.clock(),
                        self.clock(),
                        self.clock(),
                        self.clock() + RETENTION,
                    ),
                )
                for dest in destinations:
                    if dest["active"]:
                        self.db.execute(
                            "INSERT OR IGNORE INTO global_deliveries(source_id,channel_id,guild_id,hook_id,state) VALUES(?,?,?,?,'preparing')",
                            (
                                ident,
                                dest["channel_id"],
                                dest["guild_id"],
                                dest["hook_id"],
                            ),
                        )
        return self.message(ident), True

    def prepared(self, ident, data, revision):
        with self.db:
            row = self.message(ident)
            if not row or row["deleted"] or row["revision"] != revision:
                return False
            self.db.execute(
                "UPDATE global_messages SET payload=?,error='' WHERE id=?",
                (json.dumps(data, ensure_ascii=False), str(ident)),
            )
            self.db.execute(
                "UPDATE global_deliveries SET state=CASE WHEN uncertain>=0 THEN 'uncertain' ELSE 'queued' END WHERE source_id=? AND state='preparing'",
                (str(ident),),
            )
        return True

    def failed(self, ident, reason):
        with self.db:
            self.db.execute(
                "UPDATE global_messages SET error=? WHERE id=?", (reason, str(ident))
            )
            self.db.execute(
                "UPDATE global_deliveries SET state='failed',error=? WHERE source_id=? AND state='preparing'",
                (reason, str(ident)),
            )

    def erase(self, ident):
        with self.db:
            self.db.execute(
                "UPDATE global_messages SET deleted=1,payload='{}',revision=revision+1,updated=? WHERE id=? AND deleted=0",
                (self.clock(), str(ident)),
            )
            self.db.execute(
                "UPDATE global_deliveries SET state=CASE WHEN uncertain>=0 THEN 'uncertain' ELSE 'queued' END,next_try=0,attempts=0 WHERE source_id=? AND (receipts<>'[]' OR uncertain>=0)",
                (str(ident),),
            )
            self.db.execute(
                "UPDATE global_deliveries SET state='cancelled' WHERE source_id=? AND receipts='[]' AND uncertain<0",
                (str(ident),),
            )

    def suppress(self, guild, channel, ident):
        row = self.resolve(guild, channel, ident)
        if not row:
            return
        with self.db:
            for delivery in self.rows(
                "SELECT * FROM global_deliveries WHERE source_id=? AND channel_id=?",
                (row["id"], str(channel)),
            ):
                self.db.execute(
                    "UPDATE global_deliveries SET suppressed=1,state='cancelled' WHERE source_id=? AND channel_id=?",
                    (row["id"], str(channel)),
                )

    def jobs(self, limit=10):
        cursor = self.base.get("global-queue-cursor") or ""
        rows = self.rows(
            """WITH candidates AS (
          SELECT d.*,ROW_NUMBER() OVER(PARTITION BY d.channel_id ORDER BY CASE WHEN m.deleted=1 OR d.suppressed=1 THEN 0 ELSE 1 END,d.rowid) AS slot
          FROM global_deliveries d JOIN global_messages m ON m.id=d.source_id
          WHERE d.state IN ('queued','uncertain') AND d.next_try<=? AND m.expires>?
          AND ((m.deleted=1 OR d.suppressed=1) OR NOT EXISTS(
            SELECT 1 FROM global_deliveries p JOIN global_messages q ON q.id=p.source_id
            WHERE p.channel_id=d.channel_id AND p.rowid<d.rowid AND p.state IN ('queued','preparing','uncertain','sending') AND q.deleted=0 AND p.suppressed=0)))
          SELECT * FROM candidates WHERE slot=1 ORDER BY CASE WHEN channel_id>? THEN 0 ELSE 1 END,channel_id LIMIT ?""",
            (self.clock(), self.clock(), cursor, limit),
        )
        if rows:
            self.base.set("global-queue-cursor", rows[-1]["channel_id"])
        return rows

    def delivery(self, source, channel):
        return self.one(
            "SELECT * FROM global_deliveries WHERE source_id=? AND channel_id=?",
            (str(source), str(channel)),
        )

    def save_receipt(self, job, part, ident):
        with self.db:
            row = self.delivery(job["source_id"], job["channel_id"])
            receipts = json.loads(row["receipts"])
            while len(receipts) <= part:
                receipts.append(None)
            receipts[part] = str(ident)
            self.db.execute(
                "UPDATE global_deliveries SET receipts=?,uncertain=-1,state=CASE WHEN suppressed=1 THEN 'queued' WHEN state='cancelled' THEN state ELSE 'queued' END WHERE source_id=? AND channel_id=?",
                (json.dumps(receipts), job["source_id"], job["channel_id"]),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO global_receipts VALUES(?,?,?,?)",
                (str(ident), job["source_id"], job["guild_id"], job["channel_id"]),
            )

    def finish(self, job, revision, receipts, *, state="sent"):
        with self.db:
            row = self.message(job["source_id"])
            fresh = self.delivery(job["source_id"], job["channel_id"])
            state = state if row["revision"] == revision else "queued"
            if not row["deleted"]:
                if fresh["suppressed"]:
                    # A moderator may act while a POST is already in flight.
                    # Keep the returned receipt available for cleanup.
                    state = (
                        "deleted"
                        if state == "deleted"
                        else "queued"
                        if any(receipts)
                        else "cancelled"
                    )
                elif fresh["state"] == "cancelled":
                    state = "cancelled"
            self.db.execute(
                "UPDATE global_deliveries SET state=?,revision=?,receipts=?,attempts=0,next_try=0,uncertain=-1,error='',attempt_payload='{}' WHERE source_id=? AND channel_id=?",
                (
                    state,
                    revision,
                    json.dumps(receipts),
                    job["source_id"],
                    job["channel_id"],
                ),
            )

    def retry(self, job, reason, *, uncertain=-1, terminal=False):
        with self.db:
            current = self.delivery(job["source_id"], job["channel_id"])
            if not current or current["state"] == "cancelled":
                return
            self.db.execute(
                """UPDATE global_deliveries SET state=?,error=?,attempts=attempts+1,
              attempted=CASE WHEN uncertain<0 THEN ? ELSE attempted END,next_try=?,uncertain=? WHERE source_id=? AND channel_id=?""",
                (
                    "failed"
                    if terminal
                    else "uncertain"
                    if uncertain >= 0
                    else "queued",
                    reason,
                    self.clock(),
                    self.clock() + min(300, 5 * 2 ** min(job["attempts"], 6)),
                    uncertain,
                    job["source_id"],
                    job["channel_id"],
                ),
            )

    def report(self, source, user, guild, reason):
        if not 10 <= len(reason.strip()) <= 500:
            raise ValueError('Describe what happened in 10 to 500 characters.')
        if not self.limit("report:" + str(user), 5, 600):
            raise ValueError('Please wait before submitting another report.')
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO global_reports(source_id,reporter,guild_id,reason,created) VALUES(?,?,?,?,?)",
                (str(source), str(user), str(guild), reason.strip(), self.clock()),
            )

    def cleanup(self):
        expired = self.rows(
            'SELECT id FROM global_messages WHERE expires<? ORDER BY expires LIMIT 64', (self.clock(),)
        )
        with self.db:
            self.db.execute('DELETE FROM global_attempts WHERE updated<?', (self.clock()-3600,))
            for row in expired:
                self.db.execute(
                    "DELETE FROM global_deliveries WHERE source_id=?", (row["id"],)
                )
                self.db.execute(
                    "DELETE FROM global_receipts WHERE source_id=?", (row["id"],)
                )
                self.db.execute('DELETE FROM global_messages WHERE id=?',(row['id'],))
            self.db.execute(
                """UPDATE global_deliveries SET state='failed',error='The queue expired after one hour; the original was preserved.'
              WHERE state IN ('queued','preparing','uncertain','sending') AND source_id IN
              (SELECT id FROM global_messages WHERE deleted=0 AND updated<?)""",
                (self.clock() - CONTENT_TTL,),
            )
            self.db.execute(
                "UPDATE global_messages SET payload='{}' WHERE updated<? AND payload<>'{}'",
                (self.clock() - CONTENT_TTL,),
            )
            self.db.execute(
                "DELETE FROM global_limits WHERE window<?", (self.clock() - 86400,)
            )
            self.db.execute(
                "DELETE FROM global_reports WHERE created<?",
                (self.clock() - RETENTION,),
            )
            self.db.execute(
                "DELETE FROM global_report_actions WHERE report_id NOT IN (SELECT id FROM global_reports)"
            )
            self.db.execute(
                "DELETE FROM global_restrictions WHERE until<=?", (self.clock(),)
            )
            self.db.execute(
                "DELETE FROM global_traffic WHERE created<?", (self.clock() - 3600,)
            )
            self.db.execute(
                "DELETE FROM global_prompts WHERE expires<?", (self.clock(),)
            )
            self.db.execute(
                "DELETE FROM global_hooks WHERE hook_id NOT IN (SELECT hook_id FROM global_channels UNION SELECT hook_id FROM global_deliveries)"
            )


def fingerprint(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
