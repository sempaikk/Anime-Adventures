"""Private UI isolation, startup recovery and storage/release acceptance checks."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

import discord

import test_banners as feeds
import test_global_chat as chats
from community_bot import CommunityBot
from community_hub import CENTRAL_GUILD_ID
from bot_ui import payload
from bot_store import BotStore
from bot_release import manifest, build_info
from bot_storage import make_snapshot, acquire_lease
from backup_check import check_restore
from instance_storage import InstanceStorage
from runtime_health import RuntimeHealth
from operations_views import diagnostic_text, DestinationView
from participant_history import RequestHistory, RecentReport, RestrictionView
from scripts.build_package import build_package
from scripts.check_package import check_package
from scripts.compact_state import compact_state
from scripts.export_backup import encrypt_snapshot


class PrivateFeedOperations(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=feeds.BannerCase.asyncSetUp
    asyncTearDown=feeds.BannerCase.asyncTearDown
    add_channel=feeds.BannerCase.add_channel
    send=feeds.BannerCase.send
    event=feeds.BannerCase.event
    interaction=feeds.BannerCase.interaction

    async def test_diagnostics_contains_only_requested_server_and_controlled_fields(self):
        self.app.globalchat.store.configure(1,10,110,'PRIVATE_WEBHOOK_SENTINEL',0)
        self.relay.configure(1,10)
        self.app.daily.configure(987654321,987654322)
        self.relay.diagnostics.error('PRIVATE_EXCEPTION_SENTINEL')
        text=diagnostic_text(self.app,1)
        data=json.loads(text.split('```json\n')[1].split('```')[0])
        self.assertEqual(data['server'],'1')
        self.assertIsNone(data['feeds']['daily']['channel'])
        self.assertNotIn('987654322',text)
        self.assertNotIn('PRIVATE_',text)
        self.assertEqual(data['feeds']['banner']['issue'],'source_issue')
        self.assertFalse(self.sent)

    async def test_destination_triage_covers_all_configured_servers_but_rejects_non_owner(self):
        self.app.owner_ids_set={7}
        self.relay.configure(1,10)
        self.relay.configure(2,20)
        await self.relay.accept(self.event())
        self.channels[20].permissions_for.return_value.attach_files=False
        await self.relay.cycle()
        view=DestinationView(self.app,self.interaction(actor=7))
        text=view.description()
        self.assertIn('server 2',text)
        self.assertIn('unavailable',text)
        with self.assertRaises(ValueError):
            view.require(self.interaction(actor=8))
        card=payload(bot=self.app,content=text,view=view)['view']
        self.assertLessEqual(card.total_children_count,40)

    async def test_read_only_connection_check_does_not_move_destination(self):
        from feed_views import FeedPanel
        self.relay.configure(1,10)
        self.add_channel(1,11)
        i=self.interaction(channel=11)
        generation=self.relay.generation(1)
        panel=FeedPanel(self.app,i,kind='banner')
        await panel.status.callback(i)
        self.assertEqual(self.relay.target(1)['channel_id'],'10')
        self.assertEqual(self.relay.generation(1),generation)
        await panel.enable.callback(i)
        self.assertEqual(self.relay.target(1)['channel_id'],'10')
        confirmation=i.followup.send.call_args.kwargs['view'].controller
        await confirmation.confirm.callback(i)
        self.assertEqual(self.relay.target(1)['channel_id'],'11')

    async def test_feed_move_confirmation_rejects_stale_configuration(self):
        from feed_views import FeedPanel
        self.relay.configure(1,10)
        self.add_channel(1,11)
        i=self.interaction(channel=11)
        panel=FeedPanel(self.app,i,kind='banner')
        await panel.enable.callback(i)
        confirmation=i.followup.send.call_args.kwargs['view'].controller
        self.relay.disable(1)
        with self.assertRaises(ValueError):
            await confirmation.confirm.callback(i)
        self.assertIsNone(self.relay.target(1))

    async def test_release_feature_gate_requires_current_source_progress(self):
        self.relay.configure(1,10)
        self.relay.votes.release_pending=lambda:None
        self.relay.status='source_unavailable'
        self.assertFalse(self.app.community.update_complete({'requires_feeds':['banner']}))
        self.relay.status='ready'
        self.relay.diagnostics.poll()
        self.assertTrue(self.app.community.update_complete({'requires_feeds':['banner']}))
        self.relay.pause(True,7)
        self.assertFalse(self.app.community.update_complete({'requires_feeds':['banner']}))

    async def test_application_restore_drill_preserves_config_and_receipts_and_never_replaces_live_state(self):
        self.relay.configure(1,10)
        await self.relay.accept(self.event())
        await self.relay.cycle()
        self.app.globalchat.store.consent(123)
        self.app.store.set('restore-sentinel','snapshot')
        snapshot,_=make_snapshot(self.app.store.path)
        self.app.store.set('restore-sentinel','live')
        report=check_restore(snapshot,temporary_parent=self.temp.name)
        self.assertTrue(report['verified'])
        self.assertGreater(report['application_state_checked'],3)
        self.assertEqual(self.app.store.get('restore-sentinel'),'live')
        self.assertEqual(len(self.sent),1)
        self.assertFalse(report['network_used'])


class PrivateParticipantOperations(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=chats.ChatCase.asyncSetUp
    asyncTearDown=chats.ChatCase.asyncTearDown
    fetch=chats.ChatCase.fetch
    history=chats.ChatCase.history
    send_notice=chats.ChatCase.send_notice
    message=chats.ChatCase.message
    interaction=chats.ChatCase.interaction
    copies=chats.ChatCase.copies
    flush=chats.ChatCase.flush
    asset=chats.ChatCase.asset

    async def test_request_followup_is_scoped_to_reporter_and_server(self):
        source=self.message()
        await self.engine.ingest(source)
        await self.flush()
        first=self.engine.store.report(source.id,7,1,'Own report for this server')
        foreign=self.engine.store.report(source.id,8,2,'Report belonging to someone else')
        text=RequestHistory(self.app,self.interaction(user=7)).description()
        self.assertIn('Report #'+str(first),text)
        self.assertNotIn('Report #'+str(foreign),text)
        self.assertNotIn('someone else',text)

    async def test_duplicate_report_keeps_receipt_and_never_claims_a_foreign_report_is_local(self):
        source=self.message()
        await self.engine.ingest(source)
        first=self.engine.store.report(source.id,7,1,'Own report in first server')
        self.assertEqual(self.engine.store.report(source.id,7,1,'Same report submitted again'),first)
        with self.assertRaisesRegex(ValueError,'another server'):
            self.engine.store.report(source.id,7,2,'Same report in a different server')
        self.assertNotIn('Report #'+str(first),RequestHistory(self.app,self.interaction(gid=2)).description())

    async def test_feedback_status_is_visible_only_to_submitter_in_official_community(self):
        from community_feedback import CommunityFeedback
        self.app.feedback=CommunityFeedback(self.app)
        i=self.interaction()
        i.guild_id=CENTRAL_GUILD_ID
        ident=self.app.feedback.submit(i,'suggestion','A useful private suggestion for this test')
        self.assertIn('Feedback #'+str(ident),RequestHistory(self.app,i).description())
        other=self.interaction(user=8)
        other.guild_id=CENTRAL_GUILD_ID
        self.assertNotIn('Feedback #'+str(ident),RequestHistory(self.app,other).description())
        self.assertNotIn('Feedback #'+str(ident),RequestHistory(self.app,self.interaction()).description())

    async def test_recent_report_selection_respects_channel_history_access(self):
        source=self.message()
        await self.engine.ingest(source)
        await self.flush()
        i=self.interaction(gid=2)
        view=RecentReport(self.app,i)
        self.assertTrue(view.options)
        self.channels[20].permissions_for.return_value.read_message_history=False
        with self.assertRaises(ValueError):
            view.check_channel(i)
        with self.assertRaises(ValueError):
            RecentReport(self.app,i)

    async def test_temporary_restrictions_and_release_are_local_and_version_safe(self):
        store=self.engine.store
        store.restrict(1,'user',123,900,7,'Temporary restriction for a test')
        self.assertTrue(store.blocked(123,1))
        self.assertFalse(store.blocked(123,2))
        view=RestrictionView(self.app,self.interaction(admin=True),network=False)
        self.assertIn('123',view.description())
        store.block(1,'user',123,7,'Release after private review',enabled=False)
        self.assertFalse(store.blocked(123,1))
        self.assertIn('No active restrictions',view.description())

    async def test_image_only_install_omits_webhooks_but_global_still_requires_them(self):
        from app_profile import install_permissions
        from global_relay import REQUIRED
        image=install_permissions('images')
        self.assertFalse(image.manage_webhooks)
        self.assertTrue(image.attach_files)
        self.assertFalse(image.administrator)
        self.assertIn('manage_webhooks',REQUIRED)

    async def test_attachment_description_is_preserved_in_transport_metadata(self):
        asset=self.asset()
        asset.description='An accessible description written by the member'
        message=self.message(attachments=[asset])
        await self.engine.ingest(message)
        row=self.engine.store.message(message.id)
        data=json.loads(row['payload'])
        self.assertEqual(data['files'][0]['description'],asset.description)
        files,_=self.engine.media.files(data['files'],self.channels[20].guild.filesize_limit)
        try:
            self.assertEqual(files[0].description,asset.description)
        finally:
            for file in files:
                file.close()


class OperationalBudgets(unittest.IsolatedAsyncioTestCase):
    async def test_new_global_uploads_leave_headroom_for_feeds_and_state(self):
        with tempfile.TemporaryDirectory() as folder:
            budget=InstanceStorage(folder,folder,RuntimeHealth(lambda:True,lambda:None),limit_mb=64)
            with patch('instance_storage.process_memory',return_value=None):
                with self.assertRaises(OSError):
                    async with budget.reserve(20*1024*1024,feature='global'):
                        pass
                async with budget.reserve(20*1024*1024):
                    pass
            self.assertEqual(budget.reserved,0)

    async def test_outbound_memory_reservation_cannot_exceed_instance_margin(self):
        with tempfile.TemporaryDirectory() as folder:
            budget=InstanceStorage(folder,folder,RuntimeHealth(lambda:True,lambda:None))
            with patch('instance_storage.process_memory',return_value=180*1024*1024):
                with self.assertRaises(OSError):
                    async with budget.reserve(0,memory=60*1024*1024):
                        pass
            self.assertEqual(budget.reserved_memory,0)

    async def test_failed_command_sync_does_not_prevent_service_startup(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'PORT':'0','SECONDARY_ACCOUNT_TOKEN':''}):
            bot=CommunityBot(folder)
            bot.application_info=AsyncMock(return_value=SimpleNamespace(id=42,team=None,owner=SimpleNamespace(id=7)))
            bot.ui_theme.refresh=AsyncMock()
            bot.tree.sync=AsyncMock(side_effect=RuntimeError('Synthetic sync outage'))
            async with bot:
                await bot.setup_hook()
                await asyncio.sleep(.02)
                self.assertIsNotNone(bot.health.runner)
                self.assertTrue(all(loop.is_running() for loop in bot.service_loops()))
                self.assertIn('retry pending',bot.command_sync_status)
                await bot.close()
                self.assertTrue(bot.command_sync_task.done())


class ReleaseAndBackupChecks(unittest.TestCase):
    def test_manifest_rejects_unlisted_runtime_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'data').mkdir()
            (root/'requirements.txt').write_text('')
            (root/'bot.py').write_text('pass\n')
            (root/'data/build.json').write_text(json.dumps(manifest('test',root)))
            (root/'unexpected_runtime.py').write_text('pass\n')
            self.assertFalse(build_info(root)['verified'])
            self.assertIn('unexpected_runtime.py',build_info(root)['changed_files'])

    def test_full_package_can_be_verified_and_private_extra_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'root'
            root.mkdir()
            (root/'data').mkdir()
            for name in ('bot.py','requirements.txt','README.md','Procfile','.python-version','.env.example'):
                (root/name).write_text('synthetic public file\n')
            (root/'data/build.json').write_text(json.dumps(manifest('test',root)))
            archive=Path(folder)/'package.zip'
            build_package(archive,root)
            self.assertTrue(check_package(archive)['verified'])
            with zipfile.ZipFile(archive,'a') as output:
                output.writestr('.env','PRIVATE_SENTINEL')
            with self.assertRaises(ValueError):
                check_package(archive)

    def test_offline_compaction_refuses_running_instance(self):
        with tempfile.TemporaryDirectory() as folder:
            store=BotStore(Path(folder)/'bot.sqlite3')
            try:
                with acquire_lease(folder):
                    with self.assertRaises((RuntimeError,ValueError,OSError)):
                        compact_state(folder)
                self.assertEqual(store.connection.execute('PRAGMA quick_check').fetchone()[0],'ok')
            finally:
                store.close()

    @unittest.skipUnless(shutil.which('age') and shutil.which('age-keygen'),'optional age tools not installed')
    def test_encrypted_export_roundtrip_uses_disposable_keys_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            identity=root/'identity.agekey'
            subprocess.run(['age-keygen','-o',str(identity)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            recipient=subprocess.run(['age-keygen','-y',str(identity)],check=True,capture_output=True,text=True).stdout.strip()
            store=BotStore(root/'bot.sqlite3')
            try:
                store.set('synthetic-recovery','preserved')
                snapshot,_=make_snapshot(store.path)
                output=root/'snapshot.age'
                result=encrypt_snapshot(snapshot,output,recipient)
                self.assertTrue(result['encrypted'])
                self.assertFalse(result['uploaded'])
                restored=root/'decoded.sqlite3'
                subprocess.run(['age','--decrypt','--identity',str(identity),'--output',str(restored),str(output)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                self.assertTrue(check_restore(restored,temporary_parent=root)['verified'])
                with self.assertRaises(ValueError):
                    encrypt_snapshot(snapshot,output,recipient)
            finally:
                store.close()
