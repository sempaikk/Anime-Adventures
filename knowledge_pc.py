"""Windows/Linux companion: outbound WSS only, Q&A data and Groq on this PC."""

import argparse
import asyncio
from contextlib import closing
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import aiohttp

from game_knowledge import GameKnowledge, GameAnswerBackend
from knowledge_migration import MAX_BUNDLE, import_bundle
from knowledge_remote import ROUTE

DEFAULT_DIRECTORY = r'D:\Armazenamento do Bot'
DEFAULT_URL = 'https://7g2x14fnpa.apps.bot-hosting.cloud'
CONFIG = 'pc-knowledge.private.json'


def validate_url(value, *, allow_loopback=False):
    parsed = urlsplit(value)
    local = allow_loopback and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
    if (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')) or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError('Use the public HTTPS origin, without a path, password or query string.')
    return value.rstrip('/')


class PCStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'knowledge-controls.sqlite3'
        self.connection = sqlite3.connect(self.path)
        self.connection.execute('CREATE TABLE IF NOT EXISTS tier_meta(key TEXT PRIMARY KEY,value TEXT)')
        self.connection.commit()
        self.clock = time.time

    def get(self, key):
        row = self.connection.execute('SELECT value FROM tier_meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def set(self, key, value):
        with self.connection:
            self.connection.execute('INSERT INTO tier_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))

    def close(self):
        self.connection.close()


class Worker:
    def __init__(self, directory, config, *, backend=None):
        self.directory = Path(directory)
        self.config = config
        self.store = PCStore(self.directory)
        self.health = SimpleNamespace(storage_level='ok')
        # No 64 MiB archive cap on the PC. SQLite pages grow as used; the 1 GiB
        # free-space margin stops collection without evicting source history.
        self.knowledge = GameKnowledge(self, backend=backend or GameAnswerBackend(api_key=config['groq_api_key']),
                                       max_bytes=8 * 1024**4, free_margin_mb=1024)
        self.knowledge.ensure_wiki()
        self.tasks = set()
        self.backup_at = 0

    def status(self):
        info = self.knowledge.statistics()
        info.pop('days', None)
        last = self.store.get('ask_last_success')
        info.update(cursor=self.knowledge.get_meta('source-cursor'), last_answer=float(last) if last else None)
        return info

    async def handle(self, ws, data):
        ident = data.get('id')
        if not isinstance(ident, str) or len(ident) != 32 or data.get('type') != 'request':
            raise ValueError('Invalid request')
        method, payload = data.get('method'), data.get('payload')
        if not isinstance(payload, dict):
            raise ValueError('Invalid payload')
        try:
            if method == 'ask':
                actor = str(payload.get('actor_id', ''))
                if not actor.isdecimal() or len(actor) > 22:
                    raise ValueError('Invalid request')
                result = await self.knowledge.ask(payload.get('question', ''), actor_id=actor, locale=payload.get('locale', 'en-US'))
            elif method == 'ingest':
                result = {'saved': self.knowledge.ingest(payload), 'status': self.status()}
            elif method == 'checkpoint':
                self.knowledge.checkpoint(payload)
                result = {'status': self.status()}
            else:
                raise ValueError('Unknown request')
            await ws.send_json({'type': 'result', 'id': ident, 'result': result})
        except ValueError as error:
            await ws.send_json({'type': 'result', 'id': ident, 'error': str(error)[:300]})
        except Exception:
            await ws.send_json({'type': 'result', 'id': ident, 'error': 'The answer service is temporarily unavailable. Please try again later.'})

    async def heartbeat(self, ws):
        while not ws.closed:
            self.knowledge.prune()
            if time.monotonic() - self.backup_at > 900:
                if shutil.disk_usage(self.directory).free > self.knowledge.used_bytes() + 1024**3:
                    try:
                        await asyncio.to_thread(self.knowledge.backup)
                    except (OSError, sqlite3.Error, TimeoutError, ValueError):
                        print('Knowledge backup postponed; the existing archive is preserved.', flush=True)
                self.backup_at = time.monotonic()
            await ws.send_json({'type': 'status', 'status': self.status()})
            await asyncio.sleep(5)

    async def connection(self, session, url):
        receipt_path = self.directory / 'migration-receipt.json'
        receipt = json.loads(receipt_path.read_text())['id'] if receipt_path.exists() else None
        async with session.ws_connect(url + ROUTE, heartbeat=5, max_msg_size=32768) as ws:
            await ws.send_json({'type': 'hello', 'protocol': 1, 'migration_id': receipt, 'status': self.status()})
            accepted = await asyncio.wait_for(ws.receive_json(), 20)
            if accepted != {'type': 'accepted', 'protocol': 1}:
                raise ValueError('The host did not accept this worker.')
            print('Connected. /ask is available while this program and the internet remain online.', flush=True)
            heartbeat = asyncio.create_task(self.heartbeat(ws))
            try:
                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        break
                    data = json.loads(message.data)
                    if data.get('method') == 'ask':
                        # Only one inference at once; ingest/checkpoints continue
                        # in receive order while Groq is answering.
                        if self.tasks:
                            await ws.send_json({'type': 'result', 'id': data.get('id'), 'error': 'The answer service is busy. Please try again shortly.'})
                            continue
                        task = asyncio.create_task(self.handle(ws, data))
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)
                    else:
                        await self.handle(ws, data)
            finally:
                heartbeat.cancel()
                for task in self.tasks:
                    task.cancel()
                await asyncio.gather(heartbeat, *self.tasks, return_exceptions=True)
                self.tasks.clear()

    def close(self):
        self.knowledge.close()
        self.store.close()


async def download_migration(session, url, directory):
    directory = Path(directory)
    if (directory / 'migration-receipt.json').exists():
        return
    if (directory / 'knowledge.sqlite3').exists():
        raise ValueError('Unconfirmed existing PC database preserved. Check its migration receipt before continuing.')
    temporary = directory / 'transfer.download'
    try:
        async with session.get(url + '/knowledge/migration', allow_redirects=False) as response:
            if response.status == 204:
                return
            if response.status != 200 or (response.content_length is not None and response.content_length > MAX_BUNDLE):
                raise ValueError('Migration is unavailable. Confirm PC mode and the shared secret on the host.')
            received = 0
            with temporary.open('wb') as stream:
                async for chunk in response.content.iter_chunked(65536):
                    received += len(chunk)
                    if received > MAX_BUNDLE:
                        raise ValueError('Migration download exceeded its size limit.')
                    stream.write(chunk)
        receipt = import_bundle(temporary, directory)
        print(f"Import verified: {receipt['messages']} messages and {receipt['articles']} wiki articles. Hosted originals remain preserved.", flush=True)
    finally:
        temporary.unlink(missing_ok=True)


async def run(directory, config, *, finalize=False, allow_loopback=False):
    url = validate_url(config['bot_url'], allow_loopback=allow_loopback)
    timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=120)
    async with aiohttp.ClientSession(headers={'Authorization': 'Bearer ' + config['bridge_secret']}, timeout=timeout) as session:
        if finalize:
            receipt = json.loads((directory / 'migration-receipt.json').read_text())
            async with session.post(url + '/knowledge/migration/finalize', json={'migration_id': receipt['id']}, allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError('Keep the verified PC worker connected and test /ask before finalizing.')
                print('Hosted Q&A database and backup removed. Other bot data was not changed.')
            return
        worker = None
        delay = 5
        try:
            while True:
                try:
                    if worker is None:
                        await download_migration(session, url, directory)
                        worker = Worker(directory, config)
                        receipt = directory / 'migration-receipt.json'
                        if not receipt.exists():
                            receipt.write_text(json.dumps({'schema': 1, 'id': None, 'fresh': True}))
                    await worker.connection(session, url)
                    delay = 5
                except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
                    print('Connection unavailable. /ask is offline; reconnecting automatically.', flush=True)
                await asyncio.sleep(delay)
                delay = min(60, delay * 2)
        finally:
            if worker:
                worker.close()


def setup(directory, url):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CONFIG
    if path.exists():
        print('Existing private configuration preserved. Open it locally to change settings.')
        return
    url = validate_url(url)
    secret = secrets.token_urlsafe(48)
    key = getpass.getpass('Paste your existing Groq API key (hidden): ').strip()
    if not key:
        raise ValueError('A Groq API key is required. No configuration was written.')
    config = {'schema': 1, 'bot_url': url, 'bridge_secret': secret, 'groq_api_key': key}
    with path.open('x', encoding='utf-8') as stream:
        json.dump(config, stream, indent=2)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    # This one-use file is private and is not automatically uploaded anywhere.
    (directory / 'HOSTING-SETUP.private.txt').write_text(
        'Add these variables to the existing bot hosting instance:\n\nKNOWLEDGE_MODE=pc\nKNOWLEDGE_BRIDGE_SECRET=' + secret +
        '\n\nMark the bridge secret as Secret. Keep DATA_DIR unchanged. Restart the hosted bot, then start the PC worker.\n'
        'Do not share this file, pc-knowledge.private.json, databases or backups.\n', encoding='utf-8')
    print('Private configuration saved. Follow HOSTING-SETUP.private.txt locally; do not send its contents to chat or GitHub.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default=DEFAULT_DIRECTORY)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--finalize-host', action='store_true')
    args = parser.parse_args()
    directory = Path(args.directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.setup:
        setup(directory, args.url)
        return
    config = json.loads((directory / CONFIG).read_text(encoding='utf-8'))
    if config.get('schema') != 1 or not 32 <= len(config.get('bridge_secret', '')) <= 200 or not config.get('groq_api_key'):
        raise ValueError('Invalid private PC configuration.')
    # Cross-platform one-process guard. Finalization is a separate short command.
    lock = None
    try:
        if not args.finalize_host:
            lock = (directory / 'knowledge-worker.lock').open('a+b')
            if os.name == 'nt':
                import msvcrt
                lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(run(directory, config, finalize=args.finalize_host))
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nPC worker stopped. /ask will be unavailable until it is restarted.')
    except (ValueError, OSError, sqlite3.Error, KeyError):
        print('Setup or archive needs attention. Existing files were preserved. Check docs/pc-knowledge.md; no private values have been logged.')
        raise SystemExit(1)
