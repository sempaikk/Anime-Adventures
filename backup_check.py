"""Restore a snapshot into a disposable private directory, never over live state."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import hashlib
import json

from bot_storage import restore_snapshot
from storage_maintenance import verify_database


def check_restore(snapshot, *, temporary_parent=None):
    snapshot=Path(snapshot)
    verify_database(snapshot)
    with tempfile.TemporaryDirectory(prefix='restore-check-',dir=temporary_parent) as folder:
        restored=restore_snapshot(snapshot,Path(folder)/'state')
        verify_database(restored)
        with closing(sqlite3.connect(snapshot.resolve().as_uri()+'?mode=ro',uri=True)) as original, closing(sqlite3.connect(restored.resolve().as_uri()+'?mode=ro',uri=True)) as copy:
            tables=[r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                name='"'+table.replace('"','""')+'"'
                if original.execute('SELECT count(*) FROM '+name).fetchone()!=copy.execute('SELECT count(*) FROM '+name).fetchone():
                    raise sqlite3.DatabaseError('Restored row counts do not match the verified snapshot.')
            preserved={table:([r[1] for r in original.execute('PRAGMA table_info("'+table+'")')],table_digest(original,table)) for table in tables if table in {
                'global_consents','global_channels','banner_targets','daily_targets','banner_config_versions',
                'daily_config_versions','daily_current','daily_source_head','banner_vote_backfill',
                'banner_vote_order_repairs','banner_image_receipts','global_receipts'}}
            for table in ('bot_tool_data','bot_tool_preferences','bot_tool_settings','bot_tool_history','bot_tool_parties','bot_tool_members'):
                if table in tables:
                    preserved[table]=([r[1] for r in original.execute('PRAGMA table_info("'+table+'")')],table_digest(original,table))
            if 'bot_tool_reminders' in tables:
                columns=['id','user','guild','nonce','generation','due']
                preserved['bot_tool_reminders']=(columns,table_digest(original,'bot_tool_reminders',columns))
        # Exercise application state readers/migrations on the disposable copy.
        # Never instantiate a Discord client or start source readers/tasks here.
        from bot_store import BotStore
        from global_store import GlobalStore
        from banner_relay import BannerRelay
        from types import SimpleNamespace
        base=BotStore(restored)
        try:
            GlobalStore(base)
            bot=SimpleNamespace(store=base)
            BannerRelay(bot)
            BannerRelay(bot,kind='daily')
            from adventure_store import AdventureStore
            AdventureStore(base)
            for table,(columns,digest) in preserved.items():
                if table_digest(base.connection,table,columns)!=digest:
                    raise sqlite3.DatabaseError('Recovered application state changed during the restore drill.')
        finally:
            base.close()
        return {'verified':True,'tables_checked':len(tables),'application_state_checked':len(preserved),
                'live_database_replaced':False,'network_used':False}


def table_digest(db,table,columns=None):
    name='"'+table.replace('"','""')+'"'
    digest=hashlib.sha256()
    # Only small metadata/receipt tables, never export values to the report.
    fields=','.join('"'+col.replace('"','""')+'"' for col in columns) if columns else '*'
    for row in db.execute('SELECT '+fields+' FROM '+name+' ORDER BY rowid'):
        digest.update(json.dumps(tuple(row),separators=(',',':'),default=str).encode())
        digest.update(b'\n')
    return digest.hexdigest()
