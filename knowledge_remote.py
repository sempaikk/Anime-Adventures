"""Authenticated outbound PC worker bridge; no hosted Q&A archive or AI fallback."""

import asyncio
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import time

from aiohttp import web, WSMsgType

from game_sources import QUESTIONS_CHANNEL_ID
from knowledge_migration import export_bundle, migration_id

OFFLINE = 'The question service is temporarily unavailable. Please try again later.'
ROUTE = '/knowledge/worker'


class RemoteKnowledge:
    remote = True

    def __init__(self, bot, secret=None):
        self.bot = bot
        self.secret = secret if secret is not None else os.getenv('KNOWLEDGE_BRIDGE_SECRET', '')
        if not 32 <= len(self.secret) <= 200:
            raise ValueError('Set a private KNOWLEDGE_BRIDGE_SECRET of at least 32 characters.')
        self.ws = None
        self.pending = {}
        self.last_status = 0
        self.info = {}
        self.cursor = None
        self.receipt = None
        self.reader_status = 'pc_offline'
        self.ask_lock = asyncio.Lock()
        self.connect_lock = asyncio.Lock()
        self.export_lock = asyncio.Lock()
        self._closed = False

    @property
    def online(self):
        return bool(self.ws and not self.ws.closed and time.monotonic() - self.last_status < 20)

    @property
    def paused(self):
        return not self.online or bool(self.info.get('paused', True))

    def authenticate(self, request):
        expected = 'Bearer ' + self.secret
        if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), expected.encode()):
            raise web.HTTPUnauthorized(text='Unauthorized')

    def install_routes(self, app):
        app.router.add_get(ROUTE, self.worker)
        app.router.add_get('/knowledge/migration', self.export)
        app.router.add_post('/knowledge/migration/finalize', self.finalize)

    def controls(self):
        return {r['key']: r['value'] for r in self.bot.store.connection.execute("SELECT key,value FROM tier_meta WHERE key IN ('budget','ask_last_success','last_connection_success') OR key LIKE 'ask-rate:%'")}

    def expected_migration(self):
        path = self.bot.directory / 'knowledge.sqlite3'
        return migration_id(path, self.controls()) if path.exists() else None

    async def export(self, request):
        self.authenticate(request)
        async with self.export_lock:
            source = self.bot.directory / 'knowledge.sqlite3'
            if not source.exists():
                return web.Response(status=204, headers={'Cache-Control': 'no-store'})
            # The local service is not instantiated in PC mode: this DB is frozen.
            temporary = tempfile.TemporaryDirectory(prefix='knowledge-transfer-', dir=self.bot.directory)
            try:
                target = Path(temporary.name) / 'transfer.zip'
                manifest = await asyncio.to_thread(export_bundle, source, self.controls(), target)
                response = web.StreamResponse(headers={'Content-Type': 'application/zip', 'Cache-Control': 'no-store',
                                                       'X-Migration-ID': manifest['id']})
                response.content_length = target.stat().st_size
                await response.prepare(request)
                with target.open('rb') as stream:
                    while chunk := stream.read(65536):
                        await response.write(chunk)
                await response.write_eof()
                return response
            except (ValueError, OSError):
                raise web.HTTPConflict(text='The preserved archive needs operator attention.') from None
            finally:
                temporary.cleanup()

    async def finalize(self, request):
        self.authenticate(request)
        async with self.export_lock:
            data = await request.json()
            expected = self.expected_migration()
            if not self.online or not expected or self.receipt != expected or data != {'migration_id': expected}:
                raise web.HTTPConflict(text='A verified imported archive must be connected first.')
            # The PC operator invokes this only after testing /ask. Never touch the
            # main tierlist.sqlite3, media, or any path supplied over the network.
            for name in ('knowledge.sqlite3', 'knowledge-backup.sqlite3', 'knowledge-backup.sqlite3.tmp'):
                path = self.bot.directory / name
                if path.is_symlink():
                    raise web.HTTPConflict(text='Unexpected archive path; originals preserved.')
            receipt = self.bot.directory / 'knowledge-migration-complete.json'
            receipt.write_text(json.dumps({'migration_id': expected, 'completed_at': time.time()}))
            for name in ('knowledge-backup.sqlite3.tmp', 'knowledge-backup.sqlite3', 'knowledge.sqlite3'):
                (self.bot.directory / name).unlink(missing_ok=True)
            with self.bot.store.connection:
                self.bot.store.connection.execute("DELETE FROM tier_meta WHERE key IN ('budget','ask_last_success') OR key LIKE 'ask-rate:%'")
            return web.json_response({'completed': True}, headers={'Cache-Control': 'no-store'})

    def restart_reader(self):
        reader = getattr(self.bot, 'banners', None)
        process = getattr(reader, 'process', None)
        if process and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def update_status(self, data):
        if not isinstance(data, dict) or not isinstance(data.get('paused'), bool):
            raise ValueError('Invalid worker status')
        for name in ('messages', 'bytes', 'used_bytes', 'limit'):
            if type(data.get(name)) is not int or not 0 <= data[name] <= 2**54:
                raise ValueError('Invalid worker status')
        cursor = data.get('cursor')
        if cursor is not None and (not isinstance(cursor, str) or not cursor.isdecimal() or len(cursor) > 22):
            raise ValueError('Invalid cursor')
        before = self.paused
        self.info = {key: data[key] for key in ('messages','bytes','used_bytes','limit','paused')}
        self.info['days'] = []  # No source text or growing history on the host.
        self.info['last_answer'] = data.get('last_answer') if isinstance(data.get('last_answer'), (int,float)) else None
        self.cursor = cursor
        self.last_status = time.monotonic()
        if before != self.paused:
            self.restart_reader()

    async def worker(self, request):
        self.authenticate(request)
        if self.connect_lock.locked() or self._closed:
            raise web.HTTPConflict(text='A worker is already connected.')
        async with self.connect_lock:
            ws = web.WebSocketResponse(heartbeat=5, max_msg_size=32768)
            await ws.prepare(request)
            self.ws = ws
            try:
                hello = await asyncio.wait_for(ws.receive_json(), 15)
                expected = self.expected_migration()
                if not isinstance(hello, dict) or hello.get('type') != 'hello' or hello.get('protocol') != 1 or (expected and hello.get('migration_id') != expected):
                    await ws.close(code=1008, message=b'Import the preserved archive first.')
                    return ws
                self.receipt = hello.get('migration_id')
                self.update_status(hello.get('status'))
                await ws.send_json({'type': 'accepted', 'protocol': 1})
                self.restart_reader()
                async for message in ws:
                    if message.type != WSMsgType.TEXT:
                        break
                    data = json.loads(message.data)
                    if not isinstance(data, dict):
                        raise ValueError('Invalid worker response')
                    if data.get('type') == 'status':
                        self.update_status(data.get('status'))
                    elif data.get('type') == 'result':
                        future = self.pending.get(data.get('id'))
                        if future and not future.done():
                            future.set_result(data)
                    else:
                        raise ValueError('Unknown worker response')
            except (ValueError, TypeError, KeyError, asyncio.TimeoutError):
                await ws.close(code=1008, message=b'Invalid worker protocol.')
            finally:
                self.ws = None
                self.last_status = 0
                self.cursor = None
                self.restart_reader()
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(ValueError(OFFLINE))
            return ws

    async def call(self, method, payload, timeout=15):
        if not self.online or len(self.pending) >= 8:
            raise ValueError(OFFLINE)
        ident = secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.ws.send_json({'type': 'request', 'id': ident, 'method': method, 'payload': payload})
            response = await asyncio.wait_for(future, timeout)
            if response.get('error'):
                error = response['error']
                raise ValueError(error if isinstance(error, str) and len(error) <= 300 else OFFLINE)
            return response.get('result')
        except (asyncio.TimeoutError, ConnectionError, RuntimeError):
            raise ValueError(OFFLINE) from None
        finally:
            self.pending.pop(ident, None)

    async def ask(self, question, *, actor_id, locale='en-US'):
        if not 5 <= len(str(question)) <= 500:
            raise ValueError('Enter a question between 5 and 500 characters.')
        if self.ask_lock.locked():
            raise ValueError('The answer service is busy. Please try again shortly.')
        async with self.ask_lock:
            result = await self.call('ask', {'question': str(question), 'actor_id': str(actor_id), 'locale': str(locale)}, timeout=110)
            if not isinstance(result, str) or not 5 <= len(result) <= 6000:
                raise ValueError(OFFLINE)
            return result

    async def ingest(self, event):
        if str(event.get('channel_id')) != str(QUESTIONS_CHANNEL_ID) or not self.online or (self.paused and event.get('event') != 'question_delete'):
            return False
        try:
            result = await self.call('ingest', event)
            if not isinstance(result, dict):
                raise ValueError(OFFLINE)
            self.update_status(result['status'])
            return result.get('saved', False)
        except ValueError:
            if self.ws:
                await self.ws.close()
            return False

    async def checkpoint(self, event):
        if str(event.get('channel_id')) != str(QUESTIONS_CHANNEL_ID) or self.paused:
            return
        try:
            result = await self.call('checkpoint', event)
            self.update_status(result['status'])
        except (ValueError, KeyError, TypeError):
            if self.ws:
                await self.ws.close()

    def get_meta(self, key):
        return self.cursor if key == 'source-cursor' and self.online else None

    def statistics(self):
        return {'messages': 0, 'bytes': 0, 'used_bytes': 0, 'limit': 0, 'days': [],
                **self.info, 'paused': self.paused, 'remote': True, 'online': self.online}

    def ensure_wiki(self): pass
    def prune(self): pass
    def backup(self): pass

    def close(self):
        self._closed = True

    async def aclose(self):
        self._closed = True
        if self.ws:
            await self.ws.close(code=1001, message=b'Host restarting.')
