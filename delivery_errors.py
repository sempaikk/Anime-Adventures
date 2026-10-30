"""Classify only definite API rejections; transport ambiguity stays reconcilable."""

import discord

def feed_failure(error):
    status = getattr(error, 'status', 0)
    if status in (401, 403, 404):
        return 'unavailable'
    if status == 413 or getattr(error, 'code', 0) == 40005:
        return 'oversize'
    if status == 400:
        return 'rejected'
    if status == 429 or isinstance(error,discord.RateLimited):
        # discord.py applies Retry-After internally. Do not create another sender.
        return 'pending'
    return 'uncertain'


def retry_delay(error):
    if getattr(error,'status',0)!=429 and not isinstance(error,discord.RateLimited):
        return 0
    value=getattr(error,'retry_after',None)
    if value is None:
        value=getattr(getattr(error,'response',None),'headers',{}).get('Retry-After',30)
    try:
        return max(1,min(86400,float(value)))
    except (ValueError,TypeError):
        return 30
