"""Private operational triage; controlled fields instead of logs and credentials."""

import json
import discord

from bot_views import BoundModal, reply
from bot_ui import edit_response
from global_views import ScopedView


def server_overview(bot, guild):
    cfg = bot.globalchat.store.channel(guild)
    text = '**This server:**\nGlobal chat: ' + (('<#' + cfg['channel_id'] + '> · ' + ('active' if cfg['active'] else 'paused')) if cfg else 'not configured') + '.'
    for feed in (bot.banners, bot.daily):
        target = feed.target(guild)
        text += '\n' + feed.kind.title() + ': ' + (('<#' + target['channel_id'] + '>') if target else 'not configured') + ('. Maintenance paused.' if feed.paused() else '.')
    return text


def diagnostic_text(bot, guild):
    # Deliberate allowlist: no exceptions, webhook tokens, URLs, member IDs,
    # message bodies or configuration belonging to another server.
    data = {'version': bot.build.get('version', 'unknown'), 'verified': bool(bot.build.get('verified')),
            'server': str(guild), 'storage': bot.health.storage_level,
            'memory': getattr(bot.health, 'memory_level', 'unknown'), 'feeds': {}}
    for feed in (bot.banners, bot.daily):
        target = feed.target(guild)
        state = feed.diagnostics.snapshot(guild)
        issue = state['error']
        data['feeds'][feed.kind] = {'channel': target['channel_id'] if target else None,
            'reader': feed.status, 'paused': feed.paused(), 'last_check': state['polled'],
            'transport': 'authorized bot' if feed.native else 'isolated reader',
            'last_verified_bytes': state['received'], 'pending': state['pending'],
            'issue': issue if issue in {'delivery_deferred', 'delivery_failed', 'partial_reception',
                'unsupported_images', 'unsupported_source_urls', 'download_failed', 'receive_timeout', 'storage_paused'} else ('source_issue' if issue else '')}
    cfg = bot.globalchat.store.channel(guild)
    data['global_chat'] = {'channel': cfg['channel_id'] if cfg else None, 'active': bool(cfg and cfg['active']),
        'states': {r['state']: r['n'] for r in bot.globalchat.store.rows('SELECT state,count(*) n FROM global_deliveries WHERE guild_id=? GROUP BY state', (str(guild),))}}
    return '## Private diagnostics\nCopy this summary for support. Only this server\'s configuration and controlled status fields are included.\n```json\n' + json.dumps(data, indent=2) + '\n```'


class DestinationView(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=True)
        self.page = 0

    def rows(self):
        rows = []
        for feed in (self.bot.banners, self.bot.daily):
            for r in feed.query('''SELECT t.guild_id,t.channel_id,j.state,count(*) n FROM banner_targets t
                JOIN banner_jobs j ON j.guild_id=t.guild_id AND j.channel_id=t.channel_id
                WHERE j.state IN ('unavailable','oversize','rejected','pending','uncertain','sending')
                GROUP BY t.guild_id,t.channel_id,j.state ORDER BY t.guild_id'''):
                rows.append((feed.kind, r['guild_id'], r['channel_id'], r['state'], r['n']))
        for r in self.bot.globalchat.store.rows('''SELECT d.guild_id,d.channel_id,d.state,count(*) n FROM global_deliveries d
                JOIN global_channels c ON c.guild_id=d.guild_id AND c.channel_id=d.channel_id
                WHERE d.state IN ('failed','queued','preparing','uncertain','sending') GROUP BY d.guild_id,d.channel_id,d.state ORDER BY d.guild_id'''):
            rows.append(('global chat', r['guild_id'], r['channel_id'], r['state'], r['n']))
        return rows

    def description(self):
        rows = self.rows()
        self.page = max(0, min(self.page, max(0, (len(rows)-1)//5)))
        self.previous.disabled = self.page == 0
        self.next.disabled = (self.page+1)*5 >= len(rows)
        text = f'## Destination triage · page {self.page+1}\nPrivate to the bot owner. Covers every configured server.\n'
        for kind, guild, channel, state, n in rows[self.page*5:self.page*5+5]:
            guidance = ('A server administrator must restore View Channel, Send Messages, Attach Files and Read Message History.' if state == 'unavailable'
                else 'The file exceeds this server\'s upload limit.' if state == 'oversize'
                else 'Discord confirmation is being reconciled; do not resend manually.' if state in {'uncertain', 'sending'}
                else 'Check this destination\'s connection and the private source diagnostics.')
            text += f'\n**{kind.title()} · server {guild} · <#{channel}>**\n{state}: {n}. {guidance}\n'
        return text if rows else text + '\nNo blocked or pending destinations.'

    @discord.ui.button(label='Previous', row=0)
    async def previous(self, i, button):
        self.require(i)
        self.page -= 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Next', row=0)
    async def next(self, i, button):
        self.require(i)
        self.page += 1
        await edit_response(i, content=self.description(), view=self)

    @discord.ui.button(label='Refresh', row=0)
    async def refresh(self, i, button):
        self.require(i)
        await edit_response(i, content=self.description(), view=self)


class FeedMaintenance(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title='Temporary feed maintenance')
        self.bind(bot, i)
        bot.require_owner(i)
        self.previous = {f.kind: f.maintenance_version() for f in (bot.banners, bot.daily)}
        self.feed = discord.ui.Select(options=[discord.SelectOption(label=x.title(), value=x) for x in ('banner', 'daily')])
        self.action = discord.ui.Select(options=[discord.SelectOption(label='Pause for 15 minutes', value='900'),
            discord.SelectOption(label='Pause for one hour', value='3600'), discord.SelectOption(label='Resume', value='0')])
        self.reason = discord.ui.TextInput(min_length=5, max_length=300)
        self.add_item(discord.ui.Label(text='Feed', component=self.feed))
        self.add_item(discord.ui.Label(text='Action', description='Preserves destinations, votes and receipts. Other services continue.', component=self.action))
        self.add_item(discord.ui.Label(text='Private reason', component=self.reason))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_owner(i)
        feed = self.bot.banners if self.feed.values[0] == 'banner' else self.bot.daily
        if feed.maintenance_version() != self.previous[feed.kind]:
            raise ValueError('Maintenance changed. Reopen the controls before confirming.')
        seconds = int(self.action.values[0])
        reason=str(self.reason).strip()
        if seconds not in {0,900,3600} or not 5<=len(reason)<=300:
            raise ValueError('Choose a maintenance duration and provide a reason in 5 to 300 characters.')
        feed.pause(bool(seconds), i.user.id, seconds=seconds)
        with self.bot.store.connection:
            self.bot.store.audit('feed-maintenance-reason', i.user.id, reason)
        await reply(i, feed.kind.title() + (' paused temporarily. Current Discord requests may finish; expired images will not be replayed.' if seconds else ' resumed. Only eligible images will be delivered.'))
