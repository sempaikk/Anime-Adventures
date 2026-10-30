"""Explicit administrative previews, reversible tool settings and read-only release checks."""

import asyncio
import io
import json

import discord

from adventure_store import MODULES
from bot_domain import safe
from bot_views import BoundModal, reply
from bot_ui import edit_response
from global_views import ScopedView


class SetupView(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i, admin=True)
        bot.require_admin(i)
        self.destination = i.channel_id

    def description(self):
        from operations_views import server_overview
        data, version = self.bot.adventures.state.settings(self.guild)
        return ('## Server setup · review before saving\n' + server_overview(self.bot, self.guild)
                + '\n\nGame modules: ' + (', '.join(data['modules']) or 'none')
                + '\nGroup channel: ' + (f"<#{data['party_channel']}>" if data['party_channel'] else 'not selected')
                + '\nFeed notification timezone: ' + data['timezone']
                + '\n\nChoose an existing channel, then review a feed connection. Tool settings have a separate confirmation. '
                  'Global chat uses its existing /globalchat consent and webhook setup. No channels or roles are created.'
                + '\n\nPermission needs: game lookups use interactions; image feeds need View Channel, Send Messages, Attach Files and Read Message History; '
                  'banner reactions also need Add Reactions. Groups need a normal text channel; optional scheduled events need Create Events.')

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text, discord.ChannelType.news], placeholder='Choose an existing feed channel', row=0)
    async def channel(self, i, select):
        self.require(i)
        self.destination = select.values[0].id
        await edit_response(i, content=self.description()+f'\n\nSelected for the next review: <#{self.destination}>.', view=self)

    @discord.ui.button(label='Review banners', row=1)
    async def banners(self, i, button):
        self.require(i)
        view = FeedSetupReview(self.bot, i, 'banner', self.destination)
        await reply(i, view.description(), view=view)

    @discord.ui.button(label='Review daily', row=1)
    async def daily(self, i, button):
        self.require(i)
        view = FeedSetupReview(self.bot, i, 'daily', self.destination)
        await reply(i, view.description(), view=view)

    @discord.ui.button(label='Review game modules', row=1)
    async def modules(self, i, button):
        self.require(i)
        await i.response.send_modal(SettingsForm(self.bot, i))

    @discord.ui.button(label='Export tool settings', row=2)
    async def export(self, i, button):
        self.require(i)
        data = self.bot.adventures.state.settings(self.guild)[0]
        file = discord.File(io.BytesIO(json.dumps({'schema': 1, 'settings': data}, indent=2).encode()), filename='adventures-tool-settings.json')
        try:
            await reply(i, 'Tool settings only: no tokens, relay messages, consent or delivery records. Import requires a new review.', file=file)
        finally:
            file.close()

    @discord.ui.button(label='Import tool settings', row=2)
    async def import_settings(self, i, button):
        self.require(i)
        await i.response.send_modal(ImportSettings(self.bot, i))

    @discord.ui.button(label='Review last tool change', row=2)
    async def undo(self, i, button):
        self.require(i)
        state = self.bot.adventures.state
        row = state.one('SELECT * FROM bot_tool_history WHERE guild=? ORDER BY id DESC LIMIT 1', (str(self.guild),))
        if not row:
            raise ValueError('No tool configuration changes are recorded.')
        view = SettingsConfirm(self.bot, i, json.loads(row['before_data']), state.settings(self.guild)[1])
        await reply(i, 'Review undo of the last tool-settings change. Feed destinations, consent, votes and receipts are outside this undo.\n\n'+view.description(), view=view)


