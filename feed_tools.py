"""Player-facing delivery links and freshness, with no image re-upload."""

import discord

from bot_views import reply
from global_views import ScopedView


def access(feed, i):
    target = feed.target(i.guild_id)
    channel = feed.bot.get_channel(int(target['channel_id'])) if target else None
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != i.guild_id:
        raise ValueError('An administrator must configure a visible destination in this server first.')
    for who in (i.user, channel.guild.me):
        p = channel.permissions_for(who)
        if not p.view_channel or not p.read_message_history:
            raise ValueError('You and the bot need access to this server\'s feed channel history.')
    return channel


def records(feed, channel):
    rows = []
    if feed.kind == 'banner':
        rows.extend(dict(r) for r in feed.query("SELECT message_id,attempted_at,source_message FROM banner_image_receipts WHERE channel_id=? AND state IN ('sent','legacy') AND message_id IS NOT NULL ORDER BY attempted_at DESC LIMIT 8", (str(channel),)))
    rows.extend(dict(r) for r in feed.query("SELECT j.message_id,j.attempted_at,e.source_message FROM banner_jobs j JOIN banner_events e ON e.id=j.event_id WHERE j.channel_id=? AND j.state='sent' AND j.message_id IS NOT NULL ORDER BY j.attempted_at DESC LIMIT 8", (str(channel),)))
    unique = {r['message_id']: r for r in sorted(rows, key=lambda r:r['attempted_at'])}
    return sorted(unique.values(), key=lambda r:r['attempted_at'], reverse=True)[:6]


def status(feed, i):
    channel = access(feed, i)
    state = feed.diagnostics.snapshot(i.guild_id)
    text = f'## {feed.kind.title()} · this server\nDestination: <#{channel.id}>\n'
    text += '\nLast successful source check: ' + (f"<t:{int(state['polled'])}:R>" if state['polled'] else 'not confirmed')
    delivery = state.get('delivery')
    text += '\nLast confirmed local delivery: ' + (f"<t:{int(delivery['confirmed_at'])}:R>" if delivery and 'confirmed_at' in delivery else f"<t:{int(delivery['confirmed'])}:R>" if delivery and 'confirmed' in delivery else 'not confirmed in the recent receipt window')
    if feed.status != 'ready' or not state['polled'] or feed.clock()-state['polled'] > 180:
        text += '\n\nThe source could not be checked recently. Previous deliveries may still be visible; a new image is not yet confirmed.'
    elif state['pending']:
        text += '\n\nAn image is awaiting delivery confirmation in this server. Please wait; checking status does not resend it.'
    elif state['source_message'] and (state['received_source'] != state['source_message'] or state['observed'] > state['received_version']):
        text += '\n\nA newer source image was observed and is still being checked.'
    else:
        text += '\n\nThe source was checked. No newer image awaiting delivery is confirmed. This is not a game-reset countdown.'
    return text


async def latest(feed, i, *, history=False):
    channel = access(feed, i)
    rows = records(feed, channel.id)
    if not rows:
        await reply(i, 'No confirmed local message links remain in the recent receipt window. No old image was re-uploaded.'); return
    if not history:
        if not i.response.is_done(): await i.response.defer(ephemeral=True, thinking=True)
        try:
            message = await channel.fetch_message(int(rows[0]['message_id']))
        except discord.NotFound:
            await reply(i, 'The last confirmed post was deleted. The bot will not recreate it. Choose Recent deliveries to inspect other retained links.'); return
        if message.author.id != feed.bot.user.id or message.webhook_id:
            raise ValueError('The confirmed message could not be validated as a feed delivery.')
    name = 'Recent deliveries' if history else 'Last confirmed delivery'
    text = f'## {name}\nThese are local delivery links, not a claim that an old banner is still current.\n\n'
    for row in rows if history else rows[:1]:
        text += f"[Open delivered image](https://discord.com/channels/{i.guild_id}/{channel.id}/{row['message_id']}) · <t:{int(row['attempted_at'])}:R>\n"
    await reply(i, text)


def silence_payload(bot, guild, params):
    tools = getattr(bot, 'adventures', None)
    if tools:
        from adventure_service import quiet
        if quiet(tools.state.settings(guild)[0], tools.state.clock()):
            if params.payload is not None:
                params.payload['flags'] = params.payload.get('flags', 0) | 4096
            else:
                import json
                for entry in params.multipart:
                    if entry['name'] == 'payload_json':
                        data = json.loads(entry['value'])
                        data['flags'] = data.get('flags', 0) | 4096
                        entry['value'] = json.dumps(data)
