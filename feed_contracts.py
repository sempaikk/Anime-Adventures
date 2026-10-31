"""Controlled stages/reasons and source envelopes, without either Discord SDK."""

import math
from enum import StrEnum
from typing import TypedDict


class Stage(StrEnum):
    SOURCE = 'source'
    RECEIVE = 'receive'
    DELIVERY = 'delivery'


class FeedJobState(StrEnum):
    PENDING = 'pending'
    SENDING = 'sending'
    UNCERTAIN = 'uncertain'
    SENT = 'sent'
    UNAVAILABLE = 'unavailable'
    OVERSIZE = 'oversize'
    REJECTED = 'rejected'
    SUPERSEDED = 'superseded'
    LEGACY_UNCERTAIN = 'legacy_uncertain'


class GlobalJobState(StrEnum):
    PREPARING = 'preparing'
    QUEUED = 'queued'
    SENDING = 'sending'
    UNCERTAIN = 'uncertain'
    SENT = 'sent'
    PARTIAL = 'partial'
    CANCELLED = 'cancelled'
    FAILED = 'failed'
    DELETED = 'deleted'


class Failure(StrEnum):
    RESOURCE = 'resource'
    RATE_LIMIT = 'rate_limit'
    PERMANENT = 'permanent'
    RETRY = 'retry'
    UNCERTAIN = 'uncertain'


def classify_failure(error, *, posting=False):
    """Only an explicit API rejection proves a POST was not accepted."""
    if getattr(error, 'resource', None) in {'memory', 'disk'}:
        return Failure.RESOURCE
    status = getattr(error, 'status', 0)
    if status == 429 or type(error).__name__ == 'RateLimited':
        return Failure.RATE_LIMIT
    if status in (400, 401, 403, 404, 413):
        return Failure.PERMANENT
    if posting:
        return Failure.UNCERTAIN
    return Failure.PERMANENT if isinstance(error, ValueError) else Failure.RETRY


SOURCE_ERRORS = frozenset({'source_unavailable', 'authorized_source_unavailable', 'connecting',
    'installing', 'reader_failed', 'login_failed', 'account_action_required', 'not_configured'})
RECEIVE_ERRORS = frozenset({'receive_memory_budget', 'receive_disk_budget', 'receive_queue_full',
    'receive_timeout', 'download_or_validation_failed', 'partial_reception',
    'unsupported_images', 'unsupported_source_urls', 'download_failed', 'storage_paused'})
DELIVERY_ERRORS = frozenset({'delivery_deferred', 'delivery_failed'})
DIAGNOSTIC_ERRORS = SOURCE_ERRORS | RECEIVE_ERRORS | DELIVERY_ERRORS


class SourceImage(TypedDict):
    channel_id: str
    message_id: str
    created_at: float
    published_at: float
    images: list[str]


def source_image(raw):
    """Copy the bounded allowlist; never carry source text/author information."""
    message, created = str(raw.get('message_id', '')), float(raw.get('created_at', 0))
    published = float(raw.get('published_at', created))
    urls = raw.get('images')
    if (not message.isdecimal() or len(message) > 22 or not math.isfinite(created)
            or not math.isfinite(published) or not isinstance(urls, list)
            or not 1 <= len(urls) <= 10 or any(not isinstance(u, str) or len(u) > 4096 for u in urls)):
        raise ValueError('Invalid source image envelope')
    return SourceImage(channel_id=str(raw.get('channel_id', '')), message_id=message,
        created_at=created, published_at=published, images=list(urls))


def error_stage(reason):
    return Stage.SOURCE if reason in SOURCE_ERRORS else Stage.DELIVERY if reason in DELIVERY_ERRORS else Stage.RECEIVE


def receive_reason(error):
    resource = getattr(error, 'resource', None)
    if resource in {'memory', 'disk'}:
        return 'receive_' + resource + '_budget'
    return 'receive_timeout' if isinstance(error, TimeoutError) else 'download_or_validation_failed'
