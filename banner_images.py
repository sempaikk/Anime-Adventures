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
        ''')

    def key(self, row):
        return row['source_message'], row['digest'], row['channel_id']

    def state(self, row, state, message_id=None):
        with self.db:
            self.db.execute('''UPDATE banner_image_receipts SET state=?,attempted_at=?,message_id=?
                WHERE source_message=? AND digest=? AND channel_id=?''',
                (state, self.relay.clock(), str(message_id) if message_id else None, *self.key(row)))

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
                name_hash = hashlib.sha256((event['source_message'] + ':' + digest).encode()).hexdigest()[:16]
                filename = f"banner-{name_hash}.{asset['extension']}"
                self.db.execute('''INSERT OR IGNORE INTO banner_image_receipts
                    (source_message,digest,guild_id,channel_id,filename,state,message_id,expires_at,reactions,attempted_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (event['source_message'], digest, job['guild_id'], job['channel_id'], filename,
                     ('legacy' if old['message_id'] and old['state']=='sent' else 'legacy_uncertain') if old else 'pending', old['message_id'] if old else None,
                     event['created_at'] + self.relay.max_age, 7 if old else 0, old['attempted_at'] if old else 0))
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
        for part, asset in zip(parts, assets):
            if part['state'] in {'sent', 'legacy', 'legacy_uncertain', 'unavailable', 'oversize'}:
                continue
            if part['state'] in {'sending', 'uncertain'}:
                if self.relay.clock() - part['attempted_at'] < 30:
                    continue
                if history is None:
                    history = [message async for message in channel.history(limit=50)]
                message = next((message for message in history
                    if message.author.id == self.bot.user.id and not getattr(message, 'webhook_id', None)
                    and (str(getattr(message, 'nonce', None)) == self.nonce(part)
                         or [a.filename for a in message.attachments] == [part['filename']])), None)
                self.state(part, 'sent' if message else 'uncertain', message.id if message else None)
                continue
            if len(asset['data']) > min(MAX_IMAGE, channel.guild.filesize_limit):
                self.state(part, 'oversize')
                continue
            file = discord.File(io.BytesIO(asset['data']), filename=part['filename'])
            self.state(part, 'sending')
            try:
                with handle_message_parameters(files=[file], allowed_mentions=discord.AllowedMentions.none()) as params:
                    for entry in params.multipart:
                        if entry['name'] == 'payload_json':
                            data = json.loads(entry['value'])
                            data.update(nonce=self.nonce(part), enforce_nonce=True)
                            entry['value'] = json.dumps(data)
                    response = await self.bot.http.send_message(channel.id, params=params)
                self.state(part, 'sent', response['id'])
            except (discord.Forbidden, discord.NotFound):
                self.state(part, 'unavailable')
            except Exception:
                self.state(part, 'uncertain')
            finally:
                file.close()
        current = [self.db.execute('''SELECT * FROM banner_image_receipts
            WHERE source_message=? AND digest=? AND channel_id=?''', self.key(part)).fetchone() for part in parts]
        current = [part for part in current if part is not None]
        if not current:
            return  # Retention expired while Discord was processing the upload.
        states = {part['state'] for part in current}
        state = next((value for value, selected in (
            ('uncertain', {'sending', 'uncertain', 'legacy_uncertain'}), ('unavailable', {'unavailable'}),
            ('pending', {'pending'}), ('oversize', {'oversize'})) if states & selected), 'sent')
        ident = next((part['message_id'] for part in current if part['message_id']), None)
        self.relay.state(job, state, ident)
        if state == 'sent':
            with self.db:
                self.db.execute('UPDATE banner_jobs SET attempted_at=? WHERE event_id=? AND channel_id=?',
                                (max(part['attempted_at'] for part in current), job['event_id'], job['channel_id']))

    def prune(self):
        with self.db:
            self.db.execute('DELETE FROM banner_image_receipts WHERE expires_at<=?', (self.relay.clock(),))

    def resume(self, guild_id, channel_id):
        with self.db:
            self.db.execute('''UPDATE banner_image_receipts SET state='pending'
                WHERE guild_id=? AND channel_id=? AND state='unavailable' ''', (str(guild_id), str(channel_id)))
