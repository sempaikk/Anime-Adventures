"""Real loopback bridge/PC integration with synthetic data and no external APIs."""

import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

import aiohttp

from community_bot import CommunityBot
from game_sources import QUESTIONS_CHANNEL_ID
from knowledge_migration import export_bundle, import_bundle, inspect_database, migration_id
from knowledge_pc import Worker, PCStore, validate_url, download_migration
from knowledge_remote import RemoteKnowledge, OFFLINE

SECRET = 'synthetic-bridge-secret-for-local-tests-only'


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = CommunityBot(self.root / 'host', archived_knowledge=True)
        self.app.knowledge.ensure_wiki()
        event = {'event':'question','channel_id':str(QUESTIONS_CHANNEL_ID),'message_id':'100',
                 'body':'Synthetic game question about gems?', 'reply_to':None, 'created_at':time.time()}
        self.app.knowledge.ingest(event)
        self.app.knowledge.checkpoint(event)
        self.source = self.app.knowledge.path
        self.app.knowledge.close()
        self.app.knowledge = RemoteKnowledge(self.app, SECRET)
        self.pc = self.root / 'pc'
        self.pc.mkdir()

    async def asyncTearDown(self):
        await self.app.close()
        self.temp.cleanup()

    def export(self):
        target = self.root / 'export.zip'
        controls = {'budget':json.dumps({'day':'2026-10-26','calls':2,'tokens':100})}
        manifest = export_bundle(self.source, controls, target)
        return target, manifest

    async def test_round_trip_preserves_all_source_records_cursor_and_budget(self):
        target, manifest = self.export()
        receipt = import_bundle(target, self.pc)
        self.assertEqual(receipt, manifest)
        self.assertEqual(inspect_database(self.pc / 'knowledge.sqlite3'), {'messages':1,'articles':655,'cursor':'100'})
        self.assertTrue(self.source.exists())
        store = PCStore(self.pc)
        self.assertEqual(json.loads(store.get('budget'))['calls'],2)
        store.close()

    async def test_import_never_overwrites_existing_pc_database(self):
        target, _ = self.export()
        original = self.pc / 'knowledge.sqlite3'
        original.write_bytes(b'preserve my previous database')
        with self.assertRaisesRegex(ValueError,'preserved'):
            import_bundle(target, self.pc)
        self.assertEqual(original.read_bytes(),b'preserve my previous database')

    async def test_unexpected_archive_paths_and_wrong_hash_are_rejected(self):
        target, _ = self.export()
        with zipfile.ZipFile(target,'a') as bundle:
            bundle.writestr('../escaped.txt','bad')
        with self.assertRaisesRegex(ValueError,'Unexpected'):
            import_bundle(target,self.pc)
        self.assertFalse((self.root / 'escaped.txt').exists())
        target,_=self.export()
        with zipfile.ZipFile(target) as bundle:
            members={n:bundle.read(n) for n in bundle.namelist()}
        manifest=json.loads(members['manifest.json']);manifest['database_sha256']='0'*64
        members['manifest.json']=json.dumps(manifest).encode()
        with zipfile.ZipFile(target,'w') as bundle:
            for name,content in members.items():bundle.writestr(name,content)
        with self.assertRaisesRegex(ValueError,'checksum'):
            import_bundle(target,self.pc)
        self.assertFalse((self.pc/'knowledge.sqlite3').exists())

    async def test_source_symlink_or_wal_requires_operator_attention(self):
        self.source.with_name(self.source.name+'-wal').write_bytes(b'synthetic')
        with self.assertRaisesRegex(ValueError,'Stop local'):
            self.export()
        self.source.with_name(self.source.name+'-wal').unlink()


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        with patch.dict('os.environ',{'KNOWLEDGE_MODE':'pc','KNOWLEDGE_BRIDGE_SECRET':SECRET}):
            self.app = CommunityBot(self.root/'host', archived_knowledge=True)
        self.bridge = self.app.knowledge
        await self.app.health.start(0,routes=self.bridge.install_routes)
        self.url='http://127.0.0.1:'+str(self.app.health.port)
        self.pc=self.root/'pc';self.pc.mkdir()
        self.config={'bridge_secret':SECRET,'groq_api_key':'synthetic-key','bot_url':self.url}
        self.session=aiohttp.ClientSession(headers={'Authorization':'Bearer '+SECRET})
        self.worker=None;self.worker_task=None

    async def asyncTearDown(self):
        if self.worker_task:
            self.worker_task.cancel()
            await asyncio.gather(self.worker_task,return_exceptions=True)
        await self.app.close()
        await self.session.close()
        if self.worker:self.worker.close()
        self.temp.cleanup()

    async def connect(self):
        async def answer(packet):
            return {'supported':False,'answer':'A fonte não confirma os detalhes solicitados.','citations':[]},100
        backend=SimpleNamespace(enabled=True,answer=AsyncMock(side_effect=answer))
        self.worker=Worker(self.pc,self.config,backend=backend)
        self.worker_task=asyncio.create_task(self.worker.connection(self.session,self.url))
        for _ in range(100):
            if self.bridge.online:return
            if self.worker_task.done():await self.worker_task
            await asyncio.sleep(.01)
        self.fail('Worker did not connect')

    async def test_pc_mode_creates_no_hosted_knowledge_database_or_local_fallback(self):
        self.assertIsInstance(self.bridge,RemoteKnowledge)
        self.assertFalse((self.app.directory/'knowledge.sqlite3').exists())
        with self.assertRaisesRegex(ValueError,'temporarily unavailable'):
            await self.bridge.ask('How does this game work?',actor_id=1)
        self.assertFalse((self.app.directory/'knowledge.sqlite3').exists())

    async def test_private_endpoints_require_secret_and_public_health_stays_minimal(self):
        async with aiohttp.ClientSession() as client:
            for path in ('/knowledge/worker','/knowledge/migration'):
                async with client.get(self.url+path) as response:
                    self.assertEqual(response.status,401)
                    self.assertNotIn(SECRET,await response.text())
            async with client.get(self.url+'/health') as response:
                self.assertEqual(await response.json(),{'status':'alive'})
            async with client.post(self.url+'/knowledge/migration/finalize',json={}) as response:
                self.assertEqual(response.status,401)

    async def test_question_and_answer_round_trip_and_no_hosted_content(self):
        await self.connect()
        result=await self.bridge.ask('Como funciona o jogo?',actor_id=7,locale='pt-BR')
        self.assertIn('A fonte não confirma',result)
        self.assertEqual(self.worker.knowledge.backend.answer.call_args.args[0]['question'],'Como funciona o jogo?')
        self.assertIsNone(self.app.store.get('budget'))
        self.assertIsNotNone(self.worker.store.get('budget'))
        self.assertFalse((self.app.directory/'knowledge.sqlite3').exists())

    async def test_real_currencies_article_answers_portuguese_gems_question_with_a_source(self):
        await self.connect()
        async def grounded(packet):
            source=next(s for s in packet['sources'] if s['title']=='Currencies')
            start=source['text'].index('They can be obtained')
            quote=source['text'][start:source['text'].index('.',start)+1]
            return {'supported':True,'answer':'Segundo a wiki arquivada, você pode conseguir gemas em missões, fases da história, raids e modos infinitos.',
                    'citations':[{'id':source['id'],'quote':quote}]},100
        self.worker.knowledge.backend.answer.side_effect=grounded
        result=await self.bridge.ask('Como conseguir gemas?',actor_id=77,locale='pt-BR')
        self.assertIn('você pode conseguir gemas',result)
        self.assertIn('/wiki/Currencies?oldid=',result)
        self.assertEqual(self.worker.knowledge.backend.answer.await_count,1)
        self.assertIsNone(self.app.store.get('budget'))

    async def test_pc_groq_quote_repair_returns_verified_answer_over_existing_bridge(self):
        await self.connect()
        calls=0
        async def respond(packet):
            nonlocal calls
            calls+=1
            source=next(s for s in packet['sources'] if s['title']=='Currencies')
            if calls==1:
                quote='As gemas podem ser obtidas completando missões e fases da história.'
            else:
                self.assertEqual(packet['repair']['reason'],'quote-not-in-source')
                start=source['text'].index('They can be obtained')
                quote=source['text'][start:source['text'].index('.',start)+1]
            return {'supported':True,'answer':'Segundo a wiki arquivada, é possível conseguir gemas em missões e fases da história.',
                    'citations':[{'id':source['id'],'quote':quote}]},100
        self.worker.knowledge.backend.answer.side_effect=respond
        result=await self.bridge.ask('Como conseguir gemas?',actor_id=78,locale='pt-BR')
        self.assertIn('é possível conseguir gemas',result)
        self.assertIn('/wiki/Currencies?oldid=',result)
        self.assertEqual(json.loads(self.worker.store.get('budget'))['calls'],2)

    async def test_only_authorized_events_are_saved_on_pc_and_cursor_is_acknowledged(self):
        await self.connect()
        event={'event':'question','channel_id':str(QUESTIONS_CHANNEL_ID),'message_id':'101',
               'body':'Synthetic question about gems?', 'reply_to':None, 'created_at':time.time()}
        self.assertTrue(await self.bridge.ingest(event))
        await self.bridge.checkpoint(event)
        self.assertEqual(self.bridge.get_meta('source-cursor'),'101')
        self.assertEqual(self.worker.knowledge.statistics()['messages'],1)
        self.assertFalse(await self.bridge.ingest({**event,'channel_id':'123','message_id':'102'}))
        self.assertEqual(self.worker.knowledge.statistics()['messages'],1)
        self.assertFalse((self.app.directory/'knowledge.sqlite3').exists())

    async def test_disconnect_fails_questions_without_waiting_for_pc_or_advancing_cursor(self):
        await self.connect()
        self.worker_task.cancel();await asyncio.gather(self.worker_task,return_exceptions=True)
        for _ in range(100):
            if not self.bridge.online:break
            await asyncio.sleep(.01)
        self.assertFalse(self.bridge.online)
        with self.assertRaisesRegex(ValueError,'temporarily unavailable'):
            await asyncio.wait_for(self.bridge.ask('How does this game work?',actor_id=1),.2)
        self.assertIsNone(self.bridge.get_meta('source-cursor'))

    async def test_server_close_reports_duration_and_code_without_private_values(self):
        import contextlib,io
        await self.connect()
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            await self.bridge.ws.close(code=1001)
            await asyncio.wait_for(self.worker_task,2)
        text=output.getvalue()
        self.assertIn('Connection ended after',text)
        self.assertIn('WebSocket code:',text)
        self.assertNotIn(SECRET,text)
        self.assertNotIn(self.config['groq_api_key'],text)

    async def test_status_task_failure_closes_connection_instead_of_silently_stalling(self):
        import contextlib,io
        async def fail_status(worker,ws):
            await asyncio.sleep(.05)
            raise RuntimeError('synthetic private details must not be logged')
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch.object(Worker,'heartbeat',fail_status):
            await self.connect()
            with self.assertRaises(RuntimeError):
                await asyncio.wait_for(self.worker_task,2)
        self.assertIn('PC connection task stopped: RuntimeError.',output.getvalue())
        self.assertNotIn('synthetic private details',output.getvalue())
        for _ in range(100):
            if not self.bridge.online:
                break
            await asyncio.sleep(.01)
        self.assertFalse(self.bridge.online)

    async def test_only_one_worker_can_connect(self):
        await self.connect()
        with self.assertRaises(aiohttp.WSServerHandshakeError) as caught:
            await self.session.ws_connect(self.url+'/knowledge/worker')
        self.assertEqual(caught.exception.status,409)

    async def test_migration_is_required_before_empty_worker_can_connect_and_cleanup_is_guarded(self):
        # Create an old local archive without activating any real service.
        from game_knowledge import GameKnowledge
        old=GameKnowledge(self.app);old.ensure_wiki();old.close()
        async with self.session.post(self.url+'/knowledge/migration/finalize',json={'migration_id':'bad'}) as response:
            self.assertEqual(response.status,409)
        async with self.session.ws_connect(self.url+'/knowledge/worker') as ws:
            await ws.send_json({'type':'hello','protocol':1,'status':{'paused':False}})
            message=await ws.receive()
            self.assertEqual(message.type,aiohttp.WSMsgType.CLOSE)
        self.assertTrue((self.app.directory/'knowledge.sqlite3').exists())
        await download_migration(self.session,self.url,self.pc)
        self.assertEqual(inspect_database(self.pc/'knowledge.sqlite3')['articles'],655)
        self.assertTrue((self.app.directory/'knowledge.sqlite3').exists())
        await self.connect()
        receipt=json.loads((self.pc/'migration-receipt.json').read_text())
        before=self.app.store.path.read_bytes()
        async with self.session.post(self.url+'/knowledge/migration/finalize',json={'migration_id':receipt['id']}) as response:
            self.assertEqual(response.status,200)
        self.assertFalse((self.app.directory/'knowledge.sqlite3').exists())
        self.assertTrue(self.app.store.path.exists())
        self.assertTrue((self.pc/'knowledge.sqlite3').exists())
        self.assertEqual(self.app.store.connection.execute('PRAGMA quick_check').fetchone()[0],'ok')

    async def test_stale_heartbeat_means_offline_and_groq_requests_go_only_to_pc_backend(self):
        await self.connect()
        self.bridge.last_status=time.monotonic()-21
        self.assertFalse(self.bridge.online)
        with self.assertRaisesRegex(ValueError,'temporarily unavailable'):
            await self.bridge.ask('How does this game work?',actor_id=1)
        self.worker.knowledge.backend.answer.assert_not_called()

    async def test_pc_restart_keeps_messages_cursor_and_ai_budget(self):
        await self.connect()
        event={'event':'question','channel_id':str(QUESTIONS_CHANNEL_ID),'message_id':'301',
               'body':'Synthetic game question?', 'created_at':time.time()}
        await self.bridge.ingest(event);await self.bridge.checkpoint(event)
        await self.bridge.ask('Como funciona o jogo?',actor_id=7)
        self.worker_task.cancel();await asyncio.gather(self.worker_task,return_exceptions=True)
        self.worker.close();self.worker=None
        for _ in range(100):
            if not self.bridge.online:break
            await asyncio.sleep(.01)
        await self.connect()
        self.assertEqual(self.bridge.get_meta('source-cursor'),'301')
        self.assertEqual(self.worker.knowledge.statistics()['messages'],1)
        self.assertEqual(json.loads(self.worker.store.get('budget'))['calls'],1)

    async def test_pending_question_fails_promptly_when_pc_disconnects(self):
        await self.connect()
        started=asyncio.Event()
        async def wait_forever(packet):
            started.set();await asyncio.Event().wait()
        self.worker.knowledge.backend.answer.side_effect=wait_forever
        question=asyncio.create_task(self.bridge.ask('How can I get gems?',actor_id=9))
        await asyncio.wait_for(started.wait(),2)
        self.worker_task.cancel();await asyncio.gather(self.worker_task,return_exceptions=True)
        with self.assertRaisesRegex(ValueError,'temporarily unavailable'):
            await asyncio.wait_for(question,.5)
        self.assertEqual(self.bridge.pending,{})

    async def test_missing_pc_secret_fails_closed_without_creating_local_archive(self):
        with patch.dict('os.environ',{'KNOWLEDGE_MODE':'pc','KNOWLEDGE_BRIDGE_SECRET':''}):
            other=CommunityBot(self.root/'misconfigured-host', archived_knowledge=True)
        try:
            self.assertTrue(other.knowledge.paused)
            self.assertFalse((other.directory/'knowledge.sqlite3').exists())
        finally:
            await other.close()

    async def test_disk_pause_preserves_saved_pc_messages_and_checkpoint(self):
        await self.connect()
        event={'event':'question','channel_id':str(QUESTIONS_CHANNEL_ID),'message_id':'201',
               'body':'Synthetic game question?', 'created_at':time.time()}
        self.assertTrue(await self.bridge.ingest(event));await self.bridge.checkpoint(event)
        with patch.object(self.worker.knowledge,'used_bytes',return_value=self.worker.knowledge.max_bytes):
            self.assertFalse(await self.bridge.ingest({**event,'message_id':'202'}))
        self.assertTrue(self.bridge.paused)
        await self.bridge.checkpoint({**event,'message_id':'202'})
        self.assertEqual(self.worker.knowledge.get_meta('source-cursor'),'201')
        self.assertEqual(self.worker.knowledge.statistics()['messages'],1)

    async def test_source_deletion_still_applies_while_pc_archive_is_paused(self):
        await self.connect()
        event={'event':'question','channel_id':str(QUESTIONS_CHANNEL_ID),'message_id':'401',
               'body':'Synthetic game question?', 'created_at':time.time()}
        await self.bridge.ingest(event)
        self.worker.knowledge.paused=True
        self.bridge.update_status(self.worker.status())
        self.assertTrue(self.bridge.paused)
        self.assertTrue(await self.bridge.ingest({**event,'event':'question_delete'}))
        self.assertEqual(self.worker.knowledge.statistics()['messages'],0)


