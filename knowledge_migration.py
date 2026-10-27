"""Fixed-file, verified transfer of Q&A state. Never transfers the bot's main DB."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

MAX_DATABASE = 128 * 1024 * 1024
MAX_BUNDLE = MAX_DATABASE + 2 * 1024 * 1024
REQUIRED = {'knowledge_chat', 'knowledge_chat_search', 'knowledge_wiki', 'knowledge_meta', 'knowledge_daily'}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inspect_database(path):
    path = Path(path).resolve()
    if not 0 < path.stat().st_size <= MAX_DATABASE:
        raise ValueError('Migration database size is outside the supported range.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Migration database integrity check failed.')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED <= tables:
            raise ValueError('This is not a game knowledge database.')
        cursor = db.execute("SELECT value FROM knowledge_meta WHERE key='source-cursor'").fetchone()
        return {'messages': db.execute('SELECT COUNT(*) FROM knowledge_chat').fetchone()[0],
                'articles': db.execute('SELECT COUNT(*) FROM knowledge_wiki').fetchone()[0],
                'cursor': cursor[0] if cursor else None}


def migration_id(path, controls):
    # The frozen source DB identifies the transfer across host restarts. Other
    # bot diagnostics may still update the shared controls DB independently.
    return digest(path)


def export_bundle(source, controls, target):
    source, target = Path(source), Path(target)
    if source.is_symlink() or source.with_name(source.name + '-wal').exists():
        raise ValueError('Stop local Q&A collection before migration.')
    original = inspect_database(source)
    ident = migration_id(source, controls)
    with tempfile.TemporaryDirectory(prefix='knowledge-export-', dir=target.parent) as temporary:
        snapshot = Path(temporary) / 'knowledge.sqlite3'
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
        if inspect_database(snapshot) != original:
            raise ValueError('Migration snapshot changed unexpectedly.')
        manifest = {'schema': 1, 'id': ident, 'database_sha256': digest(snapshot), **original}
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(snapshot, 'knowledge.sqlite3')
            bundle.writestr('controls.json', json.dumps(controls, sort_keys=True))
            bundle.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
    return manifest


def import_bundle(bundle_path, directory):
    directory = Path(directory)
    target = directory / 'knowledge.sqlite3'
    if target.exists() or (directory / 'knowledge-controls.sqlite3').exists():
        raise ValueError('Existing PC state was preserved; import requires an unused data folder.')
    if Path(bundle_path).stat().st_size > MAX_BUNDLE:
        raise ValueError('Migration bundle is too large.')
    with tempfile.TemporaryDirectory(prefix='knowledge-import-', dir=directory) as temporary:
        temporary = Path(temporary)
        with zipfile.ZipFile(bundle_path) as bundle:
            entries = bundle.infolist()
            if len(entries) != 3 or {entry.filename for entry in entries} != {'knowledge.sqlite3', 'controls.json', 'manifest.json'}:
                raise ValueError('Unexpected migration files.')
            if any(entry.file_size > (MAX_DATABASE if entry.filename == 'knowledge.sqlite3' else 65536) for entry in entries):
                raise ValueError('Migration contents exceed their size limit.')
            # Fixed names only; never extract paths supplied by an archive.
            for entry in entries:
                with bundle.open(entry) as source, (temporary / entry.filename).open('wb') as dest:
                    remaining = entry.file_size
                    while remaining:
                        chunk = source.read(min(65536, remaining))
                        if not chunk:
                            raise ValueError('Incomplete migration file.')
                        dest.write(chunk)
                        remaining -= len(chunk)
        manifest = json.loads((temporary / 'manifest.json').read_text())
        controls = json.loads((temporary / 'controls.json').read_text())
        if manifest.get('schema') != 1 or not isinstance(manifest.get('id'), str) or len(manifest['id']) != 64:
            raise ValueError('Invalid migration manifest.')
        if not isinstance(controls, dict) or len(controls) > 1000 or any(not isinstance(k, str) or not isinstance(v, str) or not (k in {'budget', 'ask_last_success', 'last_connection_success'} or k.startswith('ask-rate:')) for k, v in controls.items()):
            raise ValueError('Unexpected Q&A controls.')
        snapshot = temporary / 'knowledge.sqlite3'
        if digest(snapshot) != manifest.get('database_sha256') or any(inspect_database(snapshot)[key] != manifest.get(key) for key in ('messages', 'articles', 'cursor')):
            raise ValueError('Migration checksum or record counts do not match.')
        with closing(sqlite3.connect(temporary / 'knowledge-controls.sqlite3')) as db:
            db.execute('CREATE TABLE tier_meta(key TEXT PRIMARY KEY,value TEXT)')
            db.executemany('INSERT INTO tier_meta VALUES(?,?)', controls.items())
            db.commit()
        (temporary / 'receipt.json').write_text(json.dumps(manifest, indent=2))
        # A partial interruption is detected on the next start, never overwritten.
        snapshot.replace(target)
        (temporary / 'knowledge-controls.sqlite3').replace(directory / 'knowledge-controls.sqlite3')
        (temporary / 'receipt.json').replace(directory / 'migration-receipt.json')
    return manifest
