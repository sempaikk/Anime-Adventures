"""Private feed/reaction load drill: synthetic PNGs, SQLite and fake HTTP only."""

import argparse
import asyncio
import io
import json
from pathlib import Path
import random
import resource
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import discord
from PIL import Image
from banner_votes import load_assets
from community_bot import CommunityBot
from game_sources import BANNER_CHANNEL_ID


async def benchmark(guilds=50, delay_ms=5):
    if not 2<=guilds<=200 or not 0<=delay_ms<=100:
        raise ValueError('Use 2 to 200 guilds and 0 to 100 milliseconds of simulated API latency.')
    with tempfile.TemporaryDirectory(prefix='feed-capacity-') as folder:
        bot=CommunityBot(folder)
        sent,reactions=0,0
        try:
            bot._connection.user=SimpleNamespace(id=42)
            bot.health.storage_level='ok'
            channels={}
            async def history(**kwargs):
                if False:
                    yield None
            async def react(emoji):
                nonlocal reactions
                await asyncio.sleep(delay_ms/1000)
                reactions+=1
            for gid in range(1,guilds+1):
                channel=MagicMock(spec=discord.TextChannel)
                channel.id=gid*10
                channel.guild=SimpleNamespace(id=gid,me=bot.user,filesize_limit=8*1024*1024)
                channel.permissions_for.return_value=discord.Permissions(view_channel=True,send_messages=True,
                    attach_files=True,read_message_history=True,add_reactions=True,manage_messages=True)
                channel.history.side_effect=history
                channel.get_partial_message.side_effect=lambda ident:SimpleNamespace(add_reaction=react)
                channels[channel.id]=channel
                bot.banners.configure(gid,channel.id)
            bot.get_channel=lambda ident:channels.get(ident)
            async def send(channel_id,*,params):
                nonlocal sent
                await asyncio.sleep(delay_ms/1000)
                sent+=1
                return {'id':str(100000+sent)}
            bot.http.send_message=AsyncMock(side_effect=send)
            emojis=[]
            for n,(name,digest,raw) in enumerate(load_assets()):
                emoji=discord.PartialEmoji(name=name,id=301+n)
                emojis.append(emoji)
                bot.store.set('banner-vote-emoji:'+digest,emoji.id)
            bot.fetch_application_emojis=AsyncMock(return_value=emojis)
            randomizer=random.Random(42)
            blobs=[]
            for n in range(3):
                out=io.BytesIO()
                Image.frombytes('RGB',(128,128),randomizer.randbytes(128*128*3)).save(out,format='PNG')
                blobs.append(out.getvalue())
            bot.banners.download=AsyncMock(side_effect=blobs)
            start=time.perf_counter()
            await bot.banners.accept({'channel_id':str(BANNER_CHANNEL_ID),'message_id':'123456789012345678',
                'created_at':time.time(),'images':[f'https://cdn.discordapp.com/attachments/1/{n}/image.png' for n in range(3)]})
            while True:
                await bot.banners.cycle()
                await bot.banners.votes.cycle()
                left=bot.store.connection.execute("SELECT count(*) FROM banner_image_receipts WHERE state<>'sent' OR reactions<>7").fetchone()[0]
                done=bot.store.connection.execute("SELECT count(*) FROM banner_jobs WHERE state='sent'").fetchone()[0]
                if done==guilds and left==0:
                    break
                if time.perf_counter()-start>60:
                    raise TimeoutError('The synthetic drill exceeded its bounded runtime.')
                await asyncio.sleep(.01)
            return {'guilds':guilds,'images_per_rotation':3,'simulated_api_delay_ms':delay_ms,
                'image_posts':sent,'reaction_requests':reactions,'elapsed_ms':round((time.perf_counter()-start)*1000),
                'database_mib':round(bot.store.path.stat().st_size/1048576,2),
                'process_peak_mib_without_source_reader':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
                'external_network':False,'production_capacity_guarantee':False}
        finally:
            await bot.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guilds',type=int,default=50)
    parser.add_argument('--delay-ms',type=int,default=5)
    args=parser.parse_args()
    print(json.dumps(asyncio.run(benchmark(args.guilds,args.delay_ms)),indent=2))
