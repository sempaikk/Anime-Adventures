"""Simulated account API only: source scope, catch-up order and buffered arrivals."""

from datetime import datetime,timezone
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from banner_reader import listen
from game_sources import SOURCE_CHANNELS,QUESTIONS_CHANNEL_ID,DAILY_CHANNEL_ID


class RecoveryCase(unittest.IsolatedAsyncioTestCase):
    async def test_catchup_finishes_before_live_buffer_is_checkpointed(self):
        events=[];calls=[];channels={}
        class Message:
            def __init__(self,ident,channel,body='How do I get gems?'):
                self.id,self.channel,self.content=ident,channel,body
                self.author=SimpleNamespace(bot=False)
                self.webhook_id=None;self.reference=None;self.attachments=[];self.embeds=[]
                self.created_at=datetime.now(timezone.utc);self.edited_at=None
        class TextChannel:
            def __init__(self,ident):
                self.id=ident;self.guild=SimpleNamespace(subscribe=AsyncMock())
            def history(self,**kwargs):
                calls.append((self.id,kwargs))
                async def values():
                    if self.id==QUESTIONS_CHANNEL_ID:
                        yield Message(200,self)
                        await current[0].on_message(Message(400,self))
                        yield Message(300,self)
                return values()
        class Client:
            def __init__(self,**kwargs):current.append(self)
            def get_channel(self,ident):return channels[ident]
            async def start(self,token):
                self.asserted_token=token
                await self.on_ready()
            async def close(self):pass
        current=[]
        channels.update({ident:TextChannel(ident) for ident in SOURCE_CHANNELS})
        fake=SimpleNamespace(Client=Client,TextChannel=TextChannel,Message=Message,
                             Object=lambda **kw:SimpleNamespace(**kw),
                             utils=SimpleNamespace(time_snowflake=lambda *a,**kw:999),
                             CaptchaRequired=type('CaptchaRequired',(Exception,),{}),LoginFailure=type('LoginFailure',(Exception,),{}))
        with patch.dict(sys.modules,{'discord':fake}),patch('banner_reader.emit',side_effect=lambda event,**values:events.append({'event':event,**values})):
            result=await listen({'token':'synthetic-only','source_channel_ids':SOURCE_CHANNELS,
                                 'questions_channel_id':QUESTIONS_CHANNEL_ID,'daily_channel_id':DAILY_CHANNEL_ID,
                                 'question_after':'100'})
        self.assertEqual(result,0)
        self.assertEqual([e['message_id'] for e in events if e['event']=='question_checkpoint'],['200','300','400'])
        self.assertEqual([e['message_id'] for e in events if e['event']=='question'],['200','300','400'])
        kwargs=next(kw for ident,kw in calls if ident==QUESTIONS_CHANNEL_ID)
        self.assertEqual(kwargs['after'].id,100)
        self.assertTrue(kwargs['oldest_first'])
        self.assertIsNone(kwargs['limit'])
        self.assertEqual({ident for ident,_ in calls},set(SOURCE_CHANNELS))
        self.assertEqual(events[-1]['event'],'ready')
