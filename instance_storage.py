"""Account for the hosting quota, including dependencies, caches and backups."""

import asyncio
import os
from pathlib import Path
import shutil
import time


class InstanceStorage:
    def __init__(self, root, data, health, *, limit_mb=512):
        self.root,self.data,self.health=Path(root).resolve(),Path(data).resolve(),health
        self.limit=max(64,int(limit_mb))*1024*1024
        self.used=0
        self.checked=0
        self.lock=asyncio.Lock()

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

    async def available(self):
        await self.refresh()
        return max(0,min(shutil.disk_usage(self.root).free,self.limit-self.used))
