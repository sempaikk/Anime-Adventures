"""Reproduce the production RSS stall without network or real Discord data."""

import asyncio
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image

from banner_relay import BannerRelay
from feed_memory import receive_memory
from feed_receiver import FeedReceiver
from game_sources import DAILY_CHANNEL_ID
from instance_storage import ResourceBudgetError
import test_banners as fixtures

MIB = 1024 * 1024


class Response:
    status = 200

    def __init__(self, length, stream):
        self.content_length = length
        self.content = SimpleNamespace(iter_chunked=stream)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FeedMemoryCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.BannerCase.asyncSetUp
    asyncTearDown = fixtures.BannerCase.asyncTearDown
    add_channel = fixtures.BannerCase.add_channel
    send = fixtures.BannerCase.send
    event = fixtures.BannerCase.event

    async def receive(self, *events):
        receiver = FeedReceiver(self.app)
        receiver.start()
        try:
            for event in events:
                receiver.handle({'event': 'image', **event})
            await asyncio.wait_for(asyncio.gather(*(q.join() for q in receiver.queues.values())), 3)
        finally:
            await receiver.close()

    def response(self, length, stream):
        self.relay.session = SimpleNamespace(get=lambda *a, **kw: Response(length, stream), close=AsyncMock())
        self.relay.download = BannerRelay.download.__get__(self.relay)

    async def test_203_mib_accepts_and_delivers_real_1080p_banner_that_fixed_reservation_rejected(self):
        budget = self.app.instance_storage
        out = io.BytesIO()
        Image.new('RGB', (1920, 1080), 'navy').save(out, format='PNG')
        blob = out.getvalue()
        async def stream(size):
            self.assertGreaterEqual(budget.reserved_memory, 2 * len(blob))
            yield blob
        self.response(len(blob), stream)
        self.relay.configure(1, 10)
        self.relay.configure(2, 20)
        with patch('instance_storage.process_memory', return_value=203 * MIB):
            with self.assertRaises(ResourceBudgetError):
                async with budget.reserve(32 * MIB, memory=32 * MIB):
                    self.fail('The old fixed reservation must reproduce the stall')
            await self.receive(self.event())
            self.assertEqual(self.relay.diagnostics.snapshot()['received_source'], self.event()['message_id'])
            await self.relay.cycle()
        self.assertEqual({item['channel'] for item in self.sent}, {10, 20})
        self.assertTrue(all(item['files'][0]['blob'] == blob for item in self.sent))
        self.assertEqual((budget.reserved, budget.reserved_memory), (0, 0))

    async def test_both_feeds_can_receive_concurrently_at_production_rss(self):
        daily = self.app.daily
        daily.clock = lambda: self.now
        daily.download = AsyncMock(return_value=self.blob)
        daily.configure(2, 20)
        self.relay.configure(1, 10)
        entered, release = asyncio.Event(), asyncio.Event()
        async def wait_then_download(*args):
            entered.set()
            await release.wait()
            return self.blob
        self.relay.download.side_effect = wait_then_download
        task = asyncio.create_task(self.receive(self.event(), self.event(
            channel_id=str(DAILY_CHANNEL_ID), message_id='200')))
        try:
            with patch('instance_storage.process_memory', return_value=203 * MIB):
                await asyncio.wait_for(entered.wait(), 1)
                release.set()
                await task
                await asyncio.gather(self.relay.cycle(), daily.cycle())
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual({item['channel'] for item in self.sent}, {10, 20})
        self.assertEqual(self.app.instance_storage.reserved_memory, 0)

    async def test_memory_pressure_still_blocks_decode_and_retry_repairs_current_image_once(self):
        self.relay.configure(1, 10)
        event = self.event(message_id='200')
        with patch('instance_storage.process_memory', return_value=int(229.8 * MIB)):
            await self.receive(event)
        state = self.relay.diagnostics.snapshot()
        self.assertEqual(state['error'], 'receive_memory_budget')
        self.assertEqual(state['received'], 0)
        self.assertEqual(state['pending'], 0)
        self.assertEqual(self.app.instance_storage.reserved_memory, 0)
        self.now += 121
        self.relay.status = 'ready'
        self.relay.diagnostics.poll()
        self.assertEqual(self.relay.diagnostics.snapshot()['error'], 'receive_memory_budget')
        self.assertFalse(self.relay.alert_conditions()['banner_source'][0])
        self.assertTrue(self.relay.alert_conditions()['banner_receive'][0])
        self.assertIn('waiting for available memory', self.relay.private_status(1))
        with patch('instance_storage.process_memory', return_value=203 * MIB):
            await self.receive(event)
            await self.relay.cycle()
            await self.receive(event)
            await self.relay.cycle()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.relay.diagnostics.snapshot()['error'], '')
        self.assertEqual(self.app.instance_storage.reserved_memory, 0)

    async def test_old_cached_receipt_cannot_hide_newer_receive_failure(self):
        await self.receive(self.event(message_id='100'))
        self.relay.diagnostics.observe('200', self.now + 1)
        self.relay.diagnostics.error('receive_memory_budget')
        await self.receive(self.event(message_id='100'))
        self.relay.diagnostics.poll()
        state = self.relay.diagnostics.snapshot()
        self.assertEqual((state['source_message'], state['received_source']), ('200', '100'))
        self.assertEqual(state['error'], 'receive_memory_budget')
        with self.relay.db:
            self.relay.diagnostics.received(message_id='200', created=self.now + 1)
        self.assertEqual(self.relay.diagnostics.snapshot()['error'], '')

    async def test_known_unknown_and_underreported_lengths_reserve_real_buffer_until_commit(self):
        budget = self.app.instance_storage
        for length in (len(self.blob), None, 1):
            with self.subTest(length=length):
                async def stream(size):
                    self.assertGreater(budget.reserved_memory, 0)
                    yield self.blob[:40]
                    yield self.blob[40:]
                self.response(length, stream)
                with patch('instance_storage.process_memory', return_value=203 * MIB):
                    async with receive_memory(budget):
                        result = await self.relay.download(self.event()['images'][0], 8 * MIB)
                        self.assertEqual(result, self.blob)
                        self.assertGreaterEqual(budget.reserved_memory, 2 * len(result) + 128 * 1024)
                self.assertEqual(budget.reserved_memory, 0)

    async def test_known_large_buffer_is_rejected_before_body_read_and_limits_remain_enforced(self):
        calls = []
        async def stream(size):
            calls.append(True)
            yield self.blob
        self.response(8 * MIB, stream)
        with patch('instance_storage.process_memory', return_value=220 * MIB):
            with self.assertRaises(ResourceBudgetError):
                await self.relay.download(self.event()['images'][0], 8 * MIB)
        self.assertEqual(calls, [])
        self.response(8 * MIB + 1, stream)
        with self.assertRaises(ValueError):
            await self.relay.download(self.event()['images'][0], 8 * MIB)
        self.assertEqual(calls, [])
        self.response(None, stream)
        with self.assertRaises(ValueError):
            await self.relay.download(self.event()['images'][0], 1)
        self.assertEqual(self.app.instance_storage.reserved_memory, 0)

    async def test_cancelled_stream_releases_all_reservations_and_leaves_no_delivery(self):
        started = asyncio.Event()
        async def stream(size):
            yield self.blob[:40]
            started.set()
            await asyncio.Event().wait()
        self.response(None, stream)
        task = asyncio.create_task(self.relay.accept(self.event()))
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.assertGreater(self.app.instance_storage.reserved_memory, 0)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.app.instance_storage.reserved_memory, 0)
        self.assertEqual(self.relay.diagnostics.snapshot()['pending'], 0)

    async def test_source_poll_clears_source_errors_but_preserves_receive_errors(self):
        for reason in ('receive_memory_budget', 'receive_disk_budget', 'partial_reception', 'download_or_validation_failed'):
            self.relay.diagnostics.error(reason)
            self.relay.diagnostics.poll()
            self.assertEqual(self.relay.diagnostics.snapshot()['error'], reason)
        self.relay.diagnostics.error('source_unavailable')
        self.relay.diagnostics.poll()
        self.assertEqual(self.relay.diagnostics.snapshot()['error'], '')

    async def test_owner_alert_distinguishes_memory_reception_from_source_outage(self):
        self.app.store.clock = lambda: self.now
        ops = self.app.globalchat.operations
        ops.notify = AsyncMock(return_value=True)
        self.relay.configure(1, 10)
        self.relay.status = 'ready'
        self.relay.diagnostics.observe('200', self.now)
        self.relay.diagnostics.error('receive_memory_budget')
        self.now += 121
        self.relay.diagnostics.poll()
        await ops.check_alerts()
        self.now += 121
        self.relay.diagnostics.poll()
        await ops.check_alerts()
        messages = [call.args[0] for call in ops.notify.await_args_list]
        self.assertTrue(any('Source checks succeeded' in text and 'available memory' in text for text in messages))
        self.assertFalse(any('upstream source outage' in text for text in messages))
