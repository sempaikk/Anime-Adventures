"""Reserve actual compressed image buffers, rather than a fixed 32 MiB per feed."""

from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar

_CURRENT = ContextVar('feed_receive_memory', default=None)


class ReceiveMemory:
    def __init__(self, budget, stack):
        self.budget, self.stack = budget, stack
        self.buffers = {}
        self.leases = []

    async def reserve(self, amount):
        if self.budget is not None and amount:
            lease = await self.stack.enter_async_context(self.budget.reserve(0, memory=amount))
            if hasattr(lease, 'materialize'):
                self.leases.append(lease)

    def retain(self, blob):
        if id(blob) not in self.buffers:
            remaining = len(blob)
            for lease in self.leases:
                remaining -= lease.materialize(remaining)
                if not remaining:
                    break
        self.buffers[id(blob)] = blob

    async def keep(self, blob):
        # A replacement download implementation still has to account for its
        # retained buffers/SQLite copy. The real downloader reserves BEFORE read.
        if id(blob) not in self.buffers:
            await self.reserve(2 * len(blob) + 128 * 1024)
            self.retain(blob)


@asynccontextmanager
async def receive_memory(budget):
    current = _CURRENT.get()
    if current is not None:
        yield current
        return
    async with AsyncExitStack() as stack:
        memory = ReceiveMemory(budget, stack)
        token = _CURRENT.set(memory)
        try:
            yield memory
        finally:
            _CURRENT.reset(token)


def current_memory():
    return _CURRENT.get()
