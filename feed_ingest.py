"""Scope, transfer/validation and atomic persistence for both existing feeds."""

import asyncio
from dataclasses import dataclass, field
import hashlib
import json

import aiohttp

from banner_reader import image_identity
from feed_contracts import source_image
from feed_memory import current_memory
from media_validation import decode_budget
from resource_jobs import joined_thread


@dataclass
class Reception:
    source: dict
    urls: list
    skipped: int = 0
    images: list = field(default_factory=list)
    blobs: dict = field(default_factory=dict)
    size: int = 0
    partial: bool = False
    last_error: Exception | None = None

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(image_identity(self.source), separators=(',', ':')).encode()).hexdigest()


def scope(feed, raw):
    from banner_relay import image_url
    event = source_image(raw)
    created, message = event['created_at'], event['message_id']
    if (event['channel_id'] not in {str(v) for v in feed.source_ids}
            or not feed.clock()-feed.max_age < created <= feed.clock()+300):
        return None
    if feed.kind == 'daily' and not all(image_url(u) for u in event['images']):
        return None
    urls = [u for u in event['images'] if image_url(u)]
    if not urls:
        feed.diagnostics.error('unsupported_source_urls')
        return None
    if event['published_at'] <= feed.clock()-feed.max_age:
        known = feed.query('SELECT 1 FROM banner_seen WHERE source_message=? LIMIT 1', (message,)).fetchone()
        current = feed.current_daily.current() if feed.kind == 'daily' else None
        if not known and not (current and current['source_message'] == message):
            return None
    return Reception(event, list(dict.fromkeys(urls)), len(event['images'])-len(urls))


async def files(feed, ctx):
    from banner_relay import MAX_IMAGE, MAX_BATCH, image_extension
    for url in ctx.urls:
        if feed.diagnostics.newer_version(ctx.source['message_id'], ctx.source['created_at']):
            return
        try:
            blob = await feed.download(url, min(MAX_IMAGE, MAX_BATCH-ctx.size))
            await current_memory().keep(blob)
            ctx.size += len(blob)
            async with decode_budget(getattr(feed.bot, 'instance_storage', None), blob):
                extension = await joined_thread(image_extension, blob)
        except (ValueError, aiohttp.ClientError, TimeoutError, OSError) as error:
            if isinstance(error, ValueError) and str(error) == 'Unsupported image':
                ctx.skipped += 1
                continue
            if feed.kind == 'daily':
                raise
            ctx.partial, ctx.last_error = True, error
            continue
        digest = hashlib.sha256(blob).hexdigest()
        if digest not in ctx.blobs:
            ctx.images.append(digest)
            ctx.blobs[digest] = extension, blob


def persist(feed, ctx):
    from banner_relay import MAX_CACHE
    message, created = ctx.source['message_id'], ctx.source['created_at']
    if not ctx.images or feed.diagnostics.newer_version(message, created):
        return False
    ident = hashlib.sha256((message+':'+':'.join(ctx.images)).encode()).hexdigest()
    exists = feed.query('SELECT 1 FROM banner_events WHERE id=?', (ident,)).fetchone()
    known = bool(exists or feed.diagnostics.known(message, ctx.images)
        or (feed.kind == 'daily' and feed.current_daily.current() is not None
            and feed.current_daily.current()['event_id'] == ident))
    if not known:
        used = feed.query('SELECT COALESCE(SUM(length(data)),0) FROM banner_assets').fetchone()[0]
        new = sum(len(blob) for digest, (_, blob) in ctx.blobs.items()
            if not feed.query('SELECT 1 FROM banner_assets WHERE digest=?', (digest,)).fetchone())
        if used+new > MAX_CACHE or feed.query('SELECT count(*) FROM banner_events').fetchone()[0] >= 64:
            raise ValueError('Banner cache full')
    with feed.db:
        if not known:
            for digest, (extension, blob) in ctx.blobs.items():
                feed.query('INSERT OR IGNORE INTO banner_assets VALUES(?,?,?)', (digest, extension, blob))
            feed.query('INSERT INTO banner_events VALUES(?,?,?,?)', (ident, message, created, json.dumps(ctx.images)))
            feed.diagnostics.remember(message, ctx.images, created)
            feed.query("UPDATE banner_jobs SET state='superseded' WHERE state='pending' AND event_id IN (SELECT id FROM banner_events WHERE source_message=? AND id<>?)", (message, ident))
            feed.query('INSERT OR IGNORE INTO banner_jobs(event_id,guild_id,channel_id) SELECT ?,guild_id,channel_id FROM banner_targets', (ident,))
        if feed.kind == 'daily':
            feed.current_daily.remember(ident, message, created)
        if not ctx.partial:
            feed.diagnostics.received(ctx.skipped, message_id=message, created=created, images=ctx.images)
            feed.query('INSERT OR REPLACE INTO banner_source_receipts VALUES(?,?)', (ctx.fingerprint, created+feed.max_age))
        else:
            feed.query("UPDATE banner_diagnostics SET receive_error='partial_reception',error='partial_reception' WHERE singleton=1")
    return not known


async def receive(feed, payload):
    try:
        ctx = scope(feed, payload)
    except (ValueError, TypeError, KeyError, OverflowError):
        return False
    if ctx is None:
        return False
    if feed.bot.health.storage_level == 'critical':
        feed.diagnostics.error('storage_paused')
        return False
    message, created = ctx.source['message_id'], ctx.source['created_at']
    async with feed.accept_lock:
        feed.prune()
        if feed.diagnostics.obsolete(message) or feed.diagnostics.newer_version(message, created):
            return False
        if feed.kind == 'daily':
            if feed.current_daily.older(message, created):
                return False
            feed.current_daily.observe(message, created)
        feed.diagnostics.observe(message, created)
        if feed.query('SELECT 1 FROM banner_source_receipts WHERE fingerprint=?', (ctx.fingerprint,)).fetchone():
            with feed.db:
                feed.diagnostics.received(message_id=message, created=created, downloaded=False)
            return False
        try:
            await files(feed, ctx)
        except asyncio.CancelledError:
            # The source receipt remains unconfirmed; good banner parts survive
            # an attempt deadline and image receipts deduplicate the later retry.
            if feed.kind == 'banner' and ctx.images:
                ctx.partial = True
                persist(feed, ctx)
            raise
        if not ctx.images:
            if ctx.last_error:
                raise ctx.last_error
            feed.diagnostics.error('unsupported_images')
            return False
        return persist(feed, ctx)
