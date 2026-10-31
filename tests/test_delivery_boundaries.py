"""Crash, revision and resource boundaries, using synthetic sources and private DBs."""
import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from resource_jobs import joined_thread
from feed_receiver import FeedReceiver
from feed_memory import receive_memory
from feed_history import recent_attempts
from operations_views import diagnostic_text
import test_banners as banners
import test_global_chat as chat


class FeedBoundaries(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=banners.BannerCase.asyncSetUp
    asyncTearDown=banners.BannerCase.asyncTearDown
    add_channel=banners.BannerCase.add_channel
    send=banners.BannerCase.send
    event=banners.BannerCase.event
    jobs=banners.BannerCase.jobs
    interaction=banners.BannerCase.interaction

    async def test_member_preview_uses_current_source_identity_and_the_same_freshness_gate(self):
        from unittest.mock import MagicMock
        import discord
        from feed_views import preview
        self.relay.configure(1,10)
        await self.relay.accept(self.event(message_id='200'))
        await self.relay.accept(self.event(message_id='100',created_at=self.now+10))
        self.relay.status='ready'
        i=self.interaction()
        i.user=MagicMock(spec=discord.Member,id=7)
        with patch('feed_views.send_preview',new_callable=AsyncMock) as send:
            await preview(self.relay,i)
            send.assert_not_awaited()
            self.relay.diagnostics.poll()
            await preview(self.relay,i)
            self.assertEqual(send.call_args.args[2]['source_message'],'200')

    async def test_auxiliary_application_failure_does_not_prevent_existing_workers_starting(self):
        loop=SimpleNamespace(start=AsyncMock(),get_task=lambda:None,cancel=lambda:None)
        # The service-loop start is synchronous in discord.ext.tasks.
        from unittest.mock import MagicMock
        loop.start=MagicMock()
        self.app.refresh_application=AsyncMock(side_effect=TimeoutError())
        self.app.health.start=AsyncMock()
        self.app.add_view=MagicMock()
        self.app.service_loops=lambda:(loop,)
        self.app.banners.start=MagicMock()
        self.app.sync_commands=AsyncMock()
        await self.app.setup_hook()
        await self.app.command_sync_task
        loop.start.assert_called_once()
        self.assertEqual(self.app.owner_ids_set,set())
        self.assertTrue(self.app.daily.require_source_confirmation)

    async def test_duplicate_queue_events_leave_room_for_a_new_source(self):
        receiver=FeedReceiver(self.app)
        for _ in range(100): receiver.handle({'event':'image',**self.event()})
        receiver.handle({'event':'image',**self.event(message_id='123456789012345679')})
        self.assertEqual(receiver.queues[self.event()['channel_id']].qsize(),2)

    async def test_current_revision_blocks_old_upload_before_new_bytes_arrive(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        job=dict(self.jobs()[0])
        self.assertTrue(self.relay.current_job(job))
        self.relay.diagnostics.observe(self.event()['message_id'],self.now+1)
        self.assertFalse(self.relay.current_job(job))
        await self.relay.cycle()
        self.assertEqual(self.sent,[])

    async def test_pending_incident_clock_does_not_restart_for_each_new_revision(self):
        self.relay.configure(1,10)
        self.relay.status='ready'
        for index in range(4):
            self.relay.diagnostics.observe(self.event()['message_id'],self.now)
            self.relay.diagnostics.error('receive_memory_budget')
            self.now+=60
        self.assertTrue(self.relay.diagnostics.waiting())
        self.assertTrue(self.relay.alert_conditions()['banner_receive'][0])
        self.assertIn('receive_memory_budget',diagnostic_text(self.app,1))

    async def test_saved_receipt_does_not_refresh_the_byte_verification_timestamp(self):
        await self.relay.accept(self.event())
        verified=self.relay.diagnostics.snapshot()['received']
        self.now+=60
        await self.relay.accept(self.event(created_at=self.now-60))
        state=self.relay.diagnostics.snapshot()
        self.assertEqual(state['received'],verified)
        self.assertEqual(state['checked_receipt'],self.now)

    async def test_attempt_deadline_retains_valid_banner_parts_without_confirming_source(self):
        self.relay.configure(1,10)
        calls=0
        async def download(*args):
            nonlocal calls
            calls+=1
            if calls==1:return self.blob
            await asyncio.Event().wait()
        self.relay.download.side_effect=download
        event=self.event(images=[self.event()['images'][0],'https://cdn.discordapp.com/attachments/1/2/next.png'])
        with self.assertRaises(TimeoutError):await asyncio.wait_for(self.relay.accept(event),.03)
        self.assertEqual(len(self.jobs()),1)
        self.assertEqual(self.relay.diagnostics.snapshot()['received'],0)
        self.assertEqual(self.relay.query('SELECT count(*) FROM banner_source_receipts').fetchone()[0],0)
        await self.relay.cycle()
        self.assertEqual(len(self.sent),1)

    async def test_cancelled_validation_keeps_memory_lease_until_thread_finishes(self):
        started,release=threading.Event(),threading.Event()
        budget=self.app.instance_storage
        def decode():started.set();release.wait(2);return 1
        async def run():
            async with receive_memory(budget) as memory:
                await memory.reserve(1024)
                return await joined_thread(decode)
        task=asyncio.create_task(run())
        try:
            await asyncio.to_thread(started.wait,1)
            task.cancel();await asyncio.sleep(.01)
            self.assertFalse(task.done())
            self.assertGreater(budget.reserved_memory,0)
        finally:
            release.set()
            result=await asyncio.gather(task,return_exceptions=True)
        self.assertIsInstance(result[0],asyncio.CancelledError)
        self.assertEqual(budget.reserved_memory,0)

    async def test_reconciliation_cursor_survives_recreation_and_reaches_beyond_300(self):
        rows=[SimpleNamespace(id=1000+i) for i in range(401)]
        async def history(**kwargs):
            cursor=getattr(kwargs['after'],'id',0)
            for message in [m for m in rows if m.id>cursor][:kwargs['limit']]:yield message
        channel=SimpleNamespace(history=history)
        seen=[]
        for _ in range(5):
            seen.extend([m.id async for m in recent_attempts(channel,self.now,store=self.relay.db,key='synthetic-uncertain')])
        self.assertEqual(seen,list(range(1000,1401)))


class GlobalBoundaries(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=chat.ChatCase.asyncSetUp
    asyncTearDown=chat.ChatCase.asyncTearDown
    fetch=chat.ChatCase.fetch
    history=chat.ChatCase.history
    send_notice=chat.ChatCase.send_notice
    message=chat.ChatCase.message
    copies=chat.ChatCase.copies
    asset=chat.ChatCase.asset

    async def test_recent_cycle_is_not_healthy_when_due_work_has_stopped_progressing(self):
        source=self.message(self.channels[10],'Synthetic stalled queue')
        await self.engine.ingest(source)
        self.now[0]+=301
        self.engine.last_cycle=self.now[0]
        self.assertFalse(self.engine.ready())

    async def test_unexpected_exception_after_post_reconciles_without_duplicate(self):
        source=self.message(self.channels[10],'Synthetic boundary')
        await self.engine.ingest(source)
        hook=self.hooks[120];original=hook.send
        async def uncertain(*a,**kw):
            await original(*a,**kw)
            raise RuntimeError('synthetic after post')
        hook.send=uncertain
        await self.engine.cycle()
        await asyncio.gather(*self.engine.deliveries.values())
        row=self.engine.store.delivery(source.id,20)
        self.assertEqual(row['state'],'uncertain')
        self.assertEqual(len([m for m in self.copies(source) if m.channel.id==20]),1)
        hook.send=original;self.now[0]+=120
        for _ in range(3):
            await self.engine.cycle();await asyncio.gather(*self.engine.deliveries.values())
        self.assertEqual(self.engine.store.delivery(source.id,20)['state'],'sent')
        self.assertEqual(len([m for m in self.copies(source) if m.channel.id==20]),1)

    async def test_transient_preparation_retries_the_same_fingerprint(self):
        source=self.message(self.channels[10],'Synthetic attachment',attachments=[self.asset()])
        original=self.engine.media.download
        self.engine.media.download=AsyncMock(side_effect=TimeoutError())
        await self.engine.ingest(source)
        self.assertEqual(self.engine.store.delivery(source.id,20)['state'],'preparing')
        self.now[0]+=301;self.engine.media.download=original
        await self.engine.ingest(source,recovery=True)
        self.assertEqual(self.engine.store.delivery(source.id,20)['state'],'queued')

    async def test_nested_ingest_does_not_remove_the_recovery_owner_task(self):
        source=self.message(self.channels[10],'Synthetic ownership')
        current=asyncio.current_task();self.engine.tasks.add(current)
        await self.engine.ingest(source,recovery=True)
        self.assertIn(current,self.engine.tasks)
        self.assertNotIn(current,self.engine.ingests)
        self.engine.tasks.discard(current)
