"""Two bounded receive workers: a slow source never blocks the other feed's pipe."""

import asyncio
import logging
import hashlib
import json

from game_sources import BANNER_CHANNEL_ID, DAILY_CHANNEL_ID
from feed_contracts import source_image, receive_reason
from runtime_limits import RECEIVE_QUEUE, RECEIVE_TIMEOUT

log = logging.getLogger('adventures.receiver')


class FeedReceiver:
    def __init__(self, bot, *, primary=False):
        self.bot = bot
        self.primary=primary
        self.feeds = {str(BANNER_CHANNEL_ID): bot.banners, str(DAILY_CHANNEL_ID): bot.daily}
        self.queues = {key: asyncio.Queue(maxsize=RECEIVE_QUEUE) for key in self.feeds}
        self.pending = {key: {} for key in self.feeds}
        self.active = {}
        self.retry_after = {}
        self.tasks = []

    def start(self):
        if self.tasks:
            return
        self.tasks = [asyncio.create_task(self.worker(key), name='receive-'+feed.kind)
                      for key, feed in self.feeds.items()]

    def handle(self, event):
        feed = self.feeds.get(str(event.get('channel_id', '')))
        kind = event.get('event')
        if feed is None:
            if kind in {'installing','connecting','login_failed','account_action_required','reader_failed','ready'}:
                for item in self.feeds.values():
                    if bool(getattr(item,'native',False))==self.primary:
                        item.status = kind
            return
        if bool(getattr(feed,'native',False))!=self.primary:
            return
        if kind == 'image':
            try:
                event = source_image(event)
            except (ValueError, TypeError, OverflowError):
                return
            message, created = event['message_id'], event['created_at']
            if not feed.clock()-feed.max_age < created <= feed.clock()+300:
                return
            if feed.kind == 'daily':
                if feed.current_daily.older(message, created):
                    return
                # Persist this barrier before any download OR readiness change.
                feed.current_daily.observe(message,created)
            feed.diagnostics.observe(message, created)
            key = event['channel_id']
            current = self.pending[key].get(message)
            running = self.active.get((key, message))
            if current and current['created_at'] > created:
                return
            if running and running['created_at'] == created and running['images'] == event['images']:
                return
            if current is not None:
                # Renew CDN signatures and supersede an older revision in place.
                current.clear()
                current.update(event)
                return
            if feed.kind == 'daily':
                for old in self.pending[key].values():
                    if old['message_id'] != message or old['created_at'] < created:
                        old['_superseded'] = True
            try:
                self.queues[key].put_nowait(event)
                self.pending[key][message] = event
            except asyncio.QueueFull:
                feed.diagnostics.error('receive_queue_full')
        elif kind == 'source_retracted':
            message = str(event.get('message_id', ''))
            if message.isdecimal():
                feed.diagnostics.retract(message)
        elif kind in {'ready','source_unavailable','connecting','login_failed','account_action_required','reader_failed'}:
            feed.status = kind
            if kind == 'ready':
                feed.diagnostics.poll()
            else:
                feed.diagnostics.error(kind)

    async def worker(self, key):
        feed, queue = self.feeds[key], self.queues[key]
        while True:
            event = await queue.get()
            message = event['message_id']
            self.pending[key].pop(message, None)
            self.active[key, message] = event
            try:
                if event.get('_superseded') or (bool(getattr(feed, 'native', False)) != self.primary):
                    continue
                retry_key = key, message, event['created_at']
                if asyncio.get_running_loop().time() < self.retry_after.get(retry_key, 0):
                    continue
                budget = getattr(self.bot, 'instance_storage', None)
                from banner_reader import image_identity
                fingerprint=hashlib.sha256(json.dumps(image_identity(event),separators=(',',':')).encode()).hexdigest()
                if feed.query('SELECT 1 FROM banner_source_receipts WHERE fingerprint=?',(fingerprint,)).fetchone():
                    with feed.db:
                        feed.diagnostics.received(message_id=message,created=event['created_at'], downloaded=False)
                    continue
                if budget:
                    # Disk headroom remains fixed; RAM is reserved by the actual
                    # image buffers and pixel decoder, before each allocation.
                    async with budget.reserve(32*1024*1024):
                        await asyncio.wait_for(feed.accept(event), RECEIVE_TIMEOUT)
                else:
                    await asyncio.wait_for(feed.accept(event), RECEIVE_TIMEOUT)
                self.retry_after.pop(retry_key, None)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                feed.diagnostics.error(receive_reason(error))
                self.retry_after[key, message, event['created_at']] = asyncio.get_running_loop().time() + 15
                if len(self.retry_after) > 128:
                    self.retry_after.pop(next(iter(self.retry_after)))
                log.warning('Receive deferred: feed=%s stage=receive error=%s status=%s',
                            feed.kind, type(error).__name__, getattr(error, 'status', 0))
            finally:
                self.active.pop((key, message), None)
                queue.task_done()

    async def close(self):
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
