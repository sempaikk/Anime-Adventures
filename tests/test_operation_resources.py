"""Resource reservations, recoverable snapshots, reproducible packages and role plans."""

from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import discord

from backup_check import check_restore
from bot_storage import make_snapshot
from bot_store import BotStore
from bot_release import manifest
from community_access import access_plan,ROLE_IDS
from instance_storage import InstanceStorage
from runtime_health import RuntimeHealth
from scripts.build_package import build_package


class ResourceChecks(unittest.IsolatedAsyncioTestCase):
    async def test_joint_reservations_prevent_parallel_overcommit_and_release_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            h=RuntimeHealth(lambda:True,lambda:None)
            q=InstanceStorage(folder,folder,h,limit_mb=64)
            with patch('instance_storage.process_memory',return_value=None):
                async with q.reserve(32*1024*1024):
                    with self.assertRaises(OSError):
                        async with q.reserve(20*1024*1024):
                            pass
                self.assertEqual(q.reserved,0)
                with self.assertRaises(RuntimeError):
                    async with q.reserve(1):
                        raise RuntimeError('synthetic interrupted preparation')
                self.assertEqual(q.reserved,0)

    async def test_memory_reservations_account_for_parallel_image_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            h=RuntimeHealth(lambda:True,lambda:None)
            q=InstanceStorage(folder,folder,h)
            q.memory_limit=100*1024*1024
            with patch('instance_storage.process_memory',return_value=40*1024*1024):
                async with q.reserve(1,memory=30*1024*1024):
                    with self.assertRaises(OSError):
                        async with q.reserve(1,memory=30*1024*1024):
                            pass
                self.assertEqual(q.reserved_memory,0)

    def test_restore_drill_compares_private_snapshot_without_touching_live_data(self):
        with tempfile.TemporaryDirectory() as folder:
            base=BotStore(Path(folder)/'bot.sqlite3')
            base.set('saved-setting','before-backup')
            snapshot,_=make_snapshot(base.path)
            base.set('saved-setting','current-live-setting')
            try:
                report=check_restore(snapshot,temporary_parent=folder)
                self.assertTrue(report['verified'])
                self.assertFalse(report['live_database_replaced'])
                self.assertEqual(base.get('saved-setting'),'current-live-setting')
                self.assertFalse(list(Path(folder).glob('restore-check-*')))
            finally:
                base.close()

    def test_complete_package_is_reproducible_and_contains_no_private_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'app';root.mkdir()
            (root/'data').mkdir()
            for name in ('bot.py','requirements.txt','README.md','Procfile','.python-version','.env.example'):
                (root/name).write_text('synthetic public file\n')
            (root/'.env').write_text('PRIVATE_SENTINEL')
            (root/'state').mkdir();(root/'state/private.sqlite3').write_bytes(b'PRIVATE_SENTINEL')
            (root/'data/build.json').write_text(json.dumps(manifest('synthetic',root)))
            first,second=Path(folder)/'one.zip',Path(folder)/'two.zip'
            build_package(first,root);build_package(second,root)
            self.assertEqual(first.read_bytes(),second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertNotIn('.env',archive.namelist())
                self.assertFalse(any(name.startswith('state/') for name in archive.namelist()))
                self.assertIn('data/build.json',archive.namelist())

    def test_official_role_plan_is_least_privilege_and_preserves_unknown_roles(self):
        class Role:
            def __init__(self,key,ident):
                self.id,self.name,self.managed=ident,key,False
                self.permissions=discord.Permissions(administrator=True)
            def __ge__(self,other):return False
        from community_hub import CENTRAL_GUILD_ID
        roles={ident:Role(key,ident) for key,ident in ROLE_IDS.items()}
        guild=SimpleNamespace(id=CENTRAL_GUILD_ID,roles=list(roles.values()),get_role=roles.get,me=SimpleNamespace(top_role=object()))
        plan,_=access_plan(guild)
        for role,p in plan:
            self.assertFalse(p.administrator)
            self.assertFalse(p.manage_guild)
            self.assertFalse(p.manage_roles)
            if role.name=='moderators':
                self.assertTrue(p.moderate_members)
                self.assertTrue(p.manage_messages)
            if role.name=='artists':
                self.assertEqual(p.value,0)
