import asyncio
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

import bot as app
import adventure_views as views
import quiz_ui as screen
from adventure_repository import AdventureRepository
from difficulty import FORMATS, LABELS, matches
from scores import AwardResult, ScoreStore
from test_controls import interaction
from test_session import Channel, Message, until, user, view_text


class FeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'scores.sqlite3'
        self.store = ScoreStore(self.path)
        self.repo = AdventureRepository(self.store.connection)
        self.patches = [patch.object(app.bot,'scores',self.store),patch.object(app.bot,'adventures',self.repo),
                        patch.object(app,'QUESTION_TIME',30),patch.object(app,'BETWEEN_QUESTIONS',.005),
                        patch.object(app.bot,'connection_lost',False)]
        for item in self.patches:item.start()
        self.sessions = []
        app.click_limits.clear()

    async def asyncTearDown(self):
        tasks=set()
        for s in self.sessions+list(app.active_sessions.values()):
            s.suspending=True
            for t in (s.runner,s.ticker,s.lobby_timer,s.pause_expiry):
                if t:t.cancel();tasks.add(t)
            if s.control_view:s.control_view.stop()
        await asyncio.gather(*tasks,return_exceptions=True)
        app.active_sessions.clear();app.click_limits.clear()
        for item in self.patches:item.stop()
        self.store.close();self.temp.cleanup()

    def guild(self,id=10):
        guild=SimpleNamespace(id=id)
        async def fetch(uid):
            return SimpleNamespace(id=uid,display_name='Player '+str(uid),bot=False,guild=guild)
        guild.fetch_member=AsyncMock(side_effect=fetch)
        return guild

    def event(self,s,actor=None,message=None):
        event=interaction(s,actor,message)
        event.guild=s.channel.guild
        event.guild_id=event.guild.id
        event.response.send_modal=AsyncMock()
        event.response.edit_message=AsyncMock()
        event.response.is_done=lambda:False
        event.followup=SimpleNamespace(send=AsyncMock())
        return event

    async def lobby(self):
        channel=Channel(9000+len(self.sessions))
        channel.guild=self.guild()
        s=app.QuizSession(channel,user(),self.store)
        self.sessions.append(s);app.active_sessions[channel.id]=s
        await s.open_lobby()
        return s

    def test_difficulty_and_formats_are_curated_without_using_character_rarity(self):
        counts=Counter(q.difficulty for q in app.PACK.questions)
        self.assertEqual(set(counts),{'easy','medium','hard'})
        singles=[q for q in app.PACK.questions if q.family=='rarity:single']
        self.assertEqual(len(singles),44)
        self.assertEqual({q.difficulty for q in singles},{'easy'})
        for q in app.PACK.questions:
            self.assertEqual(sum(matches(q,'all',mode) for mode in ('choices','text','image')),1)
        self.assertEqual(Counter('choices' if q.options else 'image' if q.requires_image else 'text' for q in app.PACK.questions),
                         {'choices':2000,'image':25,'text':174})

    async def test_specific_categories_advanced_options_and_empty_selection_are_safe(self):
        s=await self.lobby()
        self.assertEqual(len(screen.GROUPS),18)
        await app.handle_control(self.event(s),'advanced')
        self.assertEqual(s.lobby_page,'advanced')
        await app.handle_control(self.event(s,user(99)),'difficulty','hard')
        self.assertEqual(s.difficulty,'all')
        await app.handle_control(self.event(s),'difficulty','hard')
        await app.handle_control(self.event(s),'format','image')
        self.assertFalse(s.selected_questions())
        view=screen.lobby_panel(s,app.handle_control)
        start=next(i for i in view.walk_children() if getattr(i,'custom_id','')=='aa:start')
        self.assertTrue(start.disabled)
        await app.handle_control(self.event(s),'start')
        self.assertEqual(s.phase,'lobby')
        self.assertIsNone(s.runner)
        for group in screen.GROUPS:
            for level in LABELS:
                for mode in FORMATS:
                    s.group,s.difficulty,s.answer_mode=group,level,mode
                    selected=s.selected_questions()
                    self.assertTrue(all(matches(q,level,mode) for q in selected))
                    view=screen.lobby_panel(s,app.handle_control)
                    self.assertLessEqual(view.total_children_count,40)
                    self.assertLessEqual(view.content_length(),4000)

    async def test_review_counts_rounds_once_and_keeps_other_players_answers_private(self):
        s=await self.lobby()
        s.current_question=next(q for q in app.PACK.questions if q.id=='summon:cost')
        s.question_number=1
        s.track_attempt(user(42));s.track_attempt(user(42));s.track_attempt(user(99,'OtherPlayer'))
        s.finish_round_review(42);s.finish_round_review(42)
        self.assertEqual(s.performance[42]['attempts'],2)
        self.assertEqual(s.performance[42]['played'],1)
        self.assertEqual(s.performance[42]['won'],1)
        self.assertEqual(s.performance[99]['won'],0)
        s.checkpoint('finished')
        view=views.review_panel(self.repo.get(s.session_id),user(42),app.PACK,app.handle_control)
        text=view_text(view)
        self.assertIn('1 primeiro acerto',text)
        self.assertNotIn('OtherPlayer',text)
        self.assertNotIn('99',text)
        self.assertLessEqual(view.content_length(),4000)

    async def test_review_links_cannot_read_or_edit_another_channel(self):
        s=await self.lobby()
        other=await self.lobby()
        event=self.event(other)
        await app.handle_control(event,f'review_page:{s.session_id}:0')
        self.assertIn('outro canal',event.response.send_message.call_args.args[0])
        event.response.edit_message.assert_not_called()

    async def test_report_form_requires_revealed_question_and_moderation_is_private(self):
        s=await self.lobby()
        s.current_question=app.PACK.questions[0]
        s.remember_panel(resolved=False)
        event=self.event(s)
        await app.handle_control(event,'report')
        event.response.send_modal.assert_not_called()
        app.click_limits.clear()
        s.remember_panel(resolved=True)
        event=self.event(s)
        await app.handle_control(event,'report')
        event.response.send_modal.assert_awaited_once()
        self.repo.report(s.control_message.id,10,s.channel.id,42,'A imagem não corresponde à pergunta.')
        denied=self.event(s,user(99))
        await app.handle_control(denied,'reports')
        self.assertIn('moderação',denied.response.send_message.call_args.args[0])
        moderator=user(78);moderator.guild_permissions=SimpleNamespace(manage_guild=True)
        allowed=self.event(s,moderator)
        await app.handle_control(allowed,'reports')
        self.assertTrue(allowed.response.send_message.call_args.kwargs['ephemeral'])

    async def test_transfer_is_owner_only_rechecks_after_network_and_rejects_old_session(self):
        s=await self.lobby()
        outsider=self.event(s,user(99))
        await app.handle_control(outsider,'transfer_target',(s.session_id,'78'))
        self.assertEqual(s.host.id,42)
        allowed=self.event(s)
        await app.handle_control(allowed,'transfer_target',(s.session_id,'78'))
        self.assertEqual(s.host.id,78)
        stale=self.event(s,user(78))
        await app.handle_control(stale,'transfer_target',('f'*32,'99'))
        self.assertEqual(s.host.id,78)
        async def changed_during_fetch(uid):
            s.host=user(123)
            return SimpleNamespace(id=uid,display_name='Target',bot=False,guild=s.channel.guild)
        s.channel.guild.fetch_member.side_effect=changed_during_fetch
        await app.handle_control(self.event(s,user(78)),'transfer_target',(s.session_id,'99'))
        self.assertEqual(s.host.id,123)

    async def test_missing_host_is_verified_and_only_one_participant_can_claim(self):
        s=await self.lobby()
        s.channel.guild.fetch_member.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='no'), 'no')
        s.last_host_check=0
        await app.check_host_presence(s)
        self.assertFalse(s.host_missing)
        s.channel.guild.fetch_member.side_effect=discord.NotFound(SimpleNamespace(status=404,reason='gone'),'gone')
        s.last_host_check=0
        await app.check_host_presence(s)
        self.assertTrue(s.host_missing)
        s.track_attempt(user(78));s.track_attempt(user(99))
        outsider=self.event(s,user(77))
        await app.handle_control(outsider,'claim')
        self.assertTrue(s.host_missing)
        await asyncio.gather(app.handle_control(self.event(s,user(78)),'claim'),app.handle_control(self.event(s,user(99)),'claim'))
        self.assertEqual(s.host.id,78)
        self.assertFalse(s.host_missing)

    async def test_completed_review_is_bounded_and_all_private_panels_fit(self):
        s=await self.lobby()
        questions=[q for q in app.PACK.questions if q.requires_image]
        for i in range(60):
            s.question_number=i+1;s.current_question=questions[i%len(questions)]
            s.round_people={};s.round_reviewed=False
            s.track_attempt(user());s.finish_round_review(42 if i%2 else None)
        self.assertEqual(len(s.review_history),50)
        self.assertEqual(s.performance[42]['played'],60)
        state=json.loads(json.dumps(s.snapshot()))
        for page in (0,1,10,999):
            view=views.review_panel(state,user(),app.PACK,app.handle_control,page)
            self.assertLessEqual(view.total_children_count,40)
            self.assertLessEqual(view.content_length(),4000)
            discord.http.handle_message_parameters(view=view)
        self.assertLess(len(json.dumps(state).encode()),512*1024)

    async def test_native_dynamic_transfer_and_pagination_dispatch_exactly_once(self):
        s=await self.lobby()
        client=app.AdventuresBot()
        dispatch=AsyncMock()
        with patch.object(views.DynamicTransfer,'dispatch',dispatch),patch.object(views.DynamicControls,'dispatch',dispatch):
            view=views.manage_panel(s,s.host,app.handle_control)
            page=views.review_panel(s.snapshot(),s.host,app.PACK,app.handle_control)
            client.add_dynamic_items(views.DynamicTransfer,views.DynamicControls)
            for index,current in enumerate((view,page)):
                message=SimpleNamespace(id=300+index,flags=discord.MessageFlags._from_value(32768),
                    components=[discord.components._component_factory(c) for c in current.to_components()])
                client._connection.store_view(current,message_id=message.id)
                dynamic=next(i for i in current.walk_children() if isinstance(i,discord.ui.DynamicItem))
                event=self.event(s)
                event.message=message;event._state=client._connection
                event.data={'custom_id':dynamic.custom_id,'component_type':dynamic.type.value,'values':['78'],'resolved':{}}
                client._connection._view_store.dispatch_view(dynamic.type.value,dynamic.custom_id,event)
                await until(lambda:dispatch.await_count==index+1)
                await asyncio.sleep(.01)
                self.assertEqual(dispatch.await_count,index+1)
                current.stop()
        # This isolated client never logs in or closes the global production test sessions.

    async def test_rejoined_host_cannot_be_displaced_and_presence_lookup_cannot_undo_a_transfer(self):
        s=await self.lobby()
        s.host_missing=True;s.track_attempt(user(78))
        await app.handle_control(self.event(s,user(78)),'claim')
        self.assertEqual(s.host.id,42)
        self.assertFalse(s.host_missing)
        async def changing_host(uid):
            s.host=user(99)
            return SimpleNamespace(id=uid,display_name='Old host',bot=False,guild=s.channel.guild)
        s.channel.guild.fetch_member.side_effect=changing_host;s.last_host_check=0
        await app.check_host_presence(s)
        self.assertEqual(s.host.id,99)

    async def test_transfer_rejects_bots_and_members_from_other_guilds(self):
        s=await self.lobby()
        for target in (SimpleNamespace(id=78,display_name='Bot',bot=True,guild=s.channel.guild),
                       SimpleNamespace(id=78,display_name='Foreign',bot=False,guild=self.guild(99))):
            s.channel.guild.fetch_member.side_effect=None;s.channel.guild.fetch_member.return_value=target
            await app.handle_control(self.event(s),'transfer_target',(s.session_id,'78'))
            self.assertEqual(s.host.id,42)

    async def test_transfer_acknowledges_before_member_lookup_and_uses_private_followup(self):
        s=await self.lobby();event=self.event(s)
        event.response.is_done=lambda:bool(event.response.defer.await_count)
        async def target(uid):
            self.assertEqual(event.response.defer.await_count,1)
            return SimpleNamespace(id=uid,display_name='Target',bot=False,guild=s.channel.guild)
        s.channel.guild.fetch_member.side_effect=target
        await app.handle_control(event,'transfer_target',(s.session_id,'78'))
        event.response.send_message.assert_not_awaited()
        event.followup.send.assert_awaited_once()

    async def test_full_moderation_queue_and_untrusted_reason_fit_discord_limits(self):
        s=await self.lobby()
        queue={'total':5000,'page':1666,'items':[{'id':i,'question_id':s.pack.questions[0].id,
               'reason':('*@everyone\n'*40)[:400]} for i in range(3)]}
        panel=views.reports_panel(queue,10,app.PACK)
        self.assertLessEqual(panel.total_children_count,40)
        self.assertLessEqual(panel.content_length(),4000)
        self.assertNotIn('@everyone',view_text(panel))
        self.assertEqual(panel.timeout,300)
        discord.http.handle_message_parameters(view=panel)

    async def test_report_modal_cannot_be_submitted_by_another_user_or_channel(self):
        s=await self.lobby()
        modal=views.ReportModal(self.repo,s.control_message.id,10,s.channel.id,42)
        for actor,channel in [(user(99),s.channel.id),(user(42),s.channel.id+1)]:
            event=self.event(s,actor);event.channel_id=channel
            await modal.on_submit(event)
            self.assertIn('Abra o formulário',event.response.send_message.call_args.args[0])
        self.assertEqual(self.repo.reports(10)['total'],0)

    async def test_old_result_keeps_review_and_reporting_available_after_the_next_round(self):
        from datetime import datetime,timezone
        s=await self.lobby()
        s.current_question=next(q for q in app.PACK.questions if q.id=='summon:cost')
        s.next_at=datetime.now(timezone.utc);s.phase='intermission'
        old_message=s.control_message
        s.control_view=screen.result_panel(s,None,None,True,app.handle_control)
        s.remember_panel(resolved=True)
        view=s.control_view
        await s.retire_controls()
        buttons={i.custom_id:i for i in view.walk_children() if isinstance(i,discord.ui.Button) and not i.url}
        self.assertFalse(buttons['aa:review'].disabled)
        self.assertFalse(buttons['aa:report'].disabled)
        self.assertTrue(buttons['aa:pause'].disabled)
        event=self.event(s,message=old_message)
        await app.handle_control(event,'report')
        event.response.send_modal.assert_awaited_once()