class FeedSetupReview(ScopedView):
    def __init__(self, bot, i, kind, destination):
        super().__init__(bot, i, admin=True)
        self.feed = bot.daily if kind == 'daily' else bot.banners
        self.destination = destination
        self.generation = self.feed.generation(i.guild_id)

    def description(self):
        from feed_views import feed_permissions
        channel = self.bot.get_channel(self.destination)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild:
            raise ValueError('Choose an existing text channel in this server.')
        missing = feed_permissions(channel, channel.guild.me, reactions=self.feed.kind=='banner')
        current = self.feed.target(self.guild)
        return (f"## Review {self.feed.kind} destination\nCurrent: " + (f"<#{current['channel_id']}>" if current else 'not configured')
                + f'\nProposed: <#{self.destination}>\n'
                + ('Missing permissions: '+', '.join(missing) if missing else 'Required channel permissions are ready.')
                + '\n\nConfirming changes this feed destination. Existing channel history and votes stay in place. No announcement crossposting is enabled.')

    @discord.ui.button(label='Confirm reviewed feed destination', style=discord.ButtonStyle.success)
    async def confirm(self, i, button):
        self.require(i)
        from feed_views import feed_permissions
        channel = self.bot.get_channel(self.destination)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild:
            raise ValueError('The reviewed channel is unavailable.')
        for member in (i.user, channel.guild.me):
            p = channel.permissions_for(member)
            if not p.view_channel or not p.read_message_history:
                raise ValueError('You and the bot need access to the reviewed channel.')
        missing = feed_permissions(channel, channel.guild.me, reactions=self.feed.kind=='banner')
        if missing: raise ValueError('Grant the bot: '+', '.join(missing)+'.')
        await i.response.defer(ephemeral=True, thinking=True)
        async with self.bot.guild_lock(self.guild):
            if self.feed.generation(self.guild) != self.generation:
                raise ValueError('Feed configuration changed. Review it again before saving.')
            cfg = self.bot.globalchat.store.channel(self.guild)
            from community_hub import CENTRAL_UPDATE_CHANNEL_ID
            if str(channel.id) == str(CENTRAL_UPDATE_CHANNEL_ID) or cfg and cfg['channel_id'] == str(channel.id):
                raise ValueError('Keep image feeds separate from global chat and official updates.')
            self.feed.configure(self.guild, self.destination)
        self.confirm.disabled = True
        await reply(i, f'Confirmed {self.feed.kind} destination: <#{self.destination}>. Delivery follows the existing source and freshness checks.')


class SettingsForm(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title='Review game-tool settings')
        self.bind(bot, i); bot.require_admin(i)
        old, self.version = bot.adventures.state.settings(i.guild_id)
        self.modules = discord.ui.Select(min_values=0, max_values=len(MODULES), required=False, options=[discord.SelectOption(label='Scheduled events (optional)' if x=='events' else x.title(), value=x, default=x in old['modules']) for x in MODULES])
        self.channel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text], min_values=0, max_values=1, required=False, default_values=[discord.Object(id=int(old['party_channel']))] if old['party_channel'] else None)
        self.zone = discord.ui.TextInput(default=old['timezone'], max_length=80)
        self.start = discord.ui.TextInput(default=str(old['quiet_start']) if old['quiet_start'] is not None else '', required=False, max_length=2)
        self.end = discord.ui.TextInput(default=str(old['quiet_end']) if old['quiet_end'] is not None else '', required=False, max_length=2)
        self.add_item(discord.ui.Label(text='Enabled game modules', component=self.modules))
        self.add_item(discord.ui.Label(text='Normal channel for groups, optional', component=self.channel))
        self.add_item(discord.ui.Label(text='IANA timezone for feed quiet hours', component=self.zone))
        self.add_item(discord.ui.Label(text='Feed quiet hours start, optional', description='0 to 23. Images remain timely; only push/desktop notification behavior changes.', component=self.start))
        self.add_item(discord.ui.Label(text='Feed quiet hours end, optional', component=self.end))

    async def on_submit(self, i):
        if not await self.interaction_check(i): return
        self.bot.require_admin(i)
        try:
            data = {'modules': list(self.modules.values), 'party_channel': str(self.channel.values[0].id) if self.channel.values else None, 'timezone': str(self.zone).strip(), 'quiet_start': int(str(self.start)) if str(self.start).strip() else None, 'quiet_end': int(str(self.end)) if str(self.end).strip() else None}
        except ValueError: raise ValueError('Quiet hours use whole hours from 0 to 23.') from None
        view = SettingsConfirm(self.bot, i, data, self.version)
        await reply(i, view.description(), view=view)


