"""Inline forwarded images use the existing private receive/delivery pipeline."""

import asyncio
from datetime import datetime, timezone
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from banner_reader import image_message, listen
from game_sources import BANNER_CHANNEL_ID, DAILY_CHANNEL_ID, IMAGE_SOURCE_CHANNELS
from test_banner_images import colored
import test_banners as feeds
import test_banner_votes as votes


def attachment(name, ident=1, mime='image/png'):
    return {'id':str(ident),'filename':name,'size':100,'content_type':mime,
            'url':f'https://cdn.discordapp.com/attachments/999/{ident}/{name}',
            'proxy_url':f'https://media.discordapp.net/attachments/999/{ident}/{name}'}


def snapshot(files=(), embeds=()):
    return discord.MessageSnapshot(state=SimpleNamespace(http=None), data={
        'type':0,'content':'PRIVATE_FORWARDED_TEXT <@123456789012345678>',
        'attachments':list(files),'embeds':list(embeds),'timestamp':'2025-01-01T00:00:00+00:00',
        'edited_timestamp':None,'flags':0})


def source_message(now, *, ident=200, channel=BANNER_CHANNEL_ID, snapshots=(), files=()):
    return SimpleNamespace(id=ident,channel=SimpleNamespace(id=channel),
        created_at=datetime.fromtimestamp(now,timezone.utc),edited_at=None,
        content='PRIVATE_SOURCE_TEXT thanks <@123456789012345678>',
        attachments=list(files),embeds=[],message_snapshots=list(snapshots))


class ForwardImageCase(unittest.TestCase):
    def test_sdk_snapshot_extracts_only_images_with_outer_source_identity_and_time(self):
        raw=attachment('banner.png')
        image=snapshot([raw],[{'image':{'url':raw['url']}}])
        message=source_message(2_000_000_000,snapshots=[image])
        message.edited_at=datetime.fromtimestamp(2_000_000_060,timezone.utc)
        event=image_message(message,IMAGE_SOURCE_CHANNELS)
        self.assertEqual(event,{'event':'image','channel_id':str(BANNER_CHANNEL_ID),
            'message_id':'200','created_at':2_000_000_060,'published_at':2_000_000_000,
            'images':[raw['url']]})
        self.assertNotIn('PRIVATE',json.dumps(event))
        self.assertNotIn('999',event['channel_id'])

    def test_forwarded_embeds_use_image_proxy_without_text_video_or_link_preview(self):
        proxy='https://images-ext-1.discordapp.net/external/synthetic/banner.png'
        image=snapshot([attachment('clip.mp4',mime='video/mp4'),attachment('moving.gif',mime='image/gif')],
            [{'image':{'url':'https://example.invalid/banner.png','proxy_url':proxy}},
             {'type':'video','thumbnail':{'url':'https://example.invalid/video-preview.png'}}])
        event=image_message(source_message(2_000_000_000,snapshots=[image]),IMAGE_SOURCE_CHANNELS)
        self.assertEqual(event['images'],[proxy])

    def test_other_channels_and_normal_reply_references_are_not_followed(self):
        image=snapshot([attachment('banner.png')])
        self.assertIsNone(image_message(source_message(2_000_000_000,channel=999,snapshots=[image]),IMAGE_SOURCE_CHANNELS))
        message=source_message(2_000_000_000)
        message.reference=SimpleNamespace(resolved=source_message(2_000_000_000,snapshots=[image]))
        self.assertIsNone(image_message(message,IMAGE_SOURCE_CHANNELS))
        self.assertIsNone(image_message(source_message(2_000_000_000,snapshots=[snapshot()]),IMAGE_SOURCE_CHANNELS))

    def test_direct_and_forwarded_images_share_the_existing_ten_image_limit(self):
        files=[attachment(f'image-{n}.png',n+1) for n in range(12)]
        message=source_message(2_000_000_000,files=[SimpleNamespace(**files[0])],snapshots=[snapshot(files)])
        event=image_message(message,IMAGE_SOURCE_CHANNELS)
        self.assertEqual(event['images'],[f['url'] for f in files[:10]])


class ForwardDeliveryCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=votes.BannerVoteCase.asyncSetUp
    asyncTearDown=votes.BannerVoteCase.asyncTearDown
    add_channel=votes.BannerVoteCase.add_channel
    send=votes.BannerVoteCase.send
    event=votes.BannerVoteCase.event
    emoji=votes.BannerVoteCase.emoji
    message=votes.BannerVoteCase.message

    async def test_native_history_recovers_two_forwarded_images_in_each_configured_server(self):
        self.app.store.clock=lambda:self.now
        self.relay.configure(2,20)
        raw=[attachment('rate.png',1),attachment('legacy.png',2)]
        blobs={raw[0]['url']:colored('red'),raw[1]['url']:colored('blue')}
        self.relay.download=AsyncMock(side_effect=lambda url,limit:blobs[url])
        forwarded=source_message(self.now,snapshots=[snapshot(raw)])
        source=self.add_channel(99,BANNER_CHANNEL_ID)
        forwarded.channel=source
        source.history.side_effect=lambda **kw:feeds.iterate([forwarded])
        self.app.banners.start=MagicMock()
        await self.app.native_sources.poll()
        queue=self.app.native_sources.receiver.queues[str(BANNER_CHANNEL_ID)]
        await asyncio.wait_for(queue.join(),1)
        await self.relay.cycle()
        self.assertEqual(len(self.sent),4)
        for channel in (10,20):
            delivered=[item for item in self.sent if item['channel']==channel]
            self.assertEqual([item['files'][0]['blob'] for item in delivered],list(blobs.values()))
            self.assertTrue(all(len(item['files'])==1 for item in delivered))
        for item in self.sent:
            self.assertFalse(set(item['payload'])&{'content','embeds','message_reference','message_snapshots'})
            self.assertTrue(item['payload']['enforce_nonce'])
        for _ in range(3):await self.votes.cycle()
        self.assertEqual(len(self.reaction_calls),12)
        self.assertEqual([e.name for e in self.votes.emojis],['win','mid','lose'])
        self.assertTrue(self.app.native_sources.event(forwarded))
        await self.app.native_sources.poll()
        await asyncio.wait_for(queue.join(),1)
        await self.relay.cycle()
        self.assertEqual(len(self.sent),4)
        self.assertEqual(self.relay.download.await_count,2)
        normal=source_message(self.now+1,ident=201,files=[SimpleNamespace(**attachment('normal.png',3))])
        self.relay.download=AsyncMock(return_value=colored('green'))
        self.assertTrue(await self.relay.accept(image_message(normal,IMAGE_SOURCE_CHANNELS)))
        await self.relay.cycle()
        self.assertEqual(len(self.sent),6)
        self.assertTrue(all(item['files'][0]['blob']==colored('green') for item in self.sent[-2:]))

    async def test_forward_receipt_survives_restart_and_does_not_resend_images(self):
        self.app.store.clock=lambda:self.now
        forwarded=source_message(self.now,snapshots=[snapshot([attachment('banner.png')])])
        event=image_message(forwarded,IMAGE_SOURCE_CHANNELS)
        self.assertTrue(await self.relay.accept(event))
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)
        await self.app.close()
        from community_bot import CommunityBot
        self.app=CommunityBot(self.temp.name)
        self.relay=self.app.banners
        self.relay.clock=lambda:self.now
        self.relay.download=AsyncMock(side_effect=AssertionError('Persisted receipt must skip download'))
        self.assertFalse(await self.relay.accept(event))
        self.relay.download.assert_not_awaited()
        self.assertEqual(self.relay.target(1)['channel_id'],'10')

    async def test_forward_publication_age_and_retraction_use_the_outer_post(self):
        old=source_message(self.now-4000,snapshots=[snapshot([attachment('banner.png')])])
        self.assertFalse(await self.relay.accept(image_message(old,IMAGE_SOURCE_CHANNELS)))
        self.relay.download.assert_not_awaited()
        current=source_message(self.now,snapshots=old.message_snapshots)
        event=image_message(current,IMAGE_SOURCE_CHANNELS)
        self.assertTrue(await self.relay.accept(event))
        self.relay.diagnostics.retract(str(current.id))
        await self.relay.cycle()
        self.assertFalse(self.sent)


class ForwardReaderRecoveryCase(unittest.IsolatedAsyncioTestCase):
    async def test_poll_and_gateway_share_receipts_and_latest_daily_stops_history_fallback(self):
        now=datetime.now(timezone.utc).timestamp()
        events=[]
        forwarded=source_message(now-60,snapshots=[snapshot([attachment('forwarded.png')])])
        normal=source_message(now,ident=201,files=[SimpleNamespace(**attachment('normal.png',2))])
        daily=source_message(now,ident=300,channel=DAILY_CHANNEL_ID,snapshots=[snapshot([attachment('daily.png',3)])])
        yesterday=source_message(now-86400,ident=299,channel=DAILY_CHANNEL_ID,files=[SimpleNamespace(**attachment('yesterday.png',4))])
        class Channel:
            def __init__(self,ident):
                self.id=ident
                self.guild=SimpleNamespace(subscribe=AsyncMock())
            def history(self,**kwargs):
                return feeds.iterate([normal,forwarded] if self.id==BANNER_CHANNEL_ID else [daily,yesterday])
        channels={ident:Channel(ident) for ident in IMAGE_SOURCE_CHANNELS}
        class Client:
            def __init__(self,**kwargs):pass
            def get_channel(self,ident):return channels[ident]
            async def start(self,token):
                await self.on_ready()
                await self.on_message(forwarded)
                await self.on_ready()
            async def close(self):pass
        fake=SimpleNamespace(Client=Client,TextChannel=Channel,
            CaptchaRequired=type('CaptchaRequired',(Exception,),{}),LoginFailure=type('LoginFailure',(Exception,),{}))
        with patch.dict(sys.modules,{'discord':fake}),patch('banner_reader.emit',side_effect=lambda event,**values:events.append({'event':event,**values})):
            self.assertEqual(await listen({'token':'synthetic-only','source_channel_ids':IMAGE_SOURCE_CHANNELS,
                'daily_channel_id':DAILY_CHANNEL_ID}),0)
        images=[e for e in events if e['event']=='image']
        self.assertEqual([e['message_id'] for e in images if e['channel_id']==str(BANNER_CHANNEL_ID)],['200','201'])
        self.assertEqual([e['message_id'] for e in images if e['channel_id']==str(DAILY_CHANNEL_ID)],['300'])
        self.assertNotIn('PRIVATE',json.dumps(events))
