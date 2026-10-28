"""Bounded reconciliation around the original attempt, not only the last screen."""

from datetime import datetime, timezone


async def recent_attempts(channel, attempted):
    after = datetime.fromtimestamp(max(0, attempted-5), timezone.utc)
    # Discord pages automatically; oldest first keeps the original time boundary.
    async for message in channel.history(limit=300, after=after, oldest_first=True):
        yield message
