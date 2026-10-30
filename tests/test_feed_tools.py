"""Existing feed quiet hours remain independent of removed game tools."""

from datetime import datetime, timezone
import io
import json
import unittest

import discord
from discord.http import handle_message_parameters

from feed_tools import quiet, silence_payload
import test_banners as feeds


class FeedQuietCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=feeds.BannerCase.asyncSetUp
    asyncTearDown=feeds.BannerCase.asyncTearDown
    add_channel=feeds.BannerCase.add_channel
    send=feeds.BannerCase.send
    event=feeds.BannerCase.event

    def configure_legacy_quiet(self):
        hour=datetime.fromtimestamp(self.app.store.clock(),timezone.utc).hour
        settings={'timezone':'UTC','quiet_start':hour,'quiet_end':(hour+1)%24}
        with self.app.store.connection:
            self.app.store.connection.execute('CREATE TABLE bot_tool_settings(guild TEXT PRIMARY KEY,data TEXT,version INTEGER)')
            self.app.store.connection.execute('INSERT INTO bot_tool_settings VALUES(?,?,1)',('1',json.dumps(settings)))

    async def test_fresh_install_does_not_create_optional_tables_or_change_payload(self):
        before={r['name'] for r in self.app.store.rows("SELECT name FROM sqlite_master WHERE type='table'")}
        with handle_message_parameters(content='synthetic',nonce='123') as params:
            original=dict(params.payload)
            silence_payload(self.app,1,params)
            self.assertEqual(params.payload,original)
        self.assertFalse(any(name.startswith('bot_tool_') for name in before))
        self.assertEqual(before,{r['name'] for r in self.app.store.rows("SELECT name FROM sqlite_master WHERE type='table'")})

    async def test_quiet_hours_preserve_multipart_image_and_nonce(self):
        self.configure_legacy_quiet()
        file=discord.File(io.BytesIO(b'unchanged'),filename='same.png')
        try:
            with handle_message_parameters(files=[file],nonce='123') as params:
                silence_payload(self.app,1,params)
                body=json.loads(next(e['value'] for e in params.multipart if e['name']=='payload_json'))
                self.assertEqual(body['flags']&4096,4096)
                self.assertEqual(body['nonce'],'123')
                self.assertTrue(body['enforce_nonce'])
                self.assertEqual(file.fp.read(),b'unchanged')
        finally:
            file.close()

    async def test_other_guild_and_invalid_settings_do_not_silence_or_block_delivery(self):
        self.configure_legacy_quiet()
        for guild in (2,1):
            with self.app.store.connection:
                self.app.store.connection.execute("UPDATE bot_tool_settings SET data='invalid json'")
            with handle_message_parameters(content='synthetic') as params:
                silence_payload(self.app,guild,params)
                self.assertFalse(params.payload.get('flags',0)&4096)

    async def test_quiet_interval_and_pinned_timezone_fallback(self):
        import zoneinfo
        cfg={'timezone':'UTC','quiet_start':22,'quiet_end':8}
        for hour,expected in ((23,True),(3,True),(8,False),(12,False)):
            self.assertEqual(quiet(cfg,datetime(2026,1,1,hour,tzinfo=timezone.utc).timestamp()),expected)
        original=zoneinfo.TZPATH
        try:
            zoneinfo.reset_tzpath(())
            zoneinfo.ZoneInfo.clear_cache()
            cfg['timezone']='America/Sao_Paulo'
            self.assertTrue(quiet(cfg,datetime(2026,1,1,3,tzinfo=timezone.utc).timestamp()))
        finally:
            zoneinfo.reset_tzpath(original)
            zoneinfo.ZoneInfo.clear_cache()
