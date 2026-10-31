"""Two bounded receive workers: a slow source never blocks the other feed's pipe."""

import asyncio
import logging
import math
import hashlib
import json

from game_sources import BANNER_CHANNEL_ID, DAILY_CHANNEL_ID

log = logging.getLogger('adventures.receiver')


class FeedReceiver:
    def __init__(self, bot, *, primary=False):
        self.bot = bot
        self.primary=primary
        self.feeds = {str(BANNER_CHANNEL_ID): bot.banners, str(DAILY_CHANNEL_ID): bot.daily}
        self.queues = {key: asyncio.Queue(maxsize=64) for key in self.feeds}
        self.tasks = []

    def start(self):
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
            message, created = str(event.get('message_id', '')), float(event.get('created_at', 0))
            if not message.isdecimal() or len(message)>22 or not math.isfinite(created):
                return
            if not feed.clock()-feed.max_age < created <= feed.clock()+300:
                return
            if feed.kind == 'daily':
                if feed.current_daily.older(message, created):
                    return
                # Persist this barrier before any download OR readiness change.
                feed.current_daily.observe(message,created)
            feed.diagnostics.observe(message, created)
            try:
                self.queues[str(event['channel_id'])].put_nowait(event)
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
            try:
                budget = getattr(self.bot, 'instance_storage', None)
                from banner_reader import image_identity
                fingerprint=hashlib.sha256(json.dumps(image_identity(event),separators=(',',':')).encode()).hexdigest()
                if feed.query('SELECT 1 FROM banner_source_receipts WHERE fingerprint=?',(fingerprint,)).fetchone():
                    with feed.db:
                        feed.diagnostics.received(message_id=str(event['message_id']),created=float(event['created_at']))
                    continue
                if budget:
                    # Disk headroom remains fixed; RAM is reserved by the actual
                    # image buffers and pixel decoder, before each allocation.
                    async with budget.reserve(32*1024*1024):
                        await asyncio.wait_for(feed.accept(event), 65)
                else:
                    await asyncio.wait_for(feed.accept(event), 65)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                from instance_storage import ResourceBudgetError
                issue = 'download_or_validation_failed'
                if isinstance(error, ResourceBudgetError):
                    issue = 'receive_memory_budget' if error.resource == 'memory' else 'receive_disk_budget'
                feed.diagnostics.error(issue)
                log.warning('Receive deferred: feed=%s stage=receive error=%s status=%s',
                            feed.kind, type(error).__name__, getattr(error, 'status', 0))
            finally:
                queue.task_done()

    async def close(self):
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
