"""Cancellation cannot release a decoder's budget while its thread still runs."""

import asyncio


async def joined_thread(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args), name='bounded-file-validation')
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    if cancelled:
        # Consume a validation exception before propagating cancellation.
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()
