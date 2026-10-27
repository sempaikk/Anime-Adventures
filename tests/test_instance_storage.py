"""Hosting quota accounting stays independent of the machine's free filesystem."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from instance_storage import InstanceStorage
from runtime_health import RuntimeHealth


class QuotaCase(unittest.IsolatedAsyncioTestCase):
    async def test_measures_project_external_data_and_hardlinks_once_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'project';root.mkdir()
            data=Path(directory)/'state';data.mkdir()
            (root/'file').write_bytes(b'x'*8192)
            os.link(root/'file',root/'hardlink')
            (root/'outside').symlink_to(data,target_is_directory=True)
            (data/'db').write_bytes(b'y'*8192)
            health=RuntimeHealth(lambda:True,lambda:None)
            quota=InstanceStorage(root,data,health,limit_mb=512)
            measured=quota.measure()
            self.assertGreaterEqual(measured,16384)
            self.assertLess(measured,24576)
            available=await quota.available()
            self.assertLessEqual(available,512*1024*1024-16384)
            self.assertEqual(health.quota['total'],512*1024*1024)

    async def test_quota_critical_status_is_not_hidden_by_large_host_filesystem(self):
        health=RuntimeHealth(lambda:True,lambda:None)
        health.update_quota(500*1024*1024,512*1024*1024)
        self.assertEqual(health.storage_level,'critical')
        health.update_storage({'backup':'fresh','free_bytes':10**12,'total_bytes':2*10**12})
        self.assertEqual(health.storage_level,'critical')
        health.update_quota(100*1024*1024,512*1024*1024)
        self.assertEqual(health.storage_level,'ok')
