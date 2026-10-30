"""Private regression journeys for derived global reply context and cleanup."""

import asyncio
from types import SimpleNamespace
import unittest

from bot_ui import visible_text
import test_global_chat as chats


class ReplyLifecycleCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=chats.ChatCase.asyncSetUp
    asyncTearDown=chats.ChatCase.asyncTearDown
    fetch=chats.ChatCase.fetch
    history=chats.ChatCase.history
    send_notice=chats.ChatCase.send_notice
    message=chats.ChatCase.message
    asset=chats.ChatCase.asset
    flush=chats.ChatCase.flush
    copies=chats.ChatCase.copies

    async def create_reply(self,files=False):
        source=self.message(content='Parent original quote')
        await self.engine.ingest(source);await self.flush()
        copy=next(m for m in self.copies(source) if m.channel.id==20)
        answer=self.message(self.channels[20],content='Reply author body',attachments=[self.asset('reply-image.png')] if files else None)
        answer.reference=SimpleNamespace(message_id=copy.id)
        await self.engine.ingest(answer);await self.flush()
        return source,answer

    async def test_parent_removal_updates_only_bot_injected_context(self):
        source,answer=await self.create_reply()
        self.engine.store.erase(source.id);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))
        self.assertIn(source.id,self.messages)
        self.assertEqual(answer.content,'Reply author body')

    async def test_parent_edit_updates_existing_quotes_without_new_copies(self):
        source,answer=await self.create_reply()
        before={m.id for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content}
        source.content='Parent edited quote'
        await self.engine.ingest(source);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual({m.id for m in replies},before)
        self.assertTrue(all('Parent edited quote' in m.content and 'Parent original quote' not in m.content for m in replies))

    async def test_reference_id_survives_restart_without_retaining_parent_text(self):
        source,answer=await self.create_reply()
        from global_store import GlobalStore
        recovered=GlobalStore(self.base)
        self.assertEqual(recovered.message(answer.id)['reply_id'],str(source.id))
        self.engine.store.erase(source.id)
        self.assertEqual(recovered.message(source.id)['payload'],'{}')

    async def test_context_removal_after_cache_expiry_and_author_leaving(self):
        source,answer=await self.create_reply()
        self.now[0]+=3601
        self.engine.store.cleanup()
        self.engine.store.consent(answer.author.id,False)
        self.assertEqual(self.engine.store.message(answer.id)['payload'],'{}')
        self.engine.store.erase(source.id)
        await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))

    async def test_context_refresh_does_not_strip_a_human_first_line(self):
        source,answer=await self.create_reply()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        for m in replies:m.content='> Changed by a separate action\nReply author body'
        self.engine.store.erase(source.id);await self.flush()
        self.assertTrue(all(m.content.startswith('> Changed by a separate action') for m in replies))

    async def test_old_context_cleanup_preserves_attachments_without_reuploading(self):
        source,answer=await self.create_reply(files=True)
        expected=self.blobs[answer.attachments[0].url]
        self.now[0]+=3601;self.engine.store.cleanup()
        self.engine.store.erase(source.id);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all(m.attachments[0].blob==expected and m.attachments[0].filename=='reply-image.png' for m in replies))
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))

    async def test_parent_removal_during_reply_ack_does_not_lose_cleanup(self):
        source=self.message(content='Parent original quote')
        await self.engine.ingest(source);await self.flush()
        copy=next(m for m in self.copies(source) if m.channel.id==20)
        answer=self.message(self.channels[20],content='Reply author body')
        answer.reference=SimpleNamespace(message_id=copy.id)
        original=self.hooks[110].send
        async def withdraw(*args,**kwargs):
            sent=await original(*args,**kwargs)
            self.engine.store.erase(source.id)
            return sent
        self.hooks[110].send=withdraw
        await self.engine.ingest(answer);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))

    async def test_cleanup_uses_reserved_capacity_while_regular_sends_stall(self):
        for gid in (4,5,6):self.engine.store.configure(gid,gid*10,gid*10+100,'synthetic',0)
        regular=self.message(content='New normal publication')
        await self.engine.ingest(regular)
        # Keep a distinct destination available for a previous-copy removal.
        with self.base.connection:
            self.base.connection.execute("UPDATE global_deliveries SET state='cancelled' WHERE source_id=? AND channel_id='60'",(str(regular.id),))
        await self.engine.ingest(self.message(content='Previous removal fixture'))
        old=self.engine.store.one('SELECT id FROM global_messages WHERE id<>? ORDER BY created DESC,rowid DESC LIMIT 1',(str(regular.id),))
        with self.base.connection:
            self.base.connection.execute("UPDATE global_deliveries SET state='sent',receipts='[\"9999\"]' WHERE source_id=? AND channel_id='60'",(old['id'],))
            self.base.connection.execute("UPDATE global_deliveries SET state='cancelled' WHERE source_id=? AND channel_id<>'60'",(old['id'],))
        release,removed=asyncio.Event(),asyncio.Event()
        started=[]
        async def deliver(job):
            row=self.engine.store.message(job['source_id'])
            if row['deleted']:
                removed.set();return
            started.append(job['channel_id']);await release.wait()
        self.engine.deliver=deliver
        self.engine.last_recovery=self.engine.store.clock()
        await self.engine.cycle()
        self.assertEqual(len(started),3)
        self.engine.store.erase(old['id'])
        await self.engine.cycle()
        await asyncio.wait_for(removed.wait(),.3)
        self.assertEqual(len(started),3)
        release.set()

    async def test_sharing_preview_neither_joins_nor_creates_network_copies(self):
        from global_views import ConsentView
        i=chats.ChatCase.interaction(self)
        self.engine.store.consent(7,False)
        before=set(self.messages)
        view=ConsentView(self.app,i,self.engine.store.channel(1))
        await view.preview.callback(i)
        self.assertFalse(self.engine.store.consented(7))
        self.assertEqual(set(self.messages),before)
        self.assertIn('Private sharing preview',visible_text(i.response.send_message.call_args.kwargs['view'].to_components()))

