"""Account for the hosting quota, including dependencies, caches and backups."""

import asyncio
import os
from pathlib import Path
import shutil
import time
from contextlib import asynccontextmanager


class ResourceBudgetError(OSError):
    """A controlled, private resource reason; never includes URLs or secrets."""
    def __init__(self, resource, message):
        super().__init__(message)
        self.resource = resource


def process_memory():
    """Conservative current RSS of this process and its children on Linux."""
    pending, seen, total = [os.getpid()], set(), 0
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        try:
            for line in Path(f'/proc/{pid}/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    total += int(line.split()[1]) * 1024
            children = Path(f'/proc/{pid}/task/{pid}/children')
            pending.extend(int(value) for value in children.read_text().split())
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return total or None


class InstanceStorage:
    def __init__(self, root, data, health, *, limit_mb=512):
        self.root,self.data,self.health=Path(root).resolve(),Path(data).resolve(),health
        self.limit=max(64,int(limit_mb))*1024*1024
        self.used=0
        self.checked=0
        self.lock=asyncio.Lock()
        self.reserved = 0
        self.reserved_memory = 0
        self.reservation_lock = asyncio.Lock()
        self.memory_limit = max(64, int(os.getenv('INSTANCE_RAM_LIMIT_MB', '256'))) * 1024 * 1024

    def measure(self):
        roots=[self.root]
        if not self.data.is_relative_to(self.root):
            roots.append(self.data)
        total=0;known=set()
        for root in roots:
            for folder,dirs,files in os.walk(root,followlinks=False):
                dirs[:]=[name for name in dirs if not (Path(folder)/name).is_symlink()]
                for name in files:
                    try:
                        info=(Path(folder)/name).lstat()
                    except FileNotFoundError:
                        continue
                    key=(info.st_dev,info.st_ino)
                    if key not in known:
                        known.add(key)
                        total+=max(info.st_size,getattr(info,'st_blocks',0)*512)
        return total

    async def refresh(self,*,force=False):
        async with self.lock:
            if force or time.monotonic()-self.checked>10:
                self.used=await asyncio.to_thread(self.measure)
                self.checked=time.monotonic()
                self.health.update_quota(self.used,self.limit)
                self.health.update_memory(process_memory(), self.memory_limit)

    async def available(self):
        await self.refresh()
        return max(0,min(shutil.disk_usage(self.root).free,self.limit-self.used)-self.reserved)

    @asynccontextmanager
    async def reserve(self, amount, *, memory=0, feature=None):
        amount = max(0, int(amount))
        memory = max(0, int(memory))
        async with self.reservation_lock:
            free = await self.available() if amount else float('inf')
            rss = process_memory()
            # New chat uploads leave room for fresh feeds, durable receipts and
            # a verified snapshot. Existing deletions/reconciliation need no upload.
            headroom = 48 * 1024 * 1024 if feature == 'global' else 16 * 1024 * 1024
            if free < amount + headroom:
                raise ResourceBudgetError('disk', 'Storage budget is reserved for safe operation. Try again after cleanup.')
            if rss is not None and rss + self.reserved_memory + memory > self.memory_limit * .9:
                raise ResourceBudgetError('memory', 'Image preparation is paused while memory usage is high.')
            self.reserved += amount
            self.reserved_memory += memory
        try:
            yield
        finally:
            self.reserved -= amount
            self.reserved_memory -= memory
            if amount:
                self.checked = 0