class SettingsConfirm(ScopedView):
    def __init__(self, bot, i, data, version):
        super().__init__(bot, i, admin=True)
        self.data, self.version = data, version

    def description(self):
        before = self.bot.adventures.state.settings(self.guild)[0]
        changed = [key for key in self.data if self.data.get(key) != before.get(key)]
        return '## Review tool-settings changes\n' + ('\n'.join(f"**{safe(key)}:** {safe(before.get(key), 250)} → {safe(self.data[key], 250)}" for key in changed) or 'No changes.') + '\n\nOnly optional tool settings change. No roles, relay consent, votes or receipt history are modified.'

    @discord.ui.button(label='Confirm reviewed tool settings', style=discord.ButtonStyle.success)
    async def confirm(self, i, button):
        self.require(i)
        if self.data.get('party_channel'):
            channel = self.bot.get_channel(int(self.data['party_channel']))
            if channel is None or channel.guild.id != i.guild_id:
                raise ValueError('Choose an existing group channel in this server.')
            self.bot.adventures.normal_channel(channel, i.user)
        async with self.bot.guild_lock(self.guild):
            self.bot.adventures.state.configure(self.guild, self.actor, self.data, self.version)
        self.confirm.disabled = True
        await edit_response(i, content='Reviewed optional-tool settings saved. Fresh feed images continue to be delivered at their normal time.', view=self)


class ImportSettings(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title='Import optional-tool settings')
        self.bind(bot, i); bot.require_admin(i)
        self.version = bot.adventures.state.settings(i.guild_id)[1]
        self.text = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=1800)
        self.add_item(discord.ui.Label(text='Paste the exported tool-settings JSON', description='Only documented settings are accepted. Review all changes before saving.', component=self.text))

    async def on_submit(self, i):
        if not await self.interaction_check(i): return
        self.bot.require_admin(i)
        try: data = json.loads(str(self.text))
        except ValueError: raise ValueError('Paste a valid exported tool-settings document.') from None
        if not isinstance(data, dict) or set(data) != {'schema','settings'} or data['schema'] != 1 or not isinstance(data['settings'], dict):
            raise ValueError('Only the exported schema-1 tool-settings document is accepted.')
        view = SettingsConfirm(self.bot, i, data['settings'], self.version)
        await reply(i, view.description(), view=view)


class ToolOperations(ScopedView):
    def __init__(self, bot, i):
        super().__init__(bot, i, owner=True)
        bot.require_owner(i)

    @discord.ui.button(label='Review knowledge pack', row=0)
    async def pack(self, i, button):
        self.require(i)
        from game_knowledge import Knowledge
        k = Knowledge()
        await reply(i, f"## Knowledge pack review\nFingerprint: {k.data['fingerprint']}\n{len(k.units)} exact forms · {len(k.items)} item identities · {len(k.guides)} guides.\n\nImported facts are historical and attributed, not verified current. Updates go through scripts/check_game_data.py and the verified release process; no runtime source-code overwrite is offered.")

    @discord.ui.button(label='Check release / restart', row=0)
    async def release(self, i, button):
        self.require(i)
        await i.response.defer(ephemeral=True, thinking=True)
        await reply(i, await release_status(self.bot))

    @discord.ui.button(label='Review feature pilot', row=0)
    async def gate(self, i, button):
        self.require(i)
        await i.response.send_modal(PilotForm(self.bot, i))

    @discord.ui.button(label='Discovery checklist', row=1)
    async def discovery(self, i, button):
        self.require(i)
        await reply(i, '## App Directory preparation\nReview the actual Developer Portal requirements for app verification and Discovery. Prepare an accurate description, example images, support invite and installation permissions.\n\nOfficial support: https://discord.gg/qwH7DvdtDZ\nhttps://discord.com/developers/applications\n\nDirectory eligibility and publication are external settings; this panel does not claim they are active. User-facing descriptions should describe only features already running.')


