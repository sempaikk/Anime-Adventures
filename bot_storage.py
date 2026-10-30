"""Exclusive state ownership, verified migration and private database snapshots."""

from contextlib import closing
import fcntl
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from storage_maintenance import MIN_FREE_BYTES, snapshot_database, verify_database

ACTIVE_PREFIXES = ('global_', 'banner_', 'daily_', 'bot_')
REQUIRED_TABLES = {'bot_meta', 'bot_audit'}


class StateLease:
    def __init__(self, streams):
        self.streams = streams

    def close(self):
        for stream in reversed(self.streams):
            stream.close()
        self.streams.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def acquire_lease(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    streams = []
    try:
        # Also honor existing lock files from earlier deployments during migration.
        (directory / 'bot.lock').touch(exist_ok=True)
        for path in sorted(directory.glob('*.lock')):
            if path.is_symlink():
                raise ValueError('A state lock cannot be a symbolic link.')
            stream = path.open('a+')
            streams.append(stream)
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return StateLease(streams)
    except BaseException:
        for stream in streams:
            stream.close()
        raise


def _tables(database):
    return {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _scrub_snapshot(path):
    with closing(sqlite3.connect(path)) as database:
        database.execute('PRAGMA secure_delete=ON')
        if 'global_messages' in _tables(database):
            database.execute("UPDATE global_messages SET payload='{}'")
        if 'bot_case_followup' in _tables(database):
            database.execute('UPDATE bot_case_followup SET image=NULL,image_type=NULL,image_expires=NULL')
        database.commit()
        database.execute('VACUUM')


def prepare_database(directory, *, available_space=None):
    """Run under the state lease; recognize earlier databases by active schemas."""
    directory = Path(directory).resolve()
    target = directory / 'bot.sqlite3'
    if target.exists():
        verify_database(target, required_tables=REQUIRED_TABLES)
        return target
    candidates = []
    for path in directory.glob('*.sqlite3'):
        if path.is_symlink():
            continue
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as database:
                tables = _tables(database)
                if tables & {'global_channels', 'banner_targets', 'daily_targets'}:
                    if database.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise sqlite3.DatabaseError('Existing state failed verification; no new database was created.')
                    candidates.append(path)
        except sqlite3.DatabaseError:
            # A file with an unknown/corrupt schema must not be silently ignored.
            raise
    if len(candidates) > 1:
        raise RuntimeError('Multiple active databases were found; all files were preserved.')
    if not candidates:
        return target
    source = candidates[0]
    required = sum(path.stat().st_size for path in (source, Path(str(source) + '-wal')) if path.exists())
    free = shutil.disk_usage(directory).free
    if available_space is not None:
        free = min(free, available_space())
    if free < 2 * required + MIN_FREE_BYTES:
        raise OSError('Not enough free space for a verified migration; existing data was preserved.')
    backup = directory / 'backups' / 'before-cleanup.sqlite3'
    snapshot_database(source, backup, required_tables=set(), transform=_scrub_snapshot)
    handle, name = tempfile.mkstemp(prefix='.bot-migration-', suffix='.sqlite3', dir=directory)
    os.close(handle)
    staging = Path(name)
    try:
        snapshot_database(source, staging, required_tables=set())
        with closing(sqlite3.connect(staging)) as database:
            database.execute('CREATE TABLE IF NOT EXISTS bot_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            database.execute('''CREATE TABLE IF NOT EXISTS bot_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,actor_id TEXT NOT NULL,reason TEXT NOT NULL,created_at REAL NOT NULL)''')
            tables = _tables(database)
            for table in tables:
                columns = [row[1] for row in database.execute('PRAGMA table_info(' + _identifier(table) + ')')]
                if columns == ['key', 'value'] and not table.startswith(ACTIVE_PREFIXES):
                    if database.execute('SELECT 1 FROM ' + _identifier(table) + ' s JOIN bot_meta b ON b.key=s.key WHERE b.value<>s.value LIMIT 1').fetchone():
                        raise sqlite3.IntegrityError('Conflicting settings; existing state was preserved.')
                    database.execute('INSERT OR IGNORE INTO bot_meta SELECT key,value FROM ' + _identifier(table))
                if not table.startswith(ACTIVE_PREFIXES) and {'kind','actor_id','reason','created_at'} <= set(columns):
                    database.execute('INSERT INTO bot_audit(kind,actor_id,reason,created_at) '
                        + 'SELECT kind,actor_id,reason,created_at FROM ' + _identifier(table)
                        + " WHERE kind LIKE 'global-%' ORDER BY created_at")
            for table in tables:
                if not table.startswith(ACTIVE_PREFIXES):
                    database.execute('DROP TABLE ' + _identifier(table))
            database.commit()
            database.execute('VACUUM')
        verify_database(staging, required_tables=REQUIRED_TABLES)
        with staging.open('rb') as stream:
            os.fsync(stream.fileno())
        staging.replace(target)
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        # The new live copy and the verified private snapshot now both exist.
        for path in (source, Path(str(source) + '-wal'), Path(str(source) + '-shm')):
            path.unlink(missing_ok=True)
        return target
    finally:
        staging.unlink(missing_ok=True)


def make_snapshot(database, *, now=None):
    from storage_maintenance import maintain_storage
    database = Path(database)
    report = maintain_storage(database, now=now, required_tables=REQUIRED_TABLES, transform=_scrub_snapshot)
    snapshot = database.parent / 'backups' / (database.stem + '-latest.sqlite3')
    return snapshot, report['backup']


def maintain_bot_storage(database):
    snapshot, status = make_snapshot(database)
    usage = shutil.disk_usage(Path(database).parent)
    return {'database_bytes': Path(database).stat().st_size, 'free_bytes': usage.free,
            'total_bytes': usage.total, 'backup': status, 'backup_bytes': snapshot.stat().st_size,
            'backup_modified': snapshot.stat().st_mtime}


def restore_snapshot(snapshot, destination, *, replace=False):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'bot.sqlite3'
    with acquire_lease(destination):
        if target.exists() and not replace:
            raise ValueError('The database exists; stop the bot before replacing state.')
        snapshot_database(Path(snapshot), target, required_tables=REQUIRED_TABLES)
    return target
