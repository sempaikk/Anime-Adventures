"""Grounding, multilingual retrieval, bounded memory and free quotas; no real API."""

import asyncio
from datetime import datetime, timezone
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from community_bot import CommunityBot
from game_knowledge import GameKnowledge, SYSTEM,unpack
from game_sources import QUESTIONS_CHANNEL_ID
from banner_reader import question_message


class KnowledgeCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = CommunityBot(self.temp.name, archived_knowledge=True)
        self.knowledge = self.app.knowledge
        self.now = 2_000_000_000.0
        self.knowledge.clock = lambda: self.now
        self.knowledge.ensure_wiki = lambda: None
        self.source = "Gems can be obtained by completing story stages. This archive does not establish the current patch reward amounts."
        self.knowledge.db.execute("INSERT INTO knowledge_wiki(source_id,title,body,url,as_of) VALUES(?,?,?,?,?)", ('1','Gems',self.source,'https://animeadventures.fandom.com/wiki/Gems','2025-04-01T00:00:00Z'))
        self.knowledge.db.commit()
        self.knowledge.backend = SimpleNamespace(enabled=True, answer=AsyncMock(side_effect=self.answer))

    async def asyncTearDown(self):
        await self.app.close()
        self.temp.cleanup()

    async def answer(self, packet):
        source = packet['sources'][0]
        return {'supported':True,'answer':'Gems can be obtained by completing story stages.',
                'citations':[{'id':source['id'],'quote':source['text'][:60]}]}, 100

    def event(self, ident, body, reply=None, **extra):
        return {'event':'question','channel_id':str(QUESTIONS_CHANNEL_ID),'message_id':str(ident),
                'body':body,'reply_to':str(reply) if reply else None,'created_at':self.now,**extra}

    async def test_answer_uses_sources_and_does_not_store_users_questions(self):
        result = await self.knowledge.ask('How do I get gems?',actor_id=17)
        self.assertIn('story stages',result)
        self.assertIn('https://animeadventures.fandom.com/wiki/Gems',result)
        packet = self.knowledge.backend.answer.call_args.args[0]
        self.assertNotIn('actor_id',packet)
        self.assertEqual(self.knowledge.db.execute('SELECT COUNT(*) FROM knowledge_chat').fetchone()[0],0)
        self.assertEqual(json.loads(self.app.store.get('budget'))['calls'],1)

    async def test_formatting_whitespace_and_unicode_composition_do_not_reject_real_quote(self):
        body='Gems are rewards.\n\nYou can obtain gems\tby completing story stages.\nCafé rewards are listed separately.'
        self.knowledge.db.execute('UPDATE knowledge_wiki SET body=?',(body,));self.knowledge.db.commit()
        self.knowledge.backend.answer.side_effect=None
        self.knowledge.backend.answer.return_value=({'supported':True,'answer':'Você pode obter gemas ao concluir fases da história.',
            'citations':[{'id':'w0','quote':'You can obtain gems\u00a0by completing story stages.'},{'id':'w0','quote':'Cafe\u0301 rewards are listed separately.'}]},100)
        result=await self.knowledge.ask('Como conseguir gemas?',actor_id=1)
        self.assertIn('Você pode obter',result)
        self.assertEqual(self.knowledge.backend.answer.await_count,1)

    async def test_bad_citation_id_gets_one_bounded_repair_in_original_question_language(self):
        bad={'supported':True,'answer':'Você pode obter gemas ao concluir fases da história.',
             'citations':[{'id':'w0 or c0','quote':self.source[:60]}]}
        good={**bad,'citations':[{'id':'w0','quote':self.source[:60]}]}
        self.knowledge.backend.answer.side_effect=[(bad,100),(good,100)]
        with self.assertLogs('adventures.knowledge',level='WARNING') as logs:
            result=await self.knowledge.ask('Como conseguir gemas?',actor_id=1,locale='pt-BR')
        self.assertIn('Você pode obter',result)
        self.assertEqual(self.knowledge.backend.answer.await_count,2)
        packet=self.knowledge.backend.answer.call_args.args[0]
        self.assertEqual(packet['repair']['reason'],'unknown-source-id')
        self.assertEqual(packet['question'],'Como conseguir gemas?')
        self.assertEqual(packet['valid_citation_ids'],['w0'])
        self.assertEqual(json.loads(self.app.store.get('budget'))['calls'],2)
        self.assertNotIn('Como conseguir gemas',' '.join(logs.output))
        self.assertNotIn(self.source,' '.join(logs.output))

    async def test_translated_or_changed_numeric_quote_is_still_refused_after_repair(self):
        for index,quote in enumerate(('Gemas podem ser obtidas ao concluir fases da história.',
                                      'Gems can be obtained by completing 999 story stages.')):
            self.knowledge.backend.answer.side_effect=None
            self.knowledge.backend.answer.return_value=({'supported':True,'answer':'Você recebe 999 gemas.',
                'citations':[{'id':'w0','quote':quote}]},100)
            with self.assertRaisesRegex(ValueError,'sources'):
                await self.knowledge.ask('Como conseguir gemas?',actor_id=index+1)
        self.assertEqual(self.knowledge.backend.answer.await_count,4)

    async def test_search_retry_and_citation_repair_share_maximum_of_two_calls(self):
        self.knowledge.backend.answer.side_effect=[
            ({'supported':False,'answer':'確認できる情報が不足しています。','citations':[], 'search_terms':'gems'},50),
            ({'supported':True,'answer':'You can get gems.','citations':[{'id':'unknown','quote':self.source[:60]}]},100)]
        with self.assertRaisesRegex(ValueError,'sources'):
            await self.knowledge.ask('ジェムの入手方法を教えてください',actor_id=1,locale='ja')
        self.assertEqual(self.knowledge.backend.answer.await_count,2)

    async def test_repair_does_not_exceed_daily_free_quota(self):
        day=datetime.fromtimestamp(self.now,timezone.utc).strftime('%Y-%m-%d')
        self.app.store.set('budget',json.dumps({'day':day,'calls':47,'tokens':0}))
        self.knowledge.backend.answer.side_effect=None
        self.knowledge.backend.answer.return_value=({'supported':True,'answer':'You can obtain gems.',
            'citations':[{'id':'unknown','quote':self.source[:60]}]},100)
        with self.assertRaisesRegex(ValueError,'free daily'):
            await self.knowledge.ask('How can I get gems?',actor_id=1)
        self.assertEqual(self.knowledge.backend.answer.await_count,1)
        self.assertEqual(json.loads(self.app.store.get('budget'))['calls'],48)

    async def test_invalid_citation_schema_is_repaired_without_crashing_or_skipping_checks(self):
        self.knowledge.backend.answer.side_effect=[
            ({'supported':True,'answer':'You can obtain gems.','citations':[{'id':['w0'],'quote':self.source[:60]}]},100),
            ({'supported':True,'answer':'You can obtain gems.','citations':[{'id':'w0','quote':self.source[:60]}]},100)]
        result=await self.knowledge.ask('How can I get gems?',actor_id=1)
        self.assertIn('You can obtain gems.',result)
        self.assertEqual(self.knowledge.backend.answer.await_count,2)

    async def test_short_padded_wiki_quote_does_not_bypass_meaningful_quote_length(self):
        self.knowledge.backend.answer.side_effect=None
        self.knowledge.backend.answer.return_value=({'supported':True,'answer':'You can obtain gems.',
            'citations':[{'id':'w0','quote':'Gems'+' '*20}]},100)
        with self.assertRaisesRegex(ValueError,'sources'):
            await self.knowledge.ask('How can I get gems?',actor_id=1)

    async def test_answers_keep_portuguese_spanish_and_english_without_forced_translation(self):
        for index,(question,answer,locale) in enumerate([
            ('Como obter gemas?','Você pode obter gemas ao concluir fases da história.','pt-BR'),
            ('¿Cómo obtener gemas?','Puedes obtener gemas completando fases de historia.','es-ES'),
            ('How do I get gems?','You can obtain gems by completing story stages.','en-US')]):
            async def respond(packet, text=answer):
                s=packet['sources'][0]
                return {'supported':True,'answer':text,'citations':[{'id':s['id'],'quote':s['text'][:60]}]},100
            self.knowledge.backend.answer.side_effect=respond
            result=await self.knowledge.ask(question,actor_id=index+1,locale=locale)
            self.assertTrue(result.startswith(answer))
            self.assertEqual(self.knowledge.backend.answer.call_args.args[0]['question'],question)
        self.assertIn('SAME LANGUAGE',SYSTEM)

    async def test_non_latin_question_can_request_one_english_search_without_changing_answer_language(self):
        async def retry(packet):
            if not packet['sources']:
                return {'supported':False,'answer':'確認できる情報が不足しています。','citations':[], 'search_terms':'gems'},50
            return {'supported':True,'answer':'ストーリーステージをクリアするとジェムを獲得できます。',
                    'citations':[{'id':'w0','quote':packet['sources'][0]['text'][:60]}]},100
        self.knowledge.backend.answer.side_effect=retry
        result=await self.knowledge.ask('ジェムの入手方法を教えてください',actor_id=1,locale='ja')
        self.assertTrue(result.startswith('ストーリー'))
        self.assertEqual(self.knowledge.backend.answer.await_count,2)
        self.assertEqual(json.loads(self.app.store.get('budget'))['calls'],2)
        self.assertEqual(self.knowledge.backend.answer.call_args.args[0]['question'],'ジェムの入手方法を教えてください')

    async def test_unanswered_questions_never_become_evidence_and_replies_are_marked_unverified(self):
        self.assertTrue(self.knowledge.ingest(self.event(100,'Does getting gems require infinite mode?')))
        self.assertEqual([s for s in self.knowledge.retrieve('gems') if s['kind'].startswith('unverified')],[])
        self.knowledge.ingest(self.event(101,'I have obtained gems by completing story stages.',reply=100))
        sources=[s for s in self.knowledge.retrieve('gems') if s['kind'].startswith('unverified')]
        self.assertEqual(len(sources),1)
        self.assertNotIn('message_id',sources[0])
        self.knowledge.ingest(self.event(101,'Where can I get gems?',reply=100))
        self.assertEqual([s for s in self.knowledge.retrieve('gems') if s['kind'].startswith('unverified')],[])

    async def test_wrong_channel_and_personal_metadata_are_not_forwarded_to_model(self):
        self.assertFalse(self.knowledge.ingest(self.event(100,'Where can I get gems?',channel_id='5')))
        self.knowledge.ingest(self.event(100,'Where can I get gems? Contact test@example.test <@123456789012345678>.'))
        self.knowledge.ingest(self.event(101,'Complete story stages to obtain gems. https://example.test/private',reply=100))
        sources=self.knowledge.retrieve('gems')
        text=json.dumps(sources)
        self.assertNotIn('test@example.test',text)
        self.assertNotIn('123456789012345678',text)
        self.assertNotIn('example.test/private',text)

    async def test_deleting_or_editing_question_during_inference_invalidates_answer(self):
        self.knowledge.ingest(self.event(100,'Where can I get gems?'))
        self.knowledge.ingest(self.event(101,'Complete story stages to obtain gems.',reply=100))
        async def stale(packet):
            source=next(s for s in packet['sources'] if s['kind'].startswith('unverified'))
            self.knowledge.ingest({'event':'question_delete','channel_id':str(QUESTIONS_CHANNEL_ID),'message_id':'100'})
            return {'supported':True,'answer':'Complete story stages.', 'citations':[{'id':source['id'],'quote':source['text'][:50]}]},100
        self.knowledge.backend.answer.side_effect=stale
        with self.assertRaisesRegex(ValueError,'source changed'):
            await self.knowledge.ask('How do I get gems?',actor_id=1)
        self.assertEqual([s for s in self.knowledge.retrieve('gems') if s['kind'].startswith('unverified')],[])

    async def test_fabricated_quote_and_uncited_factual_answers_are_refused(self):
        for index,output in enumerate([
            {'supported':True,'answer':'You receive 999999 gems.','citations':[]},
            {'supported':True,'answer':'You receive 999999 gems.','citations':[{'id':'w0','quote':'This fabricated quotation does not exist.'}]}]):
            self.knowledge.backend.answer.side_effect=None
            self.knowledge.backend.answer.return_value=(output,100)
            with self.assertRaisesRegex(ValueError,'sources'):
                await self.knowledge.ask('How do I get gems?',actor_id=index+1)

    async def test_daily_free_budget_and_rate_limit_stop_calls_without_fallback(self):
        await self.knowledge.ask('How do I get gems?',actor_id=1)
        with self.assertRaisesRegex(ValueError,'20 seconds'):
            await self.knowledge.ask('How do I get gems?',actor_id=1)
        self.assertEqual(self.knowledge.backend.answer.await_count,1)
        day=datetime.fromtimestamp(self.now,timezone.utc).strftime('%Y-%m-%d')
        self.app.store.set('budget',json.dumps({'day':day,'calls':48,'tokens':100}))
        with self.assertRaisesRegex(ValueError,'free daily'):
            await self.knowledge.ask('How do I get gems?',actor_id=2)
        self.assertEqual(self.knowledge.backend.answer.await_count,1)

    async def test_history_survives_age_and_is_compressed_without_duplicate_plaintext_index(self):
        self.knowledge.ingest(self.event(100,'Where can I get gems?'))
        self.knowledge.ingest(self.event(101,'Complete story stages to obtain gems.',reply=100))
        self.now+=31*86400
        self.knowledge.prune()
        self.assertEqual(self.knowledge.db.execute('SELECT COUNT(*) FROM knowledge_chat').fetchone()[0],2)
        self.assertEqual(self.knowledge.db.execute('SELECT COUNT(*) FROM knowledge_chat_search').fetchone()[0],2)
        body=self.knowledge.db.execute("SELECT body FROM knowledge_chat WHERE message_id='100'").fetchone()[0]
        self.assertIsInstance(body,bytes)
        self.assertEqual(unpack(body),'Where can I get gems?')
        self.assertIsNone(self.knowledge.db.execute('SELECT body FROM knowledge_chat_search LIMIT 1').fetchone()[0])

    async def test_storage_limit_pauses_without_erasing_or_advancing_source_checkpoint(self):
        self.knowledge.ingest(self.event(100,'Where can I get gems?'))
        self.knowledge.checkpoint(self.event(100,''))
        with patch.object(self.knowledge,'used_bytes',return_value=self.knowledge.max_bytes):
            self.assertFalse(self.knowledge.ingest(self.event(101,'This new reply must wait for free space.',reply=100)))
        self.knowledge.checkpoint(self.event(101,''))
        self.assertTrue(self.knowledge.paused)
        self.assertEqual(self.knowledge.get_meta('source-cursor'),'100')
        self.assertEqual(self.knowledge.statistics()['messages'],1)
        self.assertFalse(self.knowledge.ingest(self.event(102,'Still paused until the owner restarts.',reply=100)))
        self.assertEqual(self.knowledge.statistics()['messages'],1)

    async def test_short_numeric_reply_is_saved_searchable_and_still_unverified(self):
        self.knowledge.ingest(self.event(100,'How many gems are required?'))
        self.knowledge.ingest(self.event(101,'500',reply=100))
        source=next(s for s in self.knowledge.retrieve('gems required') if s['kind'].startswith('unverified'))
        self.assertIn('Reply: 500',source['text'])

    async def test_measured_daily_counts_do_not_count_replays_as_new_messages(self):
        self.knowledge.ingest(self.event(100,'Where can I get gems?'))
        self.knowledge.ingest(self.event(100,'Where can I get gems?'))
        self.assertEqual(self.knowledge.statistics()['days'][0]['messages'],1)

    async def test_separate_database_and_backup_preserve_data_across_restart(self):
        self.knowledge.ingest(self.event(100,'Where can I get gems?'))
        self.knowledge.checkpoint(self.event(100,''))
        self.assertNotEqual(self.knowledge.path,self.app.store.path)
        await asyncio.to_thread(self.knowledge.backup)
        self.assertTrue(self.knowledge.path.with_name('knowledge-backup.sqlite3').is_file())
        await self.app.close()
        self.app=CommunityBot(self.temp.name, archived_knowledge=True)
        self.knowledge=self.app.knowledge
        self.assertEqual(self.knowledge.statistics()['messages'],1)
        self.assertEqual(self.knowledge.get_meta('source-cursor'),'100')

    async def test_specific_long_game_numbers_and_full_message_text_are_not_truncated_as_phone_numbers(self):
        text='How does the 123456789 damage value work on 2026-10-26? '+('specific game detail '*150)
        self.knowledge.ingest(self.event(100,text))
        body=self.knowledge.db.execute("SELECT body FROM knowledge_chat WHERE message_id='100'").fetchone()[0]
        self.assertEqual(unpack(body),text)

    async def test_more_than_five_thousand_records_are_not_evicted(self):
        import zlib
        data=zlib.compress(b'Example game question?')
        self.knowledge.db.executemany('INSERT INTO knowledge_chat VALUES(?,?,?,?,?,?)',[(str(n),None,data,self.now,22,1) for n in range(6000)])
        self.knowledge.db.commit()
        self.now+=31*86400
        self.knowledge.prune()
        self.assertEqual(self.knowledge.statistics()['messages'],6000)

    async def test_corrupted_optional_archive_does_not_disable_chat_or_erase_the_file(self):
        await self.app.close()
        path=self.knowledge.path
        path.write_bytes(b'synthetic corruption')
        self.app=CommunityBot(self.temp.name, archived_knowledge=True)
        self.knowledge=self.app.knowledge
        self.assertTrue(self.knowledge.paused)
        self.assertIsNotNone(self.app.tree.get_command('globalchat'))
        self.assertEqual(path.read_bytes(),b'synthetic corruption')

    async def test_missing_key_does_not_call_provider(self):
        self.knowledge.backend.enabled=False
        with self.assertRaisesRegex(ValueError,'not been configured'):
            await self.knowledge.ask('How do I get gems?',actor_id=1)
        self.knowledge.backend.answer.assert_not_awaited()


class QuestionSerializerCase(unittest.TestCase):
    def test_source_serializer_uses_only_question_channel_text_without_author_or_images(self):
        message=SimpleNamespace(id=101,channel=SimpleNamespace(id=QUESTIONS_CHANNEL_ID),
            author=SimpleNamespace(id=999,name='Private author',bot=False),webhook_id=None,
            content='How do I obtain gems? Email: test@example.test <@123456789012345678>',
            created_at=datetime.now(timezone.utc),reference=SimpleNamespace(message_id=100,channel_id=QUESTIONS_CHANNEL_ID))
        payload=question_message(message,QUESTIONS_CHANNEL_ID)
        self.assertNotIn('author',payload)
        self.assertNotIn('images',payload)
        self.assertNotIn('test@example.test',payload['body'])
        self.assertEqual(payload['reply_to'],'100')
        self.assertIsNone(question_message(message,4))
        message.author.bot=True
        self.assertIsNotNone(question_message(message,QUESTIONS_CHANNEL_ID))
