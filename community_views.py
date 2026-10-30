"""Member help, installation and local moderation without extra slash commands."""

import os
from urllib.parse import urlsplit

import discord

from bot_views import reply
from global_views import ScopedView
from community_hub import CENTRAL_GUILD_ID,CENTRAL_COMMUNITY_INVITE


SHORT_HELP = ('## Adventures\n**Game tools:** `/adventures` → sourced historical knowledge, manual plans, calculators, groups and optional reminders.\n\n**Banners:** `/setbanner` → View current images. Administrators enable a destination explicitly. '
    'Every banner image has the original win / mid / lose reactions.\n\n'
    '**Daily challenge:** `/dailychallenge` → View current images. Publication time comes from the source; an expired file is not presented as current.\n\n'
    '**Global chat:** `/globalchat` in the configured global channel → Join. Only new messages after confirmation are shared. '
    'My messages shows delivery progress; Leave stops new sharing. Reports and controls are private.\n\n'
    '**Restarts:** settings, receipts and votes remain saved. Reaction counts include the bot\'s seed. '
    'Automatic announcement crossposting is disabled. Images have no advertising captions.')


class HelpView(ScopedView):
    def __init__(self,bot,i):
        super().__init__(bot,i)
        app_id=getattr(bot,'application_id',None) or (bot.user.id if getattr(bot,'user',None) else None)
        if app_id:
            from app_profile import install_permissions
            p=install_permissions()
            self.add_item(discord.ui.Button(label='Add Adventures',url=f'https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions={p.value}'))
            p=install_permissions('images')
            self.add_item(discord.ui.Button(label='Add images only',url=f'https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions={p.value}'))
            p=install_permissions('tools')
            self.add_item(discord.ui.Button(label='Add game tools only',url=f'https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions={p.value}'))
        invite=(os.getenv('COMMUNITY_INVITE_URL') or CENTRAL_COMMUNITY_INVITE).strip()
        try:
            parsed=urlsplit(invite)
            if len(invite)<=2048 and parsed.scheme=='https' and parsed.hostname in {'discord.gg','discord.com'} and not parsed.username and not parsed.password and parsed.port in (None,443):
                if (parsed.hostname=='discord.gg' and parsed.path.strip('/')) or parsed.path.startswith('/invite/'):
                    self.add_item(discord.ui.Button(label='Official community',url=invite))
        except ValueError:
            pass


class MemberHome(ScopedView):
    def __init__(self,bot,i):
        super().__init__(bot,i)
        if i.guild_id != CENTRAL_GUILD_ID:
            self.remove_item(self.feedback)

    def description(self):
        return ('## Adventures · private controls\nGlobal chat is not configured in this server. An administrator can enable it with `/globalchat`. '
                'Use `/setbanner` or `/dailychallenge` for private image controls.\n\n'
                'Opening these panels does not activate sharing or change destinations.')

    @discord.ui.button(label='How it works',row=0)
    async def help(self,i,button):
        await reply(i,SHORT_HELP,view=HelpView(self.bot,i))

    @discord.ui.button(label='Feedback',row=0)
    async def feedback(self,i,button):
        from community_feedback import FeedbackForm
        await i.response.send_modal(FeedbackForm(self.bot,i))

    @discord.ui.button(label='My requests',row=0)
    async def requests(self,i,button):
        self.require(i)
        from participant_history import RequestHistory
        view=RequestHistory(self.bot,i)
        await reply(i,view.description(),view=view)


class GlobalModeratorView(ScopedView):
    def __init__(self,bot,i):
        super().__init__(bot,i,moderator=True)

    def description(self):
        return ('## Global chat · local moderation\nReview reports and restrict participation **only in this server**. '
                'Connection settings remain with administrators; network actions remain with the bot owner.\n\n'
                'A restriction stops bot sharing here. It does not ban the account from Discord or grant server permissions.')

    @discord.ui.button(label='Server reports',row=0)
    async def reports(self,i,button):
        self.require(i)
        from global_reports import ReportInbox
        view=ReportInbox(self.bot,i)
        await reply(i,view.description(),view=view)

    @discord.ui.button(label='Local restrictions',row=0)
    async def restrictions(self,i,button):
        self.require(i)
        from global_views import ModerationModal
        await i.response.send_modal(ModerationModal(self.bot,i,network=False))

    @discord.ui.button(label='My participation',row=1)
    async def personal(self,i,button):
        self.require(i)
        from global_views import GlobalMemberView
        view=GlobalMemberView(self.bot,i)
        await reply(i,view.description(),view=view)

    @discord.ui.button(label='Review restrictions',row=0)
    async def review_restrictions(self,i,button):
        self.require(i)
        from participant_history import RestrictionView
        view=RestrictionView(self.bot,i,network=False)
        await reply(i,view.description(),view=view)
