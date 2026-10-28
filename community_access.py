"""Reviewable official-server role plan. Never apply permissions during startup."""

import hashlib
import json
import re

import discord

from community_hub import CENTRAL_GUILD_ID
from global_views import ScopedView
from bot_views import reply

ROLE_IDS={'members':1554955923854725160,'artists':1556741950361702410,'moderators':1556727848415273132}


def access_plan(guild):
    if guild.id!=CENTRAL_GUILD_ID:
        raise ValueError('This plan belongs only to the official community.')
    roles={key:guild.get_role(ident) for key,ident in ROLE_IDS.items()}
    if any(role is None for role in roles.values()):
        raise ValueError('A known role is missing. Review the current server report before applying a plan.')
    angelic=[r for r in guild.roles if re.findall(r'\w+',r.name.casefold())[-1:]==['angelic']]
    if len(angelic)>1:
        raise ValueError('More than one Angelic role exists; resolve the ambiguity before applying.')
    if angelic:
        roles['angelic']=angelic[0]
    normal=discord.Permissions(view_channel=True,read_message_history=True,send_messages=True,
        add_reactions=True,attach_files=True,embed_links=True,use_application_commands=True,
        connect=True,speak=True,use_voice_activation=True,send_messages_in_threads=True)
    mods=discord.Permissions(normal.value)
    mods.update(manage_messages=True,manage_threads=True,moderate_members=True,kick_members=True,
                ban_members=True,manage_nicknames=True,mute_members=True,deafen_members=True,
                move_members=True,view_audit_log=True)
    result=[]
    for key,role in roles.items():
        desired=mods if key=='moderators' else normal if key=='members' else discord.Permissions.none()
        if role.managed or role>=guild.me.top_role:
            raise ValueError('The bot must be above the roles in this plan. Managed roles are not edited.')
        result.append((role,desired))
    signature=hashlib.sha256(json.dumps([(r.id,r.permissions.value,p.value) for r,p in result]).encode()).hexdigest()
    return result,signature


class AccessReview(ScopedView):
    def __init__(self,bot,i):
        super().__init__(bot,i,owner=True,admin=True)
        self.plan,self.signature=access_plan(i.guild)

    def description(self):
        return ('## Official community · role review\n**Assinantes:** normal conversation, attachments, reactions, commands and voice where channels allow it. '
                '**Artista / Angelic, when present:** visual roles without additional permissions. '
                '**Mods:** moderation permissions and local bot tools, without Administrator, Manage Server, Manage Roles or Manage Webhooks.\n\n'
                'Role membership, names, colors, ordering, @everyone and channel overrides are preserved. '
                'Existing channel exceptions still apply; this review does not certify a channel as private.\n\n'
                'Apply changes the listed roles only. A changed role plan must be reviewed again.')

    @discord.ui.button(label='Apply reviewed role permissions',style=discord.ButtonStyle.danger)
    async def apply(self,i,button):
        self.require(i)
        current,signature=access_plan(i.guild)
        if signature!=self.signature:
            raise ValueError('The roles changed. Open a fresh review before applying.')
        await i.response.defer(ephemeral=True,thinking=True)
        async with self.bot.guild_lock(self.guild):
            current,signature=access_plan(i.guild)
            if signature!=self.signature:
                raise ValueError('The roles changed. Open a fresh review.')
            for role,permissions in current:
                if role.permissions.value!=permissions.value:
                    await role.edit(permissions=permissions,reason='Official community access plan applied by the bot owner')
        self.stop()
        await reply(i,'The reviewed role permissions were applied. Channel exceptions remain; verify access with an ordinary member account before changing channel visibility.')
