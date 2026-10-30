"""Private, read-only previews and explicit feed configuration in the same commands."""

import io

import discord

from bot_views import GuardedView, reply
from banner_relay import BannerControls, require_banner_admin, MAX_IMAGE

FAQ = ('## Image feeds\nThe source publishes the game images; the bot forwards verified static files. '
       'The source publication time describes freshness. Cache retention is not a game reset timer.\n\n'
       'Each banner image has its own win / mid / lose reactions. Counts include the bot\'s initial reaction. '
       'Restarting preserves configuration, delivery records and votes. Deleting a delivered image does not recreate it.\n\n'
       'Images are delivered directly by the installed bot. Automatic announcement crossposting is disabled.')


def feed_permissions(channel, member, *, reactions=False):
    p = channel.permissions_for(member)
    names = {'view_channel':'View Channel','send_messages':'Send Messages','attach_files':'Attach Files',
             'read_message_history':'Read Message History'}
    if reactions:
        names['add_reactions'] = 'Add Reactions'
    return [label for key,label in names.items() if not getattr(p,key,False)]


async def preview(feed, i):
    if not feed.bot.globalchat.store.limit('feed-preview:'+str(i.user.id),3,60):
        raise ValueError('Please wait a moment before requesting more image previews.')
    if not i.response.is_done():
        await i.response.defer(ephemeral=True,thinking=True)
    if feed.bot.preview_slots.locked():
        raise ValueError('Another image preview is being prepared. Please try again shortly.')
    async with feed.bot.preview_slots:
        await _preview(feed,i)


async def _preview(feed, i):
    if not i.response.is_done():
        await i.response.defer(ephemeral=True, thinking=True)
    target = feed.target(i.guild_id)
    channel = feed.bot.get_channel(int(target['channel_id'])) if target else None
    if channel is None or not isinstance(i.user,discord.Member):
        raise ValueError('A configured destination visible to your server member account is required for a preview.')
    p = channel.permissions_for(i.user)
    if not p.view_channel or not p.read_message_history:
        raise ValueError('You need access to the configured feed channel to preview its images.')
    suffix = (" AND id=(SELECT c.event_id FROM daily_current c JOIN daily_source_head h ON h.singleton=c.singleton AND h.source_message=c.source_message)"
              if feed.kind=='daily' else '')
    row = feed.query('SELECT * FROM banner_events WHERE created_at>?'+suffix+' ORDER BY created_at DESC,rowid DESC LIMIT 1',
                     (feed.clock()-feed.max_age,)).fetchone()
    state=feed.diagnostics.snapshot()
    newer_waiting=bool(row and state['observed']>row['created_at'] and
        (state['source_message']!=state['received_source'] or state['observed']>state['received_version']))
    if row is None or newer_waiting or feed.diagnostics.obsolete(row['source_message']) or feed.status != 'ready':
        await reply(i,'No current verified image is available. The bot is waiting for the source; an old image will not be labelled as current.')
        return
    from contextlib import AsyncExitStack
    async with AsyncExitStack() as reservations:
        budget=getattr(feed.bot,'instance_storage',None)
        if budget:
            sizes=feed.query('SELECT length(data) FROM banner_assets WHERE digest IN (SELECT value FROM banner_events,json_each(images) WHERE banner_events.id=?)',(row['id'],)).fetchall()
            await reservations.enter_async_context(budget.reserve(0,memory=3*sum(r[0] for r in sizes)))
        await send_preview(feed,i,row)


async def send_preview(feed,i,row):
    assets = feed.assets(row['id'])
    if not assets or any(x is None for x in assets):
        raise ValueError('The current files are unavailable. Wait for the next source update.')
    if any(len(x['data'])>min(MAX_IMAGE,i.guild.filesize_limit) for x in assets):
        raise ValueError('The current image exceeds this server\'s upload limit. Check the configured feed channel.')
    files = [discord.File(io.BytesIO(x['data']),filename=f'preview-{index}.{x["extension"]}') for index,x in enumerate(assets)]
    try:
        await reply(i,f'Private preview · source published/updated <t:{int(row["created_at"])}:R>. This does not change settings or post in the feed channel.',files=files)
    finally:
        for file in files:
            file.close()


