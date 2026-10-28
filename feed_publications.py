"""Resumable publishing of confirmed bot feed images to announcement followers."""

import asyncio

import aiohttp
import discord

from banner_votes import BANNER_FILE


class FeedPublications:
    def __init__(self, bot):
        self.bot, self.db = bot, bot.store.connection
        self.lock = asyncio.Lock()
        self.db.execute('''CREATE TABLE IF NOT EXISTS feed_publications(
            kind TEXT NOT NULL, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            next_attempt REAL NOT NULL DEFAULT 0, expires_at REAL NOT NULL,
            issue TEXT NOT NULL DEFAULT '', PRIMARY KEY(kind,channel_id,message_id))''')
        self.db.commit()

    def deliveries(self):
        now = self.bot.store.clock()
        images = self.db.execute('''SELECT 'banner' AS kind,r.guild_id,r.channel_id,r.message_id,r.expires_at
            FROM banner_image_receipts r JOIN banner_targets t
            ON t.guild_id=r.guild_id AND t.channel_id=r.channel_id
            WHERE r.state IN ('sent','legacy') AND r.message_id IS NOT NULL AND r.expires_at>?''', (now,)).fetchall()
        batches = []
        for feed in (self.bot.banners, self.bot.daily):
            batches.extend(dict(row, kind=feed.kind) for row in feed.query('''SELECT j.guild_id,j.channel_id,j.message_id,
                e.created_at+? AS expires_at FROM banner_jobs j JOIN banner_targets t
                ON t.guild_id=j.guild_id AND t.channel_id=j.channel_id JOIN banner_events e ON e.id=j.event_id
                WHERE j.state='sent' AND j.message_id IS NOT NULL AND e.created_at>?'''
                + (" AND j.layout='batch'" if feed.kind == 'banner' else ''),
                (feed.max_age, now - feed.max_age)).fetchall())
        return [*images, *(row for row in batches if row['kind'] != 'daily'
                or self.bot.daily.current_daily.publication_current(row['channel_id'], row['message_id']))]

    def receipt(self, row):
        return self.db.execute('''SELECT * FROM feed_publications
            WHERE kind=? AND channel_id=? AND message_id=?''',
            (row['kind'], row['channel_id'], row['message_id'])).fetchone()

    def prepare(self):
        with self.db:
            self.db.execute('DELETE FROM feed_publications WHERE expires_at<=?', (self.bot.store.clock(),))
            for kind in ('banner', 'daily'):
                self.db.execute(f'''DELETE FROM feed_publications WHERE kind=? AND NOT EXISTS(
                    SELECT 1 FROM {kind}_targets t WHERE t.guild_id=feed_publications.guild_id
                    AND t.channel_id=feed_publications.channel_id)''', (kind,))
            self.db.execute('''UPDATE feed_publications SET state='ignored' WHERE kind='daily'
                AND state IN ('pending','sending') AND NOT EXISTS(SELECT 1 FROM daily_jobs j
                    JOIN daily_current c ON c.event_id=j.event_id
                    JOIN daily_source_head h ON h.singleton=c.singleton AND h.source_message=c.source_message
                    WHERE j.channel_id=feed_publications.channel_id
                    AND j.message_id=feed_publications.message_id AND j.state='sent')''')
            for row in self.deliveries():
                channel = self.bot.get_channel(int(row['channel_id']))
                if not isinstance(channel, discord.TextChannel) or channel.type != discord.ChannelType.news:
                    continue
                self.db.execute('''INSERT INTO feed_publications(kind,guild_id,channel_id,message_id,expires_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(kind,channel_id,message_id)
                    DO UPDATE SET expires_at=MAX(expires_at,excluded.expires_at)''',
                    tuple(row[key] for key in ('kind', 'guild_id', 'channel_id', 'message_id', 'expires_at')))

    def save(self, row, state, *, delay=0, issue=''):
        with self.db:
            self.db.execute('''UPDATE feed_publications SET state=?,next_attempt=?,issue=?
                WHERE kind=? AND channel_id=? AND message_id=?''',
                (state, self.bot.store.clock() + delay, issue, row['kind'], row['channel_id'], row['message_id']))

    def release_pending(self):
        if self.db.execute('''SELECT 1 FROM feed_publications p WHERE p.state IN ('pending','sending')
                AND p.expires_at>? AND (
                    (p.kind='banner' AND EXISTS(SELECT 1 FROM banner_targets t
                        WHERE t.guild_id=p.guild_id AND t.channel_id=p.channel_id)) OR
                    (p.kind='daily' AND EXISTS(SELECT 1 FROM daily_targets t
                        WHERE t.guild_id=p.guild_id AND t.channel_id=p.channel_id))) LIMIT 1''',
                (self.bot.store.clock(),)).fetchone():
            return 'Feed announcement publishing is awaiting Discord or channel permissions.'
        for row in self.deliveries():
            channel = self.bot.get_channel(int(row['channel_id']))
            receipt = self.receipt(row)
            if receipt and receipt['state'] in {'published', 'ignored', 'gone'}:
                continue
            if channel is None or (isinstance(channel, discord.TextChannel) and channel.type == discord.ChannelType.news):
                return 'Delivered feed images are awaiting announcement publishing checks.'
        return None

    def description(self, kind, guild_id):
        feed = self.bot.banners if kind == 'banner' else self.bot.daily
        target = feed.target(guild_id)
        channel = self.bot.get_channel(int(target['channel_id'])) if target else None
        if not isinstance(channel, discord.TextChannel) or channel.type != discord.ChannelType.news:
            return None
        row = self.db.execute('''SELECT issue FROM feed_publications WHERE kind=? AND channel_id=?
            AND state IN ('pending','sending') AND expires_at>? ORDER BY next_attempt DESC LIMIT 1''',
            (kind, target['channel_id'], self.bot.store.clock())).fetchone()
        if row:
            if row['issue'] == 'permissions':
                return 'Publishing is waiting. Grant View Channel, Send Messages and Read Message History.'
            if row['issue'] == 'source':
                return 'Publishing is waiting for the latest daily source check.'
            return 'Automatic publishing is waiting for Discord confirmation.'
        return 'Images are published automatically to this announcement channel\'s followers.'

    def destination(self, row):
        feed = self.bot.banners if row['kind'] == 'banner' else self.bot.daily
        target = feed.target(row['guild_id'])
        if not target or target['channel_id'] != row['channel_id']:
            return None
        if row['kind'] == 'daily' and not feed.current_daily.publication_current(row['channel_id'], row['message_id']):
            self.save(row, 'ignored')
            return None
        if row['kind'] == 'daily' and feed.status != 'ready':
            self.save(row, 'pending', delay=30, issue='source')
            return None
        channel = self.bot.get_channel(int(row['channel_id']))
        if channel is None:
            self.save(row, 'pending', delay=300, issue='permissions')
            return None
        if not isinstance(channel, discord.TextChannel) or channel.type != discord.ChannelType.news:
            self.save(row, 'ignored')
            return None
        permissions = channel.permissions_for(channel.guild.me) if channel.guild.me else discord.Permissions.none()
        if not all(getattr(permissions, key) for key in ('view_channel', 'send_messages', 'read_message_history')):
            self.save(row, 'pending', delay=300, issue='permissions')
            return None
        return channel

    async def publish(self, row):
        # Publishing has its own task/lock; never hold the image-delivery lock
        # while Discord delays a crosspost. Recheck the target after fetching.
        channel = self.destination(row)
        if channel is None:
            return
        try:
            async with asyncio.timeout(10):
                message = await channel.fetch_message(int(row['message_id']))
                if (message.author.id != self.bot.user.id or message.webhook_id
                        or message.flags.is_crossposted or not message.attachments
                        or not all(BANNER_FILE.fullmatch(file.filename) for file in message.attachments)):
                    self.save(row, 'ignored')
                    return
                if not message.flags.crossposted:
                    if self.destination(row) is None:
                        return
                    # Save before POST. A lost acknowledgment or restart is
                    # reconciled by fetching the crossposted flag first.
                    self.save(row, 'sending', delay=30)
                    await message.publish()
                self.save(row, 'published')
        except discord.NotFound:
            self.save(row, 'gone')
        except discord.Forbidden:
            self.save(row, 'pending', delay=300, issue='permissions')
        except discord.HTTPException as error:
            if error.code == 40033:  # Another actor already published it.
                self.save(row, 'published')
            else:
                self.save(row, 'pending', delay=60, issue='discord')
        except (aiohttp.ClientError, TimeoutError, OSError):
            self.save(row, 'pending', delay=30, issue='discord')

    async def cycle(self):
        if self.lock.locked() or self.bot.health.storage_level == 'critical':
            return
        async with self.lock:
            self.prepare()
            rows = self.db.execute('''SELECT * FROM feed_publications
                WHERE state IN ('pending','sending') AND next_attempt<=? ORDER BY next_attempt LIMIT 4''',
                (self.bot.store.clock(),)).fetchall()
            for row in rows:
                await self.publish(row)
