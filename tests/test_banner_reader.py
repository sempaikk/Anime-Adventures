"""Image-only live reader: subscriptions, polling, source status and retirement."""

import asyncio
from datetime import datetime,timezone
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from banner_reader import ImageTracker,listen
from community_bot import CommunityBot
from game_sources import IMAGE_SOURCE_CHANNELS,BANNER_CHANNEL_ID,DAILY_CHANNEL_ID


class ReaderImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_guild_subscription_is_enabled_and_poll_recovers_missed_image(self):
        events=[];histories=[];clients=[];subscriptions=[];messages={ident:[] for ident in IMAGE_SOURCE_CHANNELS}
        class Channel:
            def __init__(self,ident):
                self.id=ident
                async def subscribe(**kwargs):subscriptions.append(kwargs)
                self.guild=SimpleNamespace(subscribe=subscribe)
            def history(self,**kwargs):
                histories.append(self.id)
                async def items():
                    for value in messages[self.id]:yield value
                return items()
        channels={ident:Channel(ident) for ident in IMAGE_SOURCE_CHANNELS}
        message=SimpleNamespace(id=123,channel=channels[BANNER_CHANNEL_ID],created_at=datetime.now(timezone.utc),edited_at=None,
            attachments=[SimpleNamespace(filename='banner.png',content_type='image/png',url='https://cdn.discordapp.com/attachments/1/2/banner.png')],embeds=[])
        class Client:
            def __init__(self,**kwargs):clients.append(self)
            def get_channel(self,ident):return channels[ident]
            async def start(self,token):
                await self.on_ready()
                await asyncio.gather(self.image_poll,return_exceptions=True)
            async def close(self):pass
        sleeps=0
        async def tick(delay):
            nonlocal sleeps
            self.assertEqual(delay,30)
            sleeps+=1
            if sleeps==1:messages[BANNER_CHANNEL_ID]=[message]
            else:raise asyncio.CancelledError()
        fake=SimpleNamespace(Client=Client,TextChannel=Channel,CaptchaRequired=type('CaptchaRequired',(Exception,),{}),LoginFailure=type('LoginFailure',(Exception,),{}))
        with patch.dict(sys.modules,{'discord':fake}),patch('banner_reader.emit',side_effect=lambda event,**values:events.append({'event':event,**values})),patch('banner_reader.asyncio.sleep',side_effect=tick):
            result=await listen({'token':'synthetic-only','source_channel_ids':IMAGE_SOURCE_CHANNELS,'daily_channel_id':DAILY_CHANNEL_ID,'questions_enabled':False})
        self.assertEqual(result,0)
        self.assertTrue(subscriptions)
        self.assertTrue(all(s['typing'] is True and s['member_updates'] is False for s in subscriptions))
        self.assertEqual({e['channel_id'] for e in events if e['event']=='image'},{str(BANNER_CHANNEL_ID)})
        self.assertEqual(set(histories),set(IMAGE_SOURCE_CHANNELS))
        self.assertFalse(any(e['event'].startswith('question') for e in events))
        self.assertEqual(len([e for e in events if e['event']=='image']),1)

    async def test_retired_ask_ignores_old_pc_environment_and_does_not_open_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'knowledge.sqlite3';source.write_bytes(b'preserve retired archive')
            with patch.dict('os.environ',{'KNOWLEDGE_MODE':'pc','KNOWLEDGE_BRIDGE_SECRET':'synthetic-old-secret-more-than-32-characters'}):
                app=CommunityBot(folder)
            try:
                self.assertTrue(app.knowledge.disabled)
                self.assertIsNone(app.tree.get_command('ask'))
                self.assertEqual({c.name for c in app.tree.get_commands()},{'setbanner','dailychallenge','globalchat'})
                self.assertIsNone(getattr(app.knowledge,'install_routes',None))
                self.assertEqual(source.read_bytes(),b'preserve retired archive')
            finally:await app.close()


class ImageTrackerTests(unittest.TestCase):
    def test_live_and_polled_duplicates_and_renewed_cdn_signatures_are_not_reemitted(self):
        tracker=ImageTracker()
        payload={'channel_id':'1','message_id':'2','created_at':123,'images':['https://cdn.discordapp.com/attachments/1/2/a.png?ex=old']}
        self.assertTrue(tracker.new(payload))
        self.assertFalse(tracker.new({**payload,'images':['https://cdn.discordapp.com/attachments/1/2/a.png?ex=new']}))
        self.assertTrue(tracker.new({**payload,'created_at':124}))
        for n in range(300):tracker.new({**payload,'message_id':str(n)})
        self.assertEqual(len(tracker.seen),256)
