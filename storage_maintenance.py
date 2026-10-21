"""Bounded local SQLite snapshots; never replace the live database automatically."""

import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

BACKUP_INTERVAL = 86400
MIN_FREE_BYTES = 16 * 1024 * 1024


def verify_database(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as database:
        result = database.execute('PRAGMA quick_check').fetchall()
        if result != [('ok',)]:
            raise sqlite3.DatabaseError('A verificação de integridade do banco falhou.')
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'scores', 'awards', 'metadata'} <= tables:
            raise sqlite3.DatabaseError('O arquivo não contém o banco de pontos esperado.')


def snapshot_database(source: Path, destination: Path, *, timeout=10):
    """Copy committed data through SQLite; keep an existing snapshot on any failure."""
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError('A cópia não pode substituir o banco em uso.')
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    required = source.stat().st_size + MIN_FREE_BYTES
    if shutil.disk_usage(destination.parent).free < required:
        raise OSError('Espaço insuficiente para uma cópia segura; o banco e a cópia anterior foram preservados.')
    descriptor, name = tempfile.mkstemp(prefix='.scores-backup-', suffix='.sqlite3', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if time.monotonic() >= deadline:
            raise TimeoutError('A cópia excedeu o tempo permitido; a anterior foi preservada.')

    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=1)) as original:
            with closing(sqlite3.connect(temporary)) as copied:
                original.backup(copied, pages=128, progress=progress, sleep=.01)
        verify_database(temporary)
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def maintain_storage(database: Path, *, now=None):
    """Called in a worker thread; at most one daily snapshot is retained."""
    now = time.time() if now is None else now
    backup = database.parent / 'backups' / 'scores-latest.sqlite3'
    free = shutil.disk_usage(database.parent).free
    size = database.stat().st_size
    report = {'database_bytes': size, 'free_bytes': free, 'backup': 'fresh'}
    if not backup.exists() or now - backup.stat().st_mtime >= BACKUP_INTERVAL:
        snapshot_database(database, backup)
        report['backup'] = 'created'
    report['backup_bytes'] = backup.stat().st_size
    return report
