"""Private migration fixtures preserve active state while retired schemas leave the live file."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bot_store import BotStore
from bot_storage import acquire_lease, prepare_database, make_snapshot, restore_snapshot
from banner_relay import BannerRelay
from global_store import GlobalStore
from storage_maintenance import snapshot_database


class MigrationCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def legacy(self, name='previous.sqlite3'):
        path=self.root/name
        base=BotStore(path,clock=lambda:2_000_000_000)
        relay=GlobalStore(base)
        relay.configure(1,10,110,'synthetic-private-hook',0)
        relay.consent(7)
        base.set('global-network-paused','1')
        base.set('global-owner-alerts','0')
        base.set('community-update:1554953245204422807:test','sent-receipt')
        base.set('banner-vote-order-cutoff:1:20','900')
        base.set('banner-vote-order-scan:1:20','1')
        base.set('banner-vote-emoji:synthetic','301')
        bot=SimpleNamespace(store=base)
        banners=BannerRelay(bot)
        daily=BannerRelay(bot,kind='daily')
        banners.configure(1,20)
        daily.configure(1,30)
        with base.connection:
            base.connection.execute("INSERT INTO banner_assets VALUES('image','png',?)",(b'original-image-bytes',))
            base.connection.execute("INSERT INTO banner_events VALUES('event','100',2000000000,'[\"image\"]')")
            base.connection.execute("INSERT INTO banner_jobs(event_id,guild_id,channel_id,state,attempted_at) VALUES('event','1','20','uncertain',2000000001)")
            base.connection.execute("INSERT INTO daily_source_head VALUES(1,'200')")
            base.connection.execute("INSERT INTO daily_current VALUES(1,'daily-event','200',2000000000)")
            base.connection.execute("INSERT INTO banner_vote_order_repairs(guild_id,channel_id,message_id,phase,cleared,seeded) VALUES('1','20','900','seed',7,1)")
            base.connection.execute("INSERT INTO global_messages(id,guild_id,channel_id,user_id,payload,fingerprint,created,updated,expires) VALUES('500','1','10','7','PRIVATE_CACHE_SENTINEL','fingerprint',2000000000,2000000000,2000003600)")
            base.connection.execute("INSERT INTO global_deliveries(source_id,channel_id,guild_id,hook_id,state,receipts,revision,attempted) VALUES('500','40','2','140','uncertain','[\"501\"]',1,2000000001)")
            base.connection.execute('CREATE TABLE retired_entries(id INTEGER PRIMARY KEY,content TEXT)')
            base.connection.execute("INSERT INTO retired_entries VALUES(1,'saved historical contribution')")
            base.connection.execute('CREATE TABLE previous_actions(id INTEGER PRIMARY KEY,kind TEXT,actor_id TEXT,reason TEXT,created_at REAL)')
            base.connection.executemany('INSERT INTO previous_actions VALUES(?,?,?,?,?)',[
                (1,'global-network-pause','7','saved moderation reason',2000000000),
                (2,'retired-analysis','7','historical analysis',1999999999)])
            base.connection.execute('ALTER TABLE bot_meta RENAME TO previous_settings')
            base.connection.execute('DROP TABLE bot_audit')
        base.close()
        return path

    def test_migrates_active_configuration_receipts_images_and_metadata_with_a_private_backup(self):
        original=self.legacy()
        with acquire_lease(self.root):
            target=prepare_database(self.root)
        self.assertEqual(target.name,'bot.sqlite3')
        self.assertFalse(original.exists())
        base=BotStore(target)
        try:
            self.assertEqual(base.get('global-network-paused'),'1')
            self.assertEqual(base.get('community-update:1554953245204422807:test'),'sent-receipt')
            self.assertEqual(base.get('banner-vote-order-scan:1:20'),'1')
            self.assertEqual(base.connection.execute('SELECT state,receipts FROM global_deliveries').fetchone()[:],('uncertain','["501"]'))
            self.assertEqual(base.connection.execute('SELECT state,attempted_at FROM banner_jobs').fetchone()[:],('uncertain',2000000001))
            self.assertEqual(base.connection.execute('SELECT phase,cleared,seeded FROM banner_vote_order_repairs').fetchone()[:],('seed',7,1))
            self.assertEqual(base.connection.execute('SELECT data FROM banner_assets').fetchone()[0],b'original-image-bytes')
            self.assertEqual(base.connection.execute('SELECT payload FROM global_messages').fetchone()[0],'PRIVATE_CACHE_SENTINEL')
            self.assertTrue(base.connection.execute('SELECT 1 FROM global_consents WHERE user_id=7').fetchone())
            tables={row[0] for row in base.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn('retired_entries',tables)
            self.assertNotIn('previous_settings',tables)
            self.assertEqual(base.connection.execute('SELECT source_message FROM daily_current').fetchone()[0],'200')
            audit=base.rows('SELECT kind,actor_id,reason FROM bot_audit')
            self.assertEqual(audit,[{'kind':'global-network-pause','actor_id':'7','reason':'saved moderation reason'}])
        finally:
            base.close()
        backup=self.root/'backups/before-cleanup.sqlite3'
        with closing(sqlite3.connect(backup)) as copied:
            self.assertEqual(copied.execute('SELECT content FROM retired_entries').fetchone()[0],'saved historical contribution')
            self.assertEqual(copied.execute('SELECT payload FROM global_messages').fetchone()[0],'{}')
        self.assertNotIn(b'PRIVATE_CACHE_SENTINEL',backup.read_bytes())

    def test_running_twice_does_not_repeat_migration_or_reset_receipts(self):
        self.legacy()
        with acquire_lease(self.root):
            path=prepare_database(self.root)
            before=path.read_bytes()
            self.assertEqual(prepare_database(self.root),path)
            self.assertEqual(path.read_bytes(),before)

    def test_previous_process_lock_blocks_migration(self):
        self.legacy()
        import fcntl
        with (self.root/'previous.lock').open('a+') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                acquire_lease(self.root)
        self.assertFalse((self.root/'bot.sqlite3').exists())

    def test_not_enough_space_leaves_original_data_untouched(self):
        path=self.legacy()
        before=path.read_bytes()
        with patch('bot_storage.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaises(OSError):
                prepare_database(self.root)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'bot.sqlite3').exists())

    def test_hosting_quota_is_respected_even_when_the_physical_disk_is_large(self):
        path=self.legacy()
        before=path.read_bytes()
        with self.assertRaises(OSError):
            prepare_database(self.root,available_space=lambda:0)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'bot.sqlite3').exists())

    def test_failed_staging_verification_never_replaces_the_original(self):
        path=self.legacy()
        before=path.read_bytes()
        with patch('bot_storage.verify_database',side_effect=sqlite3.DatabaseError('synthetic verification failure')):
            with self.assertRaises(sqlite3.DatabaseError):
                prepare_database(self.root)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'bot.sqlite3').exists())
        self.assertFalse(list(self.root.glob('.bot-migration-*')))

    def test_ambiguous_databases_require_resolution_without_picking_or_deleting_one(self):
        first=self.legacy('first.sqlite3')
        second=self.legacy('second.sqlite3')
        with self.assertRaises(RuntimeError):
            prepare_database(self.root)
        self.assertTrue(first.exists() and second.exists())
        self.assertFalse((self.root/'bot.sqlite3').exists())

    def test_conflicting_settings_abort_the_migration(self):
        path=self.legacy()
        with closing(sqlite3.connect(path)) as database:
            database.execute('CREATE TABLE other_settings(key TEXT,value TEXT)')
            database.execute("INSERT INTO other_settings VALUES('global-network-paused','different')")
            database.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            prepare_database(self.root)
        self.assertTrue(path.exists())
        self.assertFalse((self.root/'bot.sqlite3').exists())

    def test_modern_state_is_not_overwritten_by_another_database(self):
        base=BotStore(self.root/'bot.sqlite3')
        base.set('global-owner-alerts','0')
        base.close()
        old=self.legacy()
        path=prepare_database(self.root)
        base=BotStore(path)
        try:
            self.assertEqual(base.get('global-owner-alerts'),'0')
        finally:
            base.close()
        self.assertTrue(old.exists())

    def test_modern_corrupt_state_is_not_silently_replaced(self):
        path=self.root/'bot.sqlite3'
        path.write_bytes(b'corrupt-state-sentinel')
        with self.assertRaises(sqlite3.DatabaseError):
            prepare_database(self.root)
        self.assertEqual(path.read_bytes(),b'corrupt-state-sentinel')

    def test_regular_backup_and_offline_restore_preserve_settings(self):
        base=BotStore(self.root/'bot.sqlite3')
        base.set('global-owner-alerts','0')
        base.close()
        snapshot,status=make_snapshot(self.root/'bot.sqlite3')
        self.assertEqual(status,'created')
        restored=restore_snapshot(snapshot,self.root/'restored')
        base=BotStore(restored)
        try:
            self.assertEqual(base.get('global-owner-alerts'),'0')
        finally:
            base.close()

    def test_failed_snapshot_transform_keeps_the_previous_snapshot(self):
        base=BotStore(self.root/'bot.sqlite3')
        base.set('global-owner-alerts','0')
        snapshot,_=make_snapshot(base.path)
        before=snapshot.read_bytes()
        base.set('global-owner-alerts','1')
        with patch('bot_storage._scrub_snapshot',side_effect=OSError('synthetic snapshot failure')) as transform:
            with self.assertRaises(OSError):
                snapshot_database(base.path,snapshot,transform=transform)
        self.assertEqual(snapshot.read_bytes(),before)
        self.assertEqual(base.get('global-owner-alerts'),'1')
        base.close()


if __name__=='__main__':
    unittest.main()
