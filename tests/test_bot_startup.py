"""The deployed entry point registers only active commands and owns the current database."""

from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from community_bot import CommunityBot


class StartupCase(unittest.IsolatedAsyncioTestCase):
    async def test_offline_setup_uses_only_active_services_and_closes_them(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{
                'PORT':'0','SECONDARY_ACCOUNT_TOKEN':'','BANNER_READER_TOKEN':''}):
            bot=CommunityBot(folder)
            bot.application_info=AsyncMock(return_value=SimpleNamespace(id=42,team=None,owner=SimpleNamespace(id=7)))
            bot.ui_theme.refresh=AsyncMock()
            bot.tree.sync=AsyncMock(return_value=[])
            async with bot:
                await bot.setup_hook()
                self.assertEqual({c.name for c in bot.tree.get_commands()},{'globalchat','setbanner','dailychallenge','Report global message'})
                self.assertEqual(bot.store.path,Path(folder)/'bot.sqlite3')
                self.assertEqual(len(bot.service_loops()),8)
                self.assertIsNotNone(bot.health.runner)
                self.assertFalse(hasattr(bot,'catalog'))
                self.assertFalse(hasattr(bot,'analyzer'))
                self.assertFalse(hasattr(bot,'knowledge'))
                self.assertFalse(hasattr(bot,'adventures'))
                self.assertFalse(bot._connection._view_store._dynamic_items)
                await bot.close()
                self.assertIsNone(bot.health.runner)
                self.assertTrue(all(loop.get_task() is None or loop.get_task().done() for loop in bot.service_loops()))

    async def test_sync_replaces_the_remote_command_list_without_retired_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=CommunityBot(folder)
            bot._connection.application_id=42
            remote={'adventures','globalchat','setbanner','dailychallenge','Report global message'}
            async def replace(application,*,payload):
                self.assertEqual(application,42)
                remote.clear()
                remote.update(c['name'] for c in payload)
                return []
            bot.http.bulk_upsert_global_commands=AsyncMock(side_effect=replace)
            try:
                await bot.sync_commands()
                self.assertEqual(remote,{'globalchat','setbanner','dailychallenge','Report global message'})
                self.assertEqual(bot.command_sync_status,'confirmed')
                bot.http.bulk_upsert_global_commands.assert_awaited_once()
            finally:
                await bot.close()

    async def test_existing_optional_state_is_preserved_without_a_worker_or_callbacks(self):
        from bot_store import BotStore
        with tempfile.TemporaryDirectory() as folder:
            base=BotStore(Path(folder)/'bot.sqlite3')
            with base.connection:
                base.connection.execute('CREATE TABLE bot_tool_reminders(id TEXT PRIMARY KEY,state TEXT,body TEXT)')
                base.connection.execute("INSERT INTO bot_tool_reminders VALUES('fixture','pending','Private synthetic reminder')")
                base.set('receipt-sentinel','accepted')
            base.close()
            bot=CommunityBot(folder)
            try:
                self.assertEqual(bot.store.rows('SELECT * FROM bot_tool_reminders'),[{'id':'fixture','state':'pending','body':'Private synthetic reminder'}])
                self.assertEqual(bot.store.get('receipt-sentinel'),'accepted')
                self.assertEqual(len(bot.service_loops()),8)
                self.assertIsNone(bot.tree.get_command('adventures'))
                self.assertFalse(hasattr(bot,'adventures'))
                self.assertFalse(bot._connection._view_store._dynamic_items)
            finally:
                await bot.close()


if __name__=='__main__':
    unittest.main()
