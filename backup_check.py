"""Restore a snapshot into a disposable private directory, never over live state."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile

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
        return {'verified':True,'tables_checked':len(tables),'live_database_replaced':False,'network_used':False}