class PilotForm(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title='Review feature pilot')
        self.bind(bot, i); bot.require_owner(i)
        self.module = discord.ui.Select(options=[discord.SelectOption(label=x.title(), value=x) for x in MODULES])
        self.guilds = discord.ui.TextInput(required=False, max_length=700, placeholder='Verified private guild IDs, one per line; empty to release to enabled servers')
        self.add_item(discord.ui.Label(text='Optional module', component=self.module))
        self.add_item(discord.ui.Label(text='Allowed server IDs', description='Only servers where the bot is currently installed are accepted. A separate confirmation follows.', component=self.guilds))

    async def on_submit(self, i):
        if not await self.interaction_check(i): return
        self.bot.require_owner(i)
        module = self.module.values[0]
        guilds = sorted(set(str(self.guilds).split()))
        if len(guilds) > 20 or any(not x.isdigit() or self.bot.get_guild(int(x)) is None for x in guilds):
            raise ValueError('Use up to 20 verified current server IDs.')
        current = self.bot.adventures.state.one('SELECT * FROM bot_feature_gates WHERE module=?', (module,))
        view = PilotConfirm(self.bot, i, module, guilds, current['version'] if current else 0)
        await reply(i, f"Review {module}: " + (', '.join(guilds) if guilds else 'release to servers where administrators enable this module') + '. Existing feeds and global chat are outside this gate.', view=view)


class PilotConfirm(ScopedView):
    def __init__(self, bot, i, module, guilds, version):
        super().__init__(bot, i, owner=True)
        self.module,self.guilds,self.version = module,guilds,version

    @discord.ui.button(label='Confirm feature availability', style=discord.ButtonStyle.success)
    async def confirm(self, i, button):
        self.require(i)
        state = self.bot.adventures.state
        with state.db:
            current = state.one('SELECT * FROM bot_feature_gates WHERE module=?', (self.module,))
            if (current['version'] if current else 0) != self.version:
                raise ValueError('Feature availability changed. Review it again.')
            # Keep the version on an open gate, so an older confirmation cannot
            # overwrite a newer rollout merely because a row was deleted.
            allowed = self.guilds if self.guilds else ['*']
            state.db.execute('INSERT OR REPLACE INTO bot_feature_gates VALUES(?,?,?)', (self.module,json.dumps(allowed),self.version+1))
        self.confirm.disabled = True
        await edit_response(i, content='Reviewed feature availability saved.', view=self)


async def release_status(bot):
    from bot_release import build_info, label
    disk = await asyncio.to_thread(build_info)
    running = bot.build
    text = f"## Release status · private\nRunning: {label(running)}\nFiles on disk: {label(disk)} · {'verified' if disk['verified'] else 'incomplete / changed'}"
    now = bot.store.clock()
    cached = bot.store.get('tool-release-check')
    data = json.loads(cached) if cached else {}
    if not data or now - data.get('checked', 0) > 900:
        result = {'checked': now, 'available': None}
        try:
            session = await bot.globalchat.http_session()
            async with session.get('https://raw.githubusercontent.com/sempaikk/Anime-Adventures/main/data/build.json', allow_redirects=False, timeout=10) as response:
                if response.status == 200:
                    raw = await response.content.read(256*1024+1)
                    if len(raw) <= 256*1024:
                        manifest = json.loads(raw)
                        if manifest.get('schema') == 1 and isinstance(manifest.get('version'),str) and len(manifest['version']) <= 40 and isinstance(manifest.get('fingerprint'),str) and len(manifest['fingerprint']) == 64:
                            result['available'] = {'version': manifest['version'], 'fingerprint': manifest['fingerprint']}
        except (OSError, ValueError, TimeoutError):
            pass
        except Exception:
            pass
        bot.store.set('tool-release-check', json.dumps(result)); data = result
    available = data.get('available')
    text += '\nAvailable release: ' + (label(available) if available else 'not confirmed; repository check unavailable')
    text+=f"\nRepository check: <t:{int(data.get('checked',now))}:R> (cached for up to 15 minutes)."
    if not disk['verified']:
        text += '\n\nThe files on disk do not pass release verification. Complete the repository update before restarting; preserve DATA_DIR and credentials.'
    elif running.get('fingerprint') != disk.get('fingerprint') or available and running.get('fingerprint') != available['fingerprint']:
        text += '\n\nAn update/restart is pending. On the configured Bot-Hosting deployment, click Reiniciar, then confirm the Running version line. The existing startup fetches GitHub; no ZIP upload is needed.'
    else:
        text += '\n\nRunning code matches the verified files on disk.' + (' It also matches the confirmed available release.' if available else ' Availability of a newer release is unknown.')
    return text