class PCConfigTests(unittest.TestCase):
    def test_patch_package_contains_only_public_answer_code_and_instructions(self):
        from scripts.build_pc_knowledge import build
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'patch.zip'
            build(target,patch=True)
            with zipfile.ZipFile(target) as bundle:
                self.assertEqual(set(bundle.namelist()),{'game_knowledge.py','knowledge_pc.py','LEIA-ME-ATUALIZACAO.txt','patch-manifest.json'})
                self.assertEqual(bundle.read('game_knowledge.py'),Path('game_knowledge.py').read_bytes())

    def test_windows_package_contains_source_and_corpus_without_state_or_credentials(self):
        from scripts.build_pc_knowledge import build
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'pc.zip'
            result=build(target)
            self.assertGreater(result['files'],10)
            with zipfile.ZipFile(target) as bundle:
                names=bundle.namelist()
                self.assertIn('Anime-Adventures-PC/CONFIGURAR-PC.cmd',names)
                self.assertIn('Anime-Adventures-PC/data/game_wiki.json',names)
                self.assertFalse(any('.private.' in name or '.sqlite' in name or '/.env' in name for name in names))
                manifest=json.loads(bundle.read('Anime-Adventures-PC/package-manifest.json'))
                import hashlib
                for name,expected in manifest.items():
                    self.assertEqual(hashlib.sha256(bundle.read('Anime-Adventures-PC/'+name)).hexdigest(),expected)

    def test_external_http_credentials_paths_and_queries_are_rejected(self):
        for url in ('http://example.test','https://user:pass@example.test','https://example.test/path', 'https://example.test?token=abc','https://example.test/#secret'):
            with self.assertRaises(ValueError):validate_url(url)
        self.assertEqual(validate_url('https://7g2x14fnpa.apps.bot-hosting.cloud/'),'https://7g2x14fnpa.apps.bot-hosting.cloud')
        self.assertEqual(validate_url('http://127.0.0.1:123',allow_loopback=True),'http://127.0.0.1:123')

    def test_default_windows_path_and_no_fcntl_dependency_in_companion(self):
        from knowledge_pc import DEFAULT_DIRECTORY
        self.assertEqual(DEFAULT_DIRECTORY,r'D:\Armazenamento do Bot')
        import sys
        # fcntl is imported only in the POSIX branch of main; Windows imports
        # and setup use msvcrt, never the Linux-only bot lease implementation.
        source=Path('knowledge_pc.py').read_text()
        self.assertNotIn('from tier_backup',source)


if __name__=='__main__':unittest.main()
