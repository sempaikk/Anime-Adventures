"""Private tools journeys, isolation, scheduling and derived reply lifecycle."""

import asyncio
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from adventure_store import AdventureStore, MODULES
from adventure_service import AdventureService, parse_time, quiet
from bot_store import BotStore
from bot_ui import payload, visible_text
from game_calculators import allocate, budget, chance, dps, farm
from game_knowledge import Knowledge
from scripts.build_game_data import LiteralTable
from scripts.check_game_data import compare, validate
import test_banners as feeds
import test_global_chat as chats


class CalculationCase(unittest.TestCase):
    def test_expected_crit_and_multiple_towers(self):
        result=dps(10000,5,20,1.5,3)
        self.assertEqual(result['single'],2000)
        self.assertEqual(result['expected'],2200)
        self.assertEqual(result['total'],6600)
        self.assertIn('DoT',result['assumptions'])

    def test_reject_nonfinite_negative_and_zero_denominator(self):
        for value in ('nan','inf','-1'):
            with self.subTest(value=value),self.assertRaises(ValueError):dps(value,5)
        for spa in (0,-1):
            with self.assertRaises(ValueError):dps(1,spa)
        with self.assertRaises(ValueError):dps(1,1,101)
        with self.assertRaises(ValueError):dps(1,1,0,1.5,1.2)

    def test_independent_probability_is_not_guaranteed_after100(self):
        result=chance(1,100,95)
        self.assertAlmostEqual(result['probability_percent'],63.39676587)
        self.assertEqual(result['attempts_for_target'],299)
        self.assertIsNone(chance(1,100,100)['attempts_for_target'])

    def test_probability_boundaries_and_input_units(self):
        self.assertEqual(chance(0,100)['probability_percent'],0)
        self.assertIsNone(chance(0,100)['attempts_for_target'])
        self.assertEqual(chance(100,1)['attempts_for_target'],1)
        self.assertEqual(chance(100,0)['probability_percent'],0)
        with self.assertRaises(ValueError):chance(5,1.5)
        with self.assertRaises(ValueError):chance(101,100)
        self.assertAlmostEqual(chance('0,5%',1)['probability_percent'],.5)

    def test_budget_has_no_hidden_price_or_discount(self):
        self.assertEqual(budget(100,30)['attempts'],3)
        self.assertEqual(budget(100,30)['remaining'],10)
        with self.assertRaises(ValueError):budget(100,0)
        self.assertEqual(budget(.3,.1)['attempts'],3)
        self.assertEqual(budget(.3,.1)['remaining'],0)

    def test_farm_distinguishes_completions_and_attempts(self):
        result=farm(21,10,5,50)
        self.assertEqual(result['completed_runs'],3)
        self.assertEqual(result['expected_attempts'],6)
        self.assertEqual(result['expected_minutes'],30)
        with self.assertRaises(ValueError):farm(10,0,5)
        self.assertEqual(farm(.56,.08,5)['completed_runs'],7)

    def test_shared_materials_are_allocated_only_once(self):
        rows=allocate([('one',{'fruit':8}),('two',{'fruit':8})],{'fruit':10})
        self.assertEqual(rows[0]['missing'],{})
        self.assertEqual(rows[1]['missing'],{'fruit':6})


class KnowledgeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.k=Knowledge()

    def test_exact_forms_have_sources_and_old_values_are_labeled(self):
        row=self.k.exact('Shinobi (Eternal)')
        self.assertEqual(row['id'],'sasuke_3_evolved')
        self.assertEqual(row['damage_type'],'magic')
        card=self.k.card(row['id'])
        self.assertIn('Historical',card)
        self.assertIn('not verified',card)
        self.assertIn('revision',card)

    def test_search_disambiguates_and_filters(self):
        results=self.k.search('Shinobi')
        self.assertGreater(len(results),1)
        self.assertEqual(len({r['id'] for r in results}),len(results))
        for r in self.k.search('Shinobi',filters={'damage_type':'magic'}):self.assertEqual(r['damage_type'],'magic')
        self.assertEqual(self.k.search('Shinobi',filters={'damage_type':'not-a-type'}),[])
        self.assertGreater(len(self.k.search('',filters={'damage_type':'magic'})),50)

    def test_evolved_form_can_find_its_exact_parent_recipe(self):
        row=self.k.exact('Shinobi (Eternal)')
        recipe=self.k.recipe(row['id'])
        self.assertEqual(recipe['to'],row['id'])
        self.assertGreater(len(recipe['recipe']),0)
        self.assertIn('Takedown',self.k.evolution(row['id']))

    def test_branching_outcomes_are_not_treated_as_a_single_guaranteed_form(self):
        row=self.k.exact('Chance')
        self.assertIsNone(row['to'])
        self.assertGreater(len(row['branches']),1)
        text=self.k.evolution(row['id'])
        self.assertIn('random',text)
        self.assertIn('not verified',text)

    def test_air_upgrade_note_is_preserved_without_inferring_it_from_placement(self):
        row=self.k.exact('Snow Reaper')
        self.assertEqual(row['tower_type'],'Ground')
        self.assertIn('Upgrade 7',row['air_note'])

    def test_every_imported_unit_card_and_path_fit_discord(self):
        for row in self.k.units.values():
            for text in (self.k.card(row['id']),self.k.evolution(row['id'])):
                self.assertLessEqual(len(text),4000,row['id'])
                self.assertLessEqual(payload(content=text)['view'].total_children_count,40,row['id'])

    def test_upgrade_pages_are_bounded_and_same_form(self):
        row=self.k.exact('Shinobi (Eternal)')
        text=self.k.upgrades(row['id'])
        self.assertEqual(text.count('**Upgrade'),5)
        self.assertIn('Shinobi',text)
        self.assertIn('Historical',text)

    def test_parser_does_not_execute_or_coerce_boolean_stats(self):
        self.assertEqual(LiteralTable('return {a={cost=250*1.4, bad=true, unknown=some.value}}').read()['a']['cost'],350)
        self.assertIsNone(LiteralTable('return {a=some.value}').read()['a'])
        with self.assertRaises(ValueError):LiteralTable('return {a=function() end}').read()
        with self.assertRaises(ValueError):LiteralTable('return {} os.execute("bad")').read()

    def test_pack_validation_and_diff_are_read_only(self):
        p=Path(__file__).resolve().parents[1]/'data/game_knowledge.json'
        before=p.read_bytes(); result=compare(p,p)
        self.assertEqual(result['changed'],[])
        self.assertFalse(result['files_replaced'])
        self.assertEqual(p.read_bytes(),before)
        self.assertGreater(len(validate(p)['units']),500)

    def test_archived_material_lookup_includes_obtaining_row_after_a_spanned_name(self):
        row=self.k.items['StarFruit']
        self.assertIn('Purchased',row['archived_details'])
        self.assertIn('Travelling Merchant',row['archived_details'])
        self.assertIn('Historical source',self.k.card(row['id'],'item'))


class ToolStoreCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=2_000_000_000.0
        self.base=BotStore(Path(self.temp.name)/'bot.sqlite3',clock=lambda:self.now)
        self.state=AdventureStore(self.base)
    def tearDown(self):self.base.close();self.temp.cleanup()

    def test_user_entries_cannot_be_read_or_removed_by_another_user(self):
        self.state.save(7,'team','mine',{'units':['one']})
        self.assertEqual(self.state.entries(8,'team'),[])
        self.assertEqual(self.state.remove(8,'team','mine'),0)
        self.assertEqual(len(self.state.entries(7,'team')),1)

    def test_limits_allow_edit_but_reject_sixth_team(self):
        for n in range(5):self.state.save(7,'team',str(n),{'units':[]})
        self.state.save(7,'team','0',{'units':['changed']})
        with self.assertRaises(ValueError):self.state.save(7,'team','six',{})

    def test_settings_cas_preserves_unrelated_state_and_rejects_secrets(self):
        self.base.set('sentinel','receipt')
        data,version=self.state.settings(1)
        data['modules']=['knowledge']
        self.state.configure(1,7,data,version)
        self.assertFalse(self.state.enabled(1,'parties'))
        with self.assertRaises(ValueError):self.state.configure(1,7,data,version)
        with self.assertRaises(ValueError):self.state.configure(1,7,{**data,'token':'must-not-import'},1)
        self.assertEqual(self.base.get('sentinel'),'receipt')

    def test_pilot_does_not_grant_global_moderation_or_disable_feeds(self):
        with self.state.db:self.state.db.execute('INSERT INTO bot_feature_gates VALUES(?,?,1)',('planning','["1"]'))
        self.assertTrue(self.state.enabled(1,'planning'))
        self.assertFalse(self.state.enabled(2,'planning'))
        with self.state.db:self.state.db.execute('UPDATE bot_feature_gates SET guilds=\'["*"]\'')
        self.assertTrue(self.state.enabled(2,'planning'))

    def test_reminders_persist_cancel_and_cannot_be_cancelled_by_other_user(self):
        ident=self.state.reminder(7,1,'private',self.now+60)
        self.assertEqual(self.state.cancel(8,ident),0)
        self.assertEqual(self.state.cancel(7,ident),1)
        self.assertEqual(self.state.one('SELECT state FROM bot_tool_reminders WHERE id=?',(ident,))['state'],'cancelled')

    def test_reminder_active_cap_and_snooze(self):
        ids=[self.state.reminder(7,1,'x',self.now+60) for _ in range(5)]
        with self.assertRaises(ValueError):self.state.reminder(7,1,'six',self.now+60)
        replacement=self.state.snooze(7,ids[0])
        self.assertNotEqual(ids[0],replacement)
        self.assertEqual(self.state.one('SELECT state FROM bot_tool_reminders WHERE id=?',(ids[0],))['state'],'cancelled')

    def test_restart_keeps_ambiguous_send_uncertain(self):
        ident=self.state.reminder(7,1,'x',self.now+60)
        with self.state.db:self.state.db.execute("UPDATE bot_tool_reminders SET state='sending',attempted=?",(self.now,))
        AdventureStore(self.base)
        self.assertEqual(self.state.one('SELECT state FROM bot_tool_reminders WHERE id=?',(ident,))['state'],'uncertain')

    def test_party_slots_and_order_survive_duplicate_clicks(self):
        ident=self.state.party(1,10,99,'Dungeon',self.now+60,2)
        with self.state.db:self.state.db.execute("UPDATE bot_tool_parties SET state='open' WHERE id=?",(ident,))
        self.state.join(ident,1,7);self.state.join(ident,1,7);self.state.join(ident,1,8)
        rows=self.state.members(ident)
        self.assertEqual([r['user'] for r in rows],['99','7','8'])
        self.assertEqual(len(rows[:2]),2)
        self.state.join(ident,1,7,ready=True);self.state.join(ident,1,7)
        self.assertEqual(self.state.members(ident)[1]['ready'],1)
        self.state.join(ident,1,7,unready=True)
        self.assertEqual(self.state.members(ident)[1]['ready'],0)
        self.state.join(ident,1,7,leave=True)
        self.assertEqual([r['user'] for r in self.state.members(ident)[:2]],['99','8'])
        with self.assertRaises(ValueError):self.state.join(ident,2,8)

    def test_expired_group_cannot_accept_clicks(self):
        ident=self.state.party(1,10,7,'Dungeon',self.now+60,2)
        with self.state.db:self.state.db.execute("UPDATE bot_tool_parties SET state='open'")
        self.now+=8000;self.state.cleanup()
        with self.assertRaises(ValueError):self.state.join(ident,1,8)

    def test_private_export_and_deletion_preserve_relay_receipt_sentinel(self):
        self.base.set('receipt-sentinel','accepted')
        self.state.save(7,'favorite','one',{'id':'unit'})
        self.state.save(8,'favorite','other',{'id':'other'})
        self.state.set_preferences(7,'America/Sao_Paulo',22,8,True,1)
        data=self.state.export_user(7)
        self.assertEqual(len(data['entries']),1)
        self.state.erase_user(7)
        self.assertEqual(self.state.entries(7,'favorite'),[])
        self.assertEqual(len(self.state.entries(8,'favorite')),1)
        self.assertEqual(self.base.get('receipt-sentinel'),'accepted')

    def test_timezone_and_dst_ambiguities_are_explicit(self):
        self.assertEqual(parse_time('60','UTC',self.now),self.now+3600)
        for local in ('2026-11-01 01:30','2026-03-08 02:30'):
            with self.assertRaises(ValueError):parse_time(local,'America/New_York',self.now)
        t=parse_time('2026-11-01 01:30-04:00','America/New_York',self.now)
        self.assertIsInstance(t,float)

    def test_pinned_timezone_data_works_without_the_operating_system_database(self):
        import zoneinfo
        original=zoneinfo.TZPATH
        try:
            zoneinfo.reset_tzpath(())
            zoneinfo.ZoneInfo.clear_cache()
            self.assertEqual(parse_time('2026-11-01 12:00','America/Sao_Paulo',self.now),parse_time('2026-11-01 12:00-03:00','UTC',self.now))
        finally:
            zoneinfo.reset_tzpath(original)
            zoneinfo.ZoneInfo.clear_cache()

    def test_quiet_interval_crosses_midnight_without_delaying_images(self):
        cfg={'timezone':'UTC','quiet_start':22,'quiet_end':8}
        for hour,expected in ((23,True),(3,True),(8,False),(12,False)):
            self.assertEqual(quiet(cfg,datetime(2026,1,1,hour,tzinfo=timezone.utc).timestamp()),expected)


class ToolViewsCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=feeds.BannerCase.asyncSetUp
    asyncTearDown=feeds.BannerCase.asyncTearDown
    add_channel=feeds.BannerCase.add_channel
    send=feeds.BannerCase.send
    event=feeds.BannerCase.event
    interaction=feeds.BannerCase.interaction

    async def test_every_tool_modal_and_home_serializes_with_discord_limits(self):
        from adventure_views import FORMS,ToolForm,ToolsHome,SearchResults,DetailView,SavedView,ReminderView,PartyView
        from adventure_admin import SettingsForm,SetupView
        from case_followup import CaseForm
        i=self.interaction();i.response.send_modal=AsyncMock()
        for name in FORMS:
            with self.subTest(form=name):
                modal=ToolForm(self.app,i,name)
                self.assertLessEqual(len(modal.children),5)
                self.assertLessEqual(len(modal.to_dict()['components']),5)
                for field in modal.inputs.values():
                    self.assertLessEqual(len(field.placeholder or ''),100)
        self.assertLessEqual(len(SettingsForm(self.app,i).to_dict()['components']),5)
        self.assertLessEqual(len(CaseForm(self.app,i).to_dict()['components']),5)
        views=[ToolsHome(self.app,i),*[ToolsHome(self.app,i,x) for x in ('knowledge','planning','parties','reminders','personal')],SetupView(self.app,i),SavedView(self.app,i),ReminderView(self.app,i)]
        for view in views:
            card=payload(bot=self.app,content=view.description(),view=view)['view']
            self.assertLessEqual(card.total_children_count,40)
        self.assertTrue(PartyView('abcdef123456').is_persistent())

    async def test_five_commands_include_message_context_without_registration_to_discord(self):
        commands={c.name:c for c in self.app.tree.get_commands()}
        self.assertEqual(commands['Report global message'].type,discord.AppCommandType.message)
        self.assertIn('adventures',commands)
        self.assertFalse(self.sent)

    async def test_goal_allocations_expose_source_date_and_priority(self):
        from adventure_views import material_goals
        state=self.app.adventures.state
        state.save(7,'goal','low',{'ingredients':{'StarFruit':8},'source':{'date':'2025-01-01'},'priority':10})
        state.save(7,'goal','high',{'ingredients':{'StarFruit':8},'source':{'date':'2025-01-02'},'priority':1})
        state.save(7,'owned','materials',{'StarFruit':10})
        text=material_goals(self.app.adventures,7)
        self.assertLess(text.index('**high**'),text.index('**low**'))
        self.assertIn('2025-01-02',text)
        self.assertIn('6 ×',text)

    async def test_quiet_hours_set_flag_on_multipart_without_changing_image_or_nonce(self):
        from feed_tools import silence_payload
        from discord.http import handle_message_parameters
        data,_=self.app.adventures.state.settings(1)
        hour=datetime.fromtimestamp(self.app.store.clock(),timezone.utc).hour
        data.update(quiet_start=hour,quiet_end=(hour+1)%24)
        self.app.adventures.state.configure(1,7,data,0)
        file=discord.File(io.BytesIO(b'unchanged'),filename='same.png')
        try:
            with handle_message_parameters(files=[file],allowed_mentions=discord.AllowedMentions.none()) as params:
                silence_payload(self.app,1,params)
                body=json.loads(next(e['value'] for e in params.multipart if e['name']=='payload_json'))
                self.assertEqual(body['flags']&4096,4096)
                self.assertEqual(file.fp.read(),b'unchanged')
        finally:file.close()

    async def test_read_only_module_settings_and_undo_require_current_version(self):
        from adventure_admin import SettingsConfirm
        i=self.interaction();state=self.app.adventures.state
        data,version=state.settings(1)
        view=SettingsConfirm(self.app,i,{**data,'modules':['knowledge']},version)
        self.assertEqual(state.settings(1)[1],0)
        state.configure(1,7,{**data,'modules':['planning']},version)
        with self.assertRaises(ValueError):await view.confirm.callback(i)

    async def test_read_only_tools_installation_needs_no_broad_permissions(self):
        from app_profile import install_permissions
        self.assertEqual(install_permissions('tools').value,0)
        self.assertFalse(install_permissions('images').manage_webhooks)

    async def test_public_update_waits_for_command_confirmation_and_local_pack(self):
        self.app.banners.votes.release_pending=lambda:None
        self.app.command_sync_status='pending'
        self.assertFalse(self.app.community.update_complete({'requires_commands':True,'requires_tools':True}))
        self.app.command_sync_status='confirmed'
        self.assertTrue(self.app.community.update_complete({'requires_commands':True,'requires_tools':True}))

    async def test_saved_team_preview_does_not_publish_until_the_second_explicit_action(self):
        from adventure_views import SavedView
        i=self.interaction();state=self.app.adventures.state
        state.save(7,'team','private team',{'units':['sasuke_3_evolved'],'notes':'my own notes'})
        view=SavedView(self.app,i,'team');view.selected='private team'
        await view.share_team.callback(i)
        self.assertEqual(self.sent,[])
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        self.assertIn('Shared team',visible_text(i.followup.send.call_args.kwargs['view'].to_components()))


class ReplyLifecycleCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=chats.ChatCase.asyncSetUp
    asyncTearDown=chats.ChatCase.asyncTearDown
    fetch=chats.ChatCase.fetch
    history=chats.ChatCase.history
    send_notice=chats.ChatCase.send_notice
    message=chats.ChatCase.message
    asset=chats.ChatCase.asset
    flush=chats.ChatCase.flush
    copies=chats.ChatCase.copies

    async def create_reply(self,files=False):
        source=self.message(content='Parent original quote')
        await self.engine.ingest(source);await self.flush()
        copy=next(m for m in self.copies(source) if m.channel.id==20)
        answer=self.message(self.channels[20],content='Reply author body',attachments=[self.asset('reply-image.png')] if files else None)
        answer.reference=SimpleNamespace(message_id=copy.id)
        await self.engine.ingest(answer);await self.flush()
        return source,answer

    async def test_parent_removal_updates_only_bot_injected_context(self):
        source,answer=await self.create_reply()
        self.engine.store.erase(source.id);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))
        self.assertIn(source.id,self.messages)
        self.assertEqual(answer.content,'Reply author body')

    async def test_parent_edit_updates_existing_quotes_without_new_copies(self):
        source,answer=await self.create_reply()
        before={m.id for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content}
        source.content='Parent edited quote'
        await self.engine.ingest(source);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual({m.id for m in replies},before)
        self.assertTrue(all('Parent edited quote' in m.content and 'Parent original quote' not in m.content for m in replies))

    async def test_reference_id_survives_restart_without_retaining_parent_text(self):
        source,answer=await self.create_reply()
        from global_store import GlobalStore
        recovered=GlobalStore(self.base)
        self.assertEqual(recovered.message(answer.id)['reply_id'],str(source.id))
        self.engine.store.erase(source.id)
        self.assertEqual(recovered.message(source.id)['payload'],'{}')

    async def test_context_removal_after_cache_expiry_and_author_leaving(self):
        source,answer=await self.create_reply()
        self.now[0]+=3601
        self.engine.store.cleanup()
        self.engine.store.consent(answer.author.id,False)
        self.assertEqual(self.engine.store.message(answer.id)['payload'],'{}')
        self.engine.store.erase(source.id)
        await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))

    async def test_context_refresh_does_not_strip_a_human_first_line(self):
        source,answer=await self.create_reply()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        for m in replies:m.content='> Changed by a separate action\nReply author body'
        self.engine.store.erase(source.id);await self.flush()
        self.assertTrue(all(m.content.startswith('> Changed by a separate action') for m in replies))

    async def test_old_context_cleanup_preserves_attachments_without_reuploading(self):
        source,answer=await self.create_reply(files=True)
        expected=self.blobs[answer.attachments[0].url]
        self.now[0]+=3601;self.engine.store.cleanup()
        self.engine.store.erase(source.id);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all(m.attachments[0].blob==expected and m.attachments[0].filename=='reply-image.png' for m in replies))
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))

    async def test_parent_removal_during_reply_ack_does_not_lose_cleanup(self):
        source=self.message(content='Parent original quote')
        await self.engine.ingest(source);await self.flush()
        copy=next(m for m in self.copies(source) if m.channel.id==20)
        answer=self.message(self.channels[20],content='Reply author body')
        answer.reference=SimpleNamespace(message_id=copy.id)
        original=self.hooks[110].send
        async def withdraw(*args,**kwargs):
            sent=await original(*args,**kwargs)
            self.engine.store.erase(source.id)
            return sent
        self.hooks[110].send=withdraw
        await self.engine.ingest(answer);await self.flush()
        replies=[m for m in self.messages.values() if m.webhook_id and 'Reply author body' in m.content]
        self.assertEqual(len(replies),2)
        self.assertTrue(all('Parent original quote' not in m.content for m in replies))

    async def test_cleanup_uses_reserved_capacity_while_regular_sends_stall(self):
        for gid in (4,5,6):self.engine.store.configure(gid,gid*10,gid*10+100,'synthetic',0)
        regular=self.message(content='New normal publication')
        await self.engine.ingest(regular)
        # Keep a distinct destination available for a previous-copy removal.
        with self.base.connection:
            self.base.connection.execute("UPDATE global_deliveries SET state='cancelled' WHERE source_id=? AND channel_id='60'",(str(regular.id),))
        await self.engine.ingest(self.message(content='Previous removal fixture'))
        old=self.engine.store.one('SELECT id FROM global_messages WHERE id<>? ORDER BY created DESC,rowid DESC LIMIT 1',(str(regular.id),))
        with self.base.connection:
            self.base.connection.execute("UPDATE global_deliveries SET state='sent',receipts='[\"9999\"]' WHERE source_id=? AND channel_id='60'",(old['id'],))
            self.base.connection.execute("UPDATE global_deliveries SET state='cancelled' WHERE source_id=? AND channel_id<>'60'",(old['id'],))
        release,removed=asyncio.Event(),asyncio.Event()
        started=[]
        async def deliver(job):
            row=self.engine.store.message(job['source_id'])
            if row['deleted']:
                removed.set();return
            started.append(job['channel_id']);await release.wait()
        self.engine.deliver=deliver
        self.engine.last_recovery=self.engine.store.clock()
        await self.engine.cycle()
        self.assertEqual(len(started),3)
        self.engine.store.erase(old['id'])
        await self.engine.cycle()
        await asyncio.wait_for(removed.wait(),.3)
        self.assertEqual(len(started),3)
        release.set()

    async def test_sharing_preview_neither_joins_nor_creates_network_copies(self):
        from global_views import ConsentView
        i=chats.ChatCase.interaction(self)
        self.engine.store.consent(7,False)
        before=set(self.messages)
        view=ConsentView(self.app,i,self.engine.store.channel(1))
        await view.preview.callback(i)
        self.assertFalse(self.engine.store.consented(7))
        self.assertEqual(set(self.messages),before)
        self.assertIn('Private sharing preview',visible_text(i.response.send_message.call_args.kwargs['view'].to_components()))
