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

    @discord.ui.button(label='Enable / check this channel',style=discord.ButtonStyle.success,row=1)
    async def enable(self,i,button):
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

    @discord.ui.button(label='Status',row=0)
    async def status(self,i,button):
        require_banner_admin(i)
        await reply(i,self.feed.private_status(self.guild))

    @discord.ui.button(label='How it works',row=0)
    async def help(self,i,button):
        await reply(i,FAQ)
