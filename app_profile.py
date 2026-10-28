"""Small, truthful application description and feature-specific install permissions."""

import discord
import aiohttp
from community_hub import CENTRAL_COMMUNITY_INVITE

DESCRIPTION=('Anime Adventures banner images with win / mid / lose reactions, daily challenge images, '
             'and opt-in global chat. Use /setbanner, /dailychallenge and /globalchat for private controls. '
             'Community: '+CENTRAL_COMMUNITY_INVITE)


def install_permissions():
    return discord.Permissions(view_channel=True,send_messages=True,read_message_history=True,
        attach_files=True,add_reactions=True,manage_webhooks=True)


async def configure_profile(bot, app):
    if bot.store.get('bot-profile:1')=='done' or not isinstance(app,discord.AppInfo):
        return
    if bot.store.clock()<float(bot.store.get('bot-profile-next-attempt') or 0):
        return
    bot.store.set('bot-profile-next-attempt',bot.store.clock()+300)
    try:
        await app.edit(description=DESCRIPTION,guild_install_scopes=['bot','applications.commands'],
                       guild_install_permissions=install_permissions(),reason='Current Adventures features and installation permissions')
        bot.store.set('bot-profile:1','done')
    except (discord.HTTPException,aiohttp.ClientError,TimeoutError,OSError):
        bot.store.set('bot-profile:1','pending')
