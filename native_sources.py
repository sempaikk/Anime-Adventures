"""Prefer authorized bot access to the two fixed sources whenever it exists."""

import asyncio

import discord

from banner_reader import image_message
from feed_receiver import FeedReceiver
from game_sources import BANNER_CHANNEL_ID,DAILY_CHANNEL_ID


class NativeSources:
    def __init__(self,bot):
        self.bot=bot
        self.receiver=FeedReceiver(bot,primary=True)
        self.channels={}
        self.blocked_until={}

    async def poll(self):
        feeds={BANNER_CHANNEL_ID:self.bot.banners,DAILY_CHANNEL_ID:self.bot.daily}
        self.channels={}
        for ident,feed in feeds.items():
            channel=self.bot.get_channel(ident)
            usable=isinstance(channel,discord.TextChannel) and channel.guild.me is not None
            if usable:
                permissions=channel.permissions_for(channel.guild.me)
                usable=permissions.view_channel and permissions.read_message_history
            feed.native=bool(usable and feed.clock()>=self.blocked_until.get(ident,0))
            if feed.native:
                self.channels[ident]=channel
        if self.channels and not self.receiver.tasks:
            self.receiver.start()
        await asyncio.gather(*(self.scan(ident,channel) for ident,channel in self.channels.items()))
        if len(self.channels)==2 and all(feed.native for feed in feeds.values()):
            await self.bot.banners.stop_reader()
        else:
            self.bot.banners.start()

    async def scan(self, ident, channel):
        feed=self.bot.daily if ident==DAILY_CHANNEL_ID else self.bot.banners
        async def read():
            messages=[message async for message in channel.history(limit=50)]
            if feed.kind=='daily':
                for message in messages:
                    if self.event(message):
                        break
            else:
                for message in reversed(messages):
                    self.event(message)
            self.receiver.handle({'event':'ready','channel_id':str(ident)})
        try:
            await asyncio.wait_for(read(),25)
        except (discord.HTTPException,TimeoutError,OSError):
            feed.native=False
            feed.status='source_unavailable'
            feed.diagnostics.error('authorized_source_unavailable')
            self.blocked_until[ident]=feed.clock()+300

    def event(self,message):
        ident=getattr(getattr(message,'channel',None),'id',None)
        channel=self.channels.get(ident)
        feed=self.bot.daily if ident==DAILY_CHANNEL_ID else self.bot.banners
        if channel is None or not feed.native:
            return False
        event=image_message(message,{BANNER_CHANNEL_ID,DAILY_CHANNEL_ID})
        if event:
            self.receiver.handle(event)
        return bool(event)

    async def edit(self,event):
        channel=self.channels.get(getattr(event,'channel_id',None))
        if channel is not None:
            try:
                self.event(await channel.fetch_message(event.message_id))
            except (discord.HTTPException,TimeoutError,OSError):
                return

    def delete(self,event):
        if event.channel_id in self.channels:
            self.receiver.handle({'event':'source_retracted','channel_id':str(event.channel_id),'message_id':str(event.message_id)})

    async def close(self):
        await self.receiver.close()
