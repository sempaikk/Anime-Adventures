"""Explicitly authorized incident notices, scoped to existing feed destinations."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging

import aiohttp
import discord
from discord.http import handle_message_parameters

from feed_history import recent_attempts

log = logging.getLogger('adventures.notices')
CAMPAIGN = 'feed-recovery-2026-10-28'
# This incident must not become a welcome message on future installations.
EXPIRES_AT = datetime(2026, 11, 4, tzinfo=timezone.utc).timestamp()
FORWARDED_CAMPAIGN = 'banner-forwarded-recovery-2026-10-30'
FORWARDED_STARTS_AT = datetime(2026, 10, 30, tzinfo=timezone.utc).timestamp()
FORWARDED_EXPIRES_AT = datetime(2026, 11, 6, tzinfo=timezone.utc).timestamp()
RECEPTION_CAMPAIGN = 'banner-reception-recovery-2026-10-31'
RECEPTION_STARTS_AT = datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp()
RECEPTION_EXPIRES_AT = datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp()
RECEPTION_NOTICE = (
    'Pedimos desculpas pela interrupção e pelos atrasos no envio dos banners. '
    'Corrigimos uma falha que impedia o recebimento de novas imagens, e este canal já voltou a receber os banners recentes.\n\n'
    'Os próximos banners continuarão sendo enviados automaticamente. '
    'As imagens antigas do período da interrupção não serão republicadas em sequência, '
    'para evitar confusão com os banners atuais.\n\n'
    'Obrigado pela paciência e por continuarem usando o Adventures!')
FORWARDED_NOTICE = (
    'Pedimos desculpas pelos atrasos e pela ausência de alguns banners. '
    'Parte das imagens passou a ser publicada por encaminhamento na origem, e o Adventures ainda não reconhecia esse formato. '
    'Por isso, alguns banners não chegaram e outros estão chegando com atraso.\n\n'
    'O problema foi corrigido: agora o bot reconhece tanto imagens normais quanto encaminhadas, e os envios estão sendo retomados. '
    'A retomada usa as imagens recentes disponíveis; o histórico completo do período sem envios não será republicado, '
    'para evitar confusão com banners antigos.\n\n'
    'Obrigado pela paciência e por continuarem usando o Adventures!')


def notice_text(kinds):
    subject = ('banners e desafios diários' if len(kinds) == 2 else
               'banners' if kinds[0]['kind'] == 'banner' else 'desafios diários')
    return (f'Pedimos desculpas pela interrupção no envio de {subject}. '
            'A falha foi corrigida, e os envios automáticos estão sendo retomados. '
            'Obrigado pela paciência e por continuarem usando o Adventures!')


class FeedNotices:
    def __init__(self, bot, *, campaign=CAMPAIGN, expires_at=EXPIRES_AT,
                 kinds=('banner', 'daily'), text=notice_text, starts_at=0,
                 label='Feed recovery notice'):
        self.bot = bot
        self.db = bot.store.connection
        self.feeds = {kind: {'banner': bot.banners, 'daily': bot.daily}[kind] for kind in kinds}
        self.campaign, self.expires_at, self.starts_at = campaign, expires_at, starts_at
        self.text, self.label = text, label
        self.lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(2)
        self.last_summary = None
        self.db.execute('''CREATE TABLE IF NOT EXISTS bot_feed_notices(
            campaign TEXT NOT NULL, channel_id TEXT NOT NULL, guild_id TEXT NOT NULL,
            kinds TEXT NOT NULL, body TEXT NOT NULL, nonce TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempted_at REAL NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0, message_id TEXT,
            PRIMARY KEY(campaign,channel_id))''')
        self.db.commit()

    def snapshot(self):
        key = 'feed-notice-snapshot:' + self.campaign
        if self.bot.store.get(key):
            return
        targets = {}
        for kind, feed in self.feeds.items():
            for row in feed.query('SELECT guild_id,channel_id FROM banner_targets'):
                if self.bot.get_guild(int(row['guild_id'])) is None:
                    continue
                channel = targets.setdefault(row['channel_id'], {'guild': row['guild_id'], 'kinds': []})
                channel['kinds'].append({'kind': kind, 'generation': feed.generation(row['guild_id'])})
        with self.db:
            for channel_id, target in targets.items():
                nonce = str(int(hashlib.sha256((self.campaign + ':' + channel_id).encode()).hexdigest()[:15], 16))
                self.db.execute('''INSERT OR IGNORE INTO bot_feed_notices
                    (campaign,channel_id,guild_id,kinds,body,nonce) VALUES(?,?,?,?,?,?)''',
                    (self.campaign, channel_id, target['guild'], json.dumps(target['kinds']),
                     self.text(target['kinds']), nonce))
            self.db.execute('INSERT OR REPLACE INTO bot_meta VALUES(?,?)', (key, str(self.bot.store.clock())))

    def update(self, row, **values):
        with self.db:
            self.db.execute('UPDATE bot_feed_notices SET ' + ','.join(name + '=?' for name in values)
                            + ' WHERE campaign=? AND channel_id=?',
                            (*values.values(), self.campaign, row['channel_id']))

    def current(self, row, kinds):
        for item in kinds:
            feed = self.feeds[item['kind']]
            target = feed.target(row['guild_id'])
            if (not target or target['channel_id'] != row['channel_id']
                    or feed.generation(row['guild_id']) != item['generation']):
                return False
        return True

    def recovered(self, kinds):
        for item in kinds:
            feed = self.feeds[item['kind']]
            if not feed.ready():
                return False
            state = feed.diagnostics.snapshot()
            if state['source_message'] and (state['source_message'] != state['received_source']
                    or state['observed'] > state['received_version']):
                return False
        return True

    def destination_recovered(self, row, kinds):
        return True

    async def deliver(self, row):
        async with self.slots:
            kinds = json.loads(row['kinds'])
            if not self.current(row, kinds) or self.bot.get_guild(int(row['guild_id'])) is None:
                self.update(row, state='cancelled')
                return
            self.update(row, next_attempt=self.bot.store.clock() + 300)
            channel = self.bot.get_channel(int(row['channel_id']))
            if channel is None:
                try:
                    channel = await asyncio.wait_for(self.bot.fetch_channel(int(row['channel_id'])), 25)
                except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                    return
            if (not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != row['guild_id']
                    or channel.guild.unavailable or channel.guild.me is None):
                return
            permissions = channel.permissions_for(channel.guild.me)
            if not (permissions.view_channel and permissions.read_message_history):
                return
            if row['state'] in {'sending', 'uncertain'}:
                # Reconcile the original attempt; never blindly repost after a crash/timeout.
                async def reconcile():
                    async for message in recent_attempts(channel, row['attempted_at']):
                        if (message.author.id == self.bot.user.id and not message.webhook_id
                                and (str(getattr(message, 'nonce', None)) == row['nonce']
                                     or (message.content == row['body'] and
                                         message.created_at.timestamp() >= row['attempted_at'] - 5))):
                            self.update(row, state='sent', message_id=str(message.id))
                            return
                try:
                    await asyncio.wait_for(reconcile(), 25)
                except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                    pass
                return
            if not (permissions.send_messages and permissions.attach_files
                    and (not any(item['kind'] == 'banner' for item in kinds) or permissions.add_reactions)):
                self.update(row, state='blocked')
                return
            if not self.recovered(kinds) or not self.destination_recovered(row, kinds):
                self.update(row, next_attempt=self.bot.store.clock() + 30)
                return
            # Fetching the channel may have awaited; recheck destination and source now.
            if not self.current(row, kinds) or self.bot.store.clock() >= self.expires_at:
                self.update(row, state='cancelled')
                return
            self.update(row, state='sending', attempted_at=self.bot.store.clock())
            state, message_id = 'uncertain', None
            try:
                with handle_message_parameters(content=row['body'], nonce=row['nonce'],
                        allowed_mentions=discord.AllowedMentions.none()) as params:
                    params.payload['enforce_nonce'] = True
                    message = await asyncio.wait_for(self.bot.http.send_message(channel.id, params=params), 25)
                state, message_id = 'sent', str(message['id'])
            except (discord.Forbidden, discord.NotFound):
                state = 'blocked'
            except (discord.HTTPException, aiohttp.ClientError, TimeoutError, OSError):
                pass
            finally:
                self.update(row, state=state, message_id=message_id)

    def description(self):
        rows = self.db.execute('''SELECT state,count(*) FROM bot_feed_notices
            WHERE campaign=? GROUP BY state''', (self.campaign,)).fetchall()
        counts = dict(rows)
        if not rows:
            return 'No destinations queued for this incident.'
        return (f"{counts.get('sent', 0)}/{sum(counts.values())} channels confirmed; "
                f"{counts.get('pending', 0) + counts.get('blocked', 0)} waiting; "
                f"{counts.get('sending', 0) + counts.get('uncertain', 0)} awaiting confirmation; "
                f"{counts.get('cancelled', 0) + counts.get('expired', 0)} closed without a send.")

    async def cycle(self):
        if self.lock.locked() or not self.bot.is_ready() or not self.bot.build.get('verified'):
            return
        async with self.lock:
            if self.bot.store.clock() < self.starts_at:
                return
            if self.bot.store.clock() >= self.expires_at:
                with self.db:
                    self.db.execute("UPDATE bot_feed_notices SET state='expired' WHERE campaign=? AND state IN ('pending','blocked')", (self.campaign,))
                return
            self.snapshot()
            rows = self.db.execute('''SELECT * FROM bot_feed_notices WHERE campaign=?
                AND state IN ('pending','blocked','sending','uncertain') AND next_attempt<=?
                ORDER BY next_attempt,rowid LIMIT 4''', (self.campaign, self.bot.store.clock())).fetchall()
            results = await asyncio.gather(*(self.deliver(row) for row in rows), return_exceptions=True)
            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, Exception):
                    log.warning('%s deferred: %s', self.label, type(result).__name__)
            summary = self.description()
            if summary != self.last_summary:
                self.last_summary = summary
                log.info('%s: %s', self.label, summary)


class ForwardedBannerNotices(FeedNotices):
    """One banner-only explanation for the separately authorized forwarding incident."""

    def __init__(self, bot):
        super().__init__(bot, campaign=FORWARDED_CAMPAIGN, expires_at=FORWARDED_EXPIRES_AT,
                         starts_at=FORWARDED_STARTS_AT, kinds=('banner',),
                         text=lambda kinds: FORWARDED_NOTICE, label='Banner forwarding notice')


class ReceptionRecoveryNotices(FeedNotices):
    """Current incident: announce recovery only after this channel receives it."""

    def __init__(self, bot):
        super().__init__(bot, campaign=RECEPTION_CAMPAIGN, expires_at=RECEPTION_EXPIRES_AT,
                         starts_at=RECEPTION_STARTS_AT, kinds=('banner',),
                         text=lambda kinds: RECEPTION_NOTICE, label='Banner reception notice')

    def destination_recovered(self, row, kinds):
        feed = self.feeds['banner']
        source = feed.diagnostics.snapshot()['source_message']
        event = feed.query('SELECT id FROM banner_events WHERE source_message=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
                           (source,)).fetchone()
        return bool(event and feed.query('''SELECT 1 FROM banner_jobs WHERE event_id=?
            AND guild_id=? AND channel_id=? AND state='sent' AND message_id IS NOT NULL''',
            (event['id'], row['guild_id'], row['channel_id'])).fetchone())
