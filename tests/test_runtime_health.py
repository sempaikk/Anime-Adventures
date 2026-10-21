import sqlite3
import unittest
import io
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp

from runtime_health import RuntimeHealth
from scripts.check_health import check_ready
import bot as app


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connected=False
        self.database=sqlite3.connect(':memory:')
        self.health=RuntimeHealth(lambda:self.connected,lambda:self.database)

    async def asyncTearDown(self):
        await self.health.close()
        self.database.close()

    async def test_live_readiness_and_database_failure_return_only_minimal_public_status(self):
        await self.health.start(0)
        base='http://127.0.0.1:'+str(self.health.port)
        async with aiohttp.ClientSession() as session:
            async with session.get(base+'/health') as response:
                self.assertEqual(response.status,200)
                self.assertEqual(await response.json(),{'status':'alive'})
                self.assertEqual(response.headers['Cache-Control'],'no-store')
            async with session.get(base+'/ready') as response:
                self.assertEqual(response.status,503)
                self.assertEqual(await response.json(),{'status':'unavailable'})
            self.connected=True
            async with session.get(base+'/ready') as response:
                self.assertEqual(response.status,200)
                self.assertEqual(await response.json(),{'status':'ready'})
            self.health.storage_level='critical'
            async with session.get(base+'/ready') as response:
                self.assertEqual(response.status,503)
            self.health.storage_level='ok'
            self.database.close()
            async with session.get(base+'/ready') as response:
                self.assertEqual(response.status,503)

    async def test_storage_alerts_fire_on_state_changes_and_backup_failure_is_visible(self):
        report={'database_bytes':10,'total_bytes':100*1024*1024,'free_bytes':20*1024*1024,'backup':'fresh','backup_modified':100}
        with self.assertLogs('adventures.health',level='WARNING') as logs:
            self.health.update_storage(report)
            self.health.update_storage(report)
            self.health.update_storage({**report,'free_bytes':5*1024*1024})
        self.assertEqual(len(logs.output),2)
        self.assertEqual(self.health.status()['storage'],'critical')
        self.assertEqual(self.health.status()['last_backup'],100)
        self.health.backup_error=True
        self.assertTrue(self.health.status()['backup_error'])

    def test_external_monitor_accepts_only_readiness_and_does_not_treat_liveness_as_ready(self):
        class Response(io.BytesIO):
            status=200
        self.assertTrue(check_ready('https://example.com/ready',opener=lambda *a,**k:Response(b'{"status":"ready"}')))
        self.assertFalse(check_ready('https://example.com/health',opener=lambda *a,**k:Response(b'{"status":"alive"}')))
        self.assertFalse(check_ready('https://example.com/ready',opener=lambda *a,**k:Response(b'x'*4097)))
        with self.assertRaises(ValueError):
            check_ready('http://example.com/ready')

    async def test_offline_startup_installs_storage_recovery_and_health_without_logging_into_discord(self):
        client=app.AdventuresBot()
        loop=asyncio.get_running_loop()
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory,'PORT':'0'}),\
                patch.object(client.tree,'sync',new=AsyncMock(return_value=[])),patch.object(loop,'add_signal_handler'):
            async with client:
                await client.setup_hook()
                self.assertEqual(client.scores.path,Path(directory)/'scores.sqlite3')
                self.assertIsNotNone(client.adventures)
                self.assertIsNotNone(client.health.runner)
                self.assertIsNotNone(client.session_task)
                self.assertIsNotNone(client.host_task)
                self.assertFalse(client.is_ready())
                await client.close()
                self.assertIsNone(client.health.runner)
                self.assertIsNone(client.session_task)
                self.assertIsNone(client.host_task)
