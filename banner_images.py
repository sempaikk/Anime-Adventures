"""One durable receipt per source image, preserving legacy batch deliveries."""

import hashlib
import io
import json

import discord
from discord.http import handle_message_parameters


class BannerImages:
    def __init__(self, relay):
        self.relay, self.bot, self.db = relay, relay.bot, relay.db
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(banner_jobs)')}
        if 'layout' not in columns:
            self.db.execute("ALTER TABLE banner_jobs ADD COLUMN layout TEXT NOT NULL DEFAULT 'batch'")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS banner_image_receipts(
                source_message TEXT NOT NULL, digest TEXT NOT NULL,
                guild_id TEXT NOT NULL, channel_id TEXT NOT NULL, filename TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', attempted_at REAL NOT NULL DEFAULT 0,
                message_id TEXT, expires_at REAL NOT NULL,
                reactions INTEGER NOT NULL DEFAULT 0, reaction_after REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(source_message,digest,channel_id));
            CREATE INDEX IF NOT EXISTS banner_image_reactions_pending
                ON banner_image_receipts(reaction_after) WHERE state='sent' AND reactions<>7;
            CREATE TABLE IF NOT EXISTS banner_delivery_floor(
                channel_id TEXT PRIMARY KEY,source_message TEXT NOT NULL);
        ''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(banner_image_receipts)')}
        if 'first_attempt' not in columns:
            self.db.execute('ALTER TABLE banner_image_receipts ADD COLUMN first_attempt REAL NOT NULL DEFAULT 0')
        self.db.commit()

    def key(self, row):
        return row['source_message'], row['digest'], row['channel_id']

    def state(self, row, state, message_id=None):
        with self.db:
            self.db.execute('''UPDATE banner_image_receipts SET state=?,attempted_at=?,message_id=?
                WHERE source_message=? AND digest=? AND channel_id=?''',
                (state, self.relay.clock(), str(message_id) if message_id else None, *self.key(row)))
            if state == 'sending':
                self.db.execute('''UPDATE banner_image_receipts SET first_attempt=CASE WHEN first_attempt=0 THEN ? ELSE first_attempt END
                    WHERE source_message=? AND digest=? AND channel_id=?''', (self.relay.clock(), *self.key(row)))

    @staticmethod
    def nonce(row):
        value = ':'.join(('banner-image', row['source_message'], row['digest'], row['channel_id']))
        return str(int(hashlib.sha256(value.encode()).hexdigest()[:15], 16))

    def prepare(self, job, assets):
        event = self.relay.query('SELECT * FROM banner_events WHERE id=?', (job['event_id'],)).fetchone()
        # A previously confirmed batch must not be republished after an upgrade/edit.
        legacy = self.db.execute('''SELECT e.images,j.message_id,j.state,j.attempted_at FROM banner_jobs j
            JOIN banner_events e ON e.id=j.event_id
            WHERE e.source_message=? AND j.channel_id=? AND j.state IN ('sent','sending','uncertain') AND j.layout='batch'
            ORDER BY (j.state='sent') DESC,j.attempted_at DESC''', (event['source_message'], job['channel_id'])).fetchall()
        result = []
        with self.db:
            self.db.execute("UPDATE banner_jobs SET layout='images' WHERE event_id=? AND channel_id=?",
                            (job['event_id'], job['channel_id']))
            for asset in assets:
                digest = asset['digest']
                old = next((row for row in legacy if digest in json.loads(row['images'])), None)
                floor = self.db.execute('SELECT source_message FROM banner_delivery_floor WHERE channel_id=?', (job['channel_id'],)).fetchone()
                obsolete = bool(floor and int(event['source_message']) <= int(floor[0]))
                name_hash = hashlib.sha256((event['source_message'] + ':' + digest).encode()).hexdigest()[:16]
                filename = f"banner-{name_hash}.{asset['extension']}"
                self.db.execute('''INSERT OR IGNORE INTO banner_image_receipts
                    (source_message,digest,guild_id,channel_id,filename,state,message_id,expires_at,reactions,attempted_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (event['source_message'], digest, job['guild_id'], job['channel_id'], filename,
                     ('legacy' if old['message_id'] and old['state']=='sent' else 'legacy_uncertain') if old else ('legacy' if obsolete else 'pending'), old['message_id'] if old else None,
                     event['created_at'] + self.relay.max_age, 7 if old or obsolete else 0, old['attempted_at'] if old else 0))
                if old and old['state'] == 'sent':
                    self.db.execute('''UPDATE banner_image_receipts SET state='legacy',message_id=?,attempted_at=?
                        WHERE source_message=? AND digest=? AND channel_id=? AND state='legacy_uncertain' ''',
                        (old['message_id'], old['attempted_at'], event['source_message'], digest, job['channel_id']))
                self.db.execute('''UPDATE banner_image_receipts SET expires_at=MAX(expires_at,?)
                    WHERE source_message=? AND digest=? AND channel_id=?''',
                    (event['created_at'] + self.relay.max_age, event['source_message'], digest, job['channel_id']))
                result.append(self.db.execute('''SELECT * FROM banner_image_receipts
                    WHERE source_message=? AND digest=? AND channel_id=?''',
                    (event['source_message'], digest, job['channel_id'])).fetchone())
        return result

    async def deliver(self, job, channel, assets):
        from banner_relay import MAX_IMAGE

        parts = self.prepare(job, assets)
        history = None
        delay=0
        for part, asset in zip(parts, assets):
            if part['state'] in {'sent', 'legacy', 'legacy_uncertain', 'unavailable', 'oversize'}:
                continue
            if part['state'] in {'sending', 'uncertain'}:
                if self.relay.clock() - part['attempted_at'] < 30:
                    continue
                if history is None:
                    from feed_history import recent_attempts
                    history = [message async for message in recent_attempts(channel, part['first_attempt'] or part['attempted_at'])]
                message = next((message for message in history
                    if message.author.id == self.bot.user.id and not getattr(message, 'webhook_id', None)
                    and (str(getattr(message, 'nonce', None)) == self.nonce(part)
                         or [a.filename for a in message.attachments] == [part['filename']])), None)
                self.state(part, 'sent' if message else 'uncertain', message.id if message else None)
                continue
            if self.relay.paused() or not self.relay.current_job(job):
                return
            if len(asset['data']) > min(MAX_IMAGE, channel.guild.filesize_limit):
                self.state(part, 'oversize')
                continue
            file = discord.File(io.BytesIO(asset['data']), filename=part['filename'])
            self.state(part, 'sending')
            try:
                with handle_message_parameters(files=[file], allowed_mentions=discord.AllowedMentions.none()) as params:
                    from feed_tools import silence_payload
                    silence_payload(self.bot, job['guild_id'], params)
                    for entry in params.multipart:
                        if entry['name'] == 'payload_json':
                            data = json.loads(entry['value'])
                            data.update(nonce=self.nonce(part), enforce_nonce=True)
                            entry['value'] = json.dumps(data)
                    response = await self.bot.http.send_message(channel.id, params=params)
                self.state(part, 'sent', response['id'])
            except (discord.Forbidden, discord.NotFound):
                self.state(part, 'unavailable')
            except Exception as error:
                from delivery_errors import feed_failure,retry_delay
                self.state(part, feed_failure(error))
                delay=retry_delay(error)
                if delay:
                    break
            finally:
                file.close()
        if not self.relay.current_job(job):
            return
        current = [self.db.execute('''SELECT * FROM banner_image_receipts
            WHERE source_message=? AND digest=? AND channel_id=?''', self.key(part)).fetchone() for part in parts]
        current = [part for part in current if part is not None]
        if not current:
            return  # Retention expired while Discord was processing the upload.
        states = {part['state'] for part in current}
        state = next((value for value, selected in (
            ('uncertain', {'sending', 'uncertain', 'legacy_uncertain'}), ('unavailable', {'unavailable'}),
            ('rejected', {'rejected'}),
            ('pending', {'pending'}), ('oversize', {'oversize'})) if states & selected), 'sent')
        ident = next((part['message_id'] for part in current if part['message_id']), None)
        self.relay.state(job, state, ident)
        if delay:
            with self.db:
                self.db.execute('UPDATE banner_jobs SET next_try=? WHERE event_id=? AND channel_id=?',
                    (self.relay.clock()+delay,job['event_id'],job['channel_id']))
        if state == 'sent':
            with self.db:
                self.db.execute('UPDATE banner_jobs SET attempted_at=? WHERE event_id=? AND channel_id=?',
                                (max(part['attempted_at'] for part in current), job['event_id'], job['channel_id']))

    def prune(self):
        with self.db:
            # Byte cache expiry must not erase the identity of a confirmed send.
            old = self.db.execute('''WITH ranked AS (SELECT rowid rid,channel_id,source_message,
                ROW_NUMBER() OVER(PARTITION BY channel_id ORDER BY expires_at DESC,rowid DESC) n
                FROM banner_image_receipts) SELECT rid,channel_id,source_message FROM ranked WHERE n>48''').fetchall()
            for row in old:
                previous = self.db.execute('SELECT source_message FROM banner_delivery_floor WHERE channel_id=?', (row['channel_id'],)).fetchone()
                floor = max(int(row['source_message']), int(previous[0]) if previous else 0)
                self.db.execute('INSERT OR REPLACE INTO banner_delivery_floor VALUES(?,?)', (row['channel_id'], str(floor)))
                self.db.execute('DELETE FROM banner_image_receipts WHERE rowid=?', (row['rid'],))

    def resume(self, guild_id, channel_id):
        with self.db:
            self.db.execute('''UPDATE banner_image_receipts SET state='pending'
                WHERE guild_id=? AND channel_id=? AND state='unavailable' ''', (str(guild_id), str(channel_id)))
