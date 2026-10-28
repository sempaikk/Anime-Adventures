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
                self.assertEqual({c.name for c in bot.tree.get_commands()},{'globalchat','setbanner','dailychallenge'})
                self.assertEqual(bot.store.path,Path(folder)/'bot.sqlite3')
                self.assertEqual(len(bot.service_loops()),8)
                self.assertIsNotNone(bot.health.runner)
                self.assertFalse(hasattr(bot,'catalog'))
                self.assertFalse(hasattr(bot,'analyzer'))
                self.assertFalse(hasattr(bot,'knowledge'))
                await bot.close()
                self.assertIsNone(bot.health.runner)
                self.assertTrue(all(loop.get_task() is None or loop.get_task().done() for loop in bot.service_loops()))


if __name__=='__main__':
    unittest.main()