class FeedPanel(GuardedView):
    def __init__(self, bot, i, *, kind):
        super().__init__(timeout=300)
        self.bot,self.actor,self.guild,self.channel = bot,i.user.id,i.guild_id,i.channel_id
        self.feed = bot.daily if kind=='daily' else bot.banners
        self.generation = self.feed.generation(self.guild)
        self.kind = kind
        admin = i.permissions.manage_guild or getattr(i.permissions,'administrator',False)
        self.admin = admin
        if not admin:
            self.remove_item(self.enable)
            self.remove_item(self.disable)
            self.remove_item(self.status)
            self.remove_item(self.diagnostics)

    async def interaction_check(self, i):
        if (i.user.id,i.guild_id,i.channel_id)!=(self.actor,self.guild,self.channel):
            await reply(i,'Open the command to use your own private feed controls.')
            return False
        return True

    def description(self):
        name = 'Daily challenge' if self.kind=='daily' else 'Banners'
        target = self.feed.target(self.guild)
        if not self.admin:
            return (f'## {name}\nView the current verified images privately. A preview does not change settings or post in the feed channel. '
                'You need access to this server\'s configured destination.\n\n'+('Choose View current images.' if target else 'Ask a server administrator to configure a destination first.'))
        return (f'## {name}\n'+(f'Configured in <#{target["channel_id"]}>.' if target else 'Not configured in this server.')
            +'\n\n**View:** preview the current verified image privately.\n**Configure:** an administrator can enable this channel after checking permissions. '
            'Opening this panel does not change a destination.\n\n'+self.feed.description(self.guild))

    @discord.ui.button(label='View current images',style=discord.ButtonStyle.primary,row=0)
    async def view(self,i,button):
        await preview(self.feed,i)

    @discord.ui.button(label='Open last delivery', row=3)
    async def open_last(self, i, button):
        from feed_tools import latest
        await latest(self.feed, i)

    @discord.ui.button(label='Recent deliveries', row=3)
    async def recent(self, i, button):
        from feed_tools import latest
        await latest(self.feed, i, history=True)

    @discord.ui.button(label='Delivery status', row=3)
    async def player_status(self, i, button):
        from feed_tools import status
        await reply(i, status(self.feed, i))

    @discord.ui.button(label='Report image issue', row=4)
    async def report_image(self, i, button):
        from community_hub import CENTRAL_GUILD_ID, CENTRAL_COMMUNITY_INVITE
        from feed_tools import access,records
        channel=access(self.feed,i)
        recent=records(self.feed,channel.id)
        state=self.feed.diagnostics.snapshot(i.guild_id)
        link=(f"https://discord.com/channels/{i.guild_id}/{channel.id}/{recent[0]['message_id']}" if recent else 'No recent confirmed local link')
        context=(f"Feed: {self.kind}\nDelivery: {link}\nSource published/updated: {state['observed']}\nRunning version: {self.bot.build.get('version','unknown')}")
        if i.guild_id == CENTRAL_GUILD_ID:
            from community_feedback import FeedbackForm
            form=FeedbackForm(self.bot,i,context=context)
            await i.response.send_modal(form)
        else:
            await reply(i, 'For an incorrect or old feed image, contact the official community: '+CENTRAL_COMMUNITY_INVITE+'\nCopy these details and describe the issue in the private feedback form there:\n\n'+context+'\n\nFeedback is handled privately in the official community.')

    @discord.ui.button(label='Enable in this channel',style=discord.ButtonStyle.success,row=1)
    async def enable(self,i,button):
        require_banner_admin(i)
        target=self.feed.target(self.guild)
        if target and target['channel_id']!=str(self.channel):
            view=FeedMoveConfirm(self.bot,i,kind=self.kind,generation=self.generation)
            await reply(i,f'Change the {self.kind} destination from <#{target["channel_id"]}> to <#{self.channel}>? History and votes stay in their original channels.',view=view)
            return
        await self.configure(i)

    async def configure(self,i):
        require_banner_admin(i)
        if not isinstance(i.channel,discord.TextChannel):
            raise ValueError('Choose a server text channel.')
        missing = feed_permissions(i.channel,i.guild.me)
        if missing:
            raise ValueError('Grant the bot: '+', '.join(missing)+'.')
        await i.response.defer(ephemeral=True,thinking=True)
        async with self.bot.guild_lock(self.guild):
            if self.feed.generation(self.guild)!=self.generation:
                raise ValueError('The settings changed. Open the command again before configuring.')
            self.feed.configure(self.guild,self.channel)
        self.generation=self.feed.generation(self.guild)
        optional=feed_permissions(i.channel,i.guild.me,reactions=self.kind=='banner')
        await reply(i,f'**Connection ready:** <#{self.channel}>. Static images only; settings and votes survive restarts.'
            + ('\nW/M/L also needs Add Reactions.' if 'Add Reactions' in optional else '')
            +'\n\n'+self.feed.private_status(self.guild),view=FeedPanel(self.bot,i,kind=self.kind))

    @discord.ui.button(label='Stop receiving',style=discord.ButtonStyle.danger,row=1)
    async def disable(self,i,button):
        require_banner_admin(i)
        await i.response.defer(ephemeral=True,thinking=True)
        async with self.bot.guild_lock(self.guild):
            if self.feed.generation(self.guild)!=self.generation:
                raise ValueError('The settings changed. Open the command again.')
            self.feed.disable(self.guild)
        self.stop()
        await reply(i,'Receiving stopped. History and votes remain. A request already accepted by Discord may finish.')

    @discord.ui.button(label='Check connection',row=0)
    async def status(self,i,button):
        require_banner_admin(i)
        from operations_views import server_overview
        target=self.feed.target(self.guild)
        channel=self.bot.get_channel(int(target['channel_id'])) if target else None
        missing=feed_permissions(channel,channel.guild.me) if isinstance(channel,discord.TextChannel) else ['Configured channel access']
        await reply(i,server_overview(self.bot,self.guild)+'\n\n'+self.feed.private_status(self.guild)
            +'\n'+('Administrator action needed: '+', '.join(missing)+'.' if missing else 'Channel permissions are ready. This check does not move or reconfigure the feed.'))

    @discord.ui.button(label='Copy diagnostics',row=2)
    async def diagnostics(self,i,button):
        require_banner_admin(i)
        from operations_views import diagnostic_text
        await reply(i,diagnostic_text(self.bot,self.guild))

    @discord.ui.button(label='How it works',row=0)
    async def help(self,i,button):
        await reply(i,FAQ)


class FeedMoveConfirm(GuardedView):
    def __init__(self,bot,i,*,kind,generation):
        super().__init__(timeout=180)
        self.panel=FeedPanel(bot,i,kind=kind)
        self.panel.generation=generation

    async def interaction_check(self,i):
        return await self.panel.interaction_check(i)

    @discord.ui.button(label='Confirm destination change',style=discord.ButtonStyle.success)
    async def confirm(self,i,button):
        await self.panel.configure(i)
        self.stop()
