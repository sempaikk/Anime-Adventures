"""Lost acknowledgements, cancellation, scoped cases and party publication; fake APIs only."""

from datetime import datetime, timedelta, timezone
import io
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

import test_banners as feeds
from adventure_admin import SettingsConfirm, FeedSetupReview
from adventure_views import PartyPreview
from bot_storage import make_snapshot
from case_followup import CaseReview, case, followup


class DeliveryCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=feeds.BannerCase.asyncSetUp
    asyncTearDown=feeds.BannerCase.asyncTearDown
    add_channel=feeds.BannerCase.add_channel
    send=feeds.BannerCase.send
    event=feeds.BannerCase.event
    interaction=feeds.BannerCase.interaction

    def dm_environment(self):
        self.app.store.clock=lambda:self.now
        self.dm_messages=[]
        self.posts=[]
        self.dm=SimpleNamespace(id=900,history=lambda **kwargs:feeds.iterate(self.dm_messages))
        self.person=SimpleNamespace(id=7,dm_channel=self.dm,create_dm=AsyncMock(return_value=self.dm))
        self.guild=self.channels[10].guild
        self.guild.get_member=lambda user:self.person if user==7 else None
        self.guild.fetch_member=AsyncMock(return_value=self.person)
        self.app.get_guild=lambda ident:self.guild if ident==1 else None
        self.app.get_user=lambda ident:self.person if ident==7 else None
        self.app.http.send_message=AsyncMock(side_effect=self.dm_post)

    async def dm_post(self,channel,*,params):
        body=params.payload
        self.posts.append((channel,body))
        m=SimpleNamespace(id=1000+len(self.posts),nonce=body.get('nonce'),content=body.get('content',''),author=SimpleNamespace(id=42),webhook_id=None,created_at=datetime.fromtimestamp(self.now,timezone.utc))
        self.dm_messages.append(m)
        return {'id':str(m.id)}

    async def test_reminder_posts_once_with_persistent_nonce(self):
        self.dm_environment();state=self.app.adventures.state
        ident=state.reminder(7,1,'Private action',self.now+60);self.now+=61
        row=state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,))
        await self.app.adventures.deliver_reminder(row)
        await self.app.adventures.deliver_reminder(row)
        self.assertEqual(len(self.posts),1)
        self.assertTrue(self.posts[0][1]['enforce_nonce'])
        self.assertEqual(state.one('SELECT state FROM bot_tool_reminders WHERE id=?',(ident,))['state'],'sent')

    async def test_lost_ack_is_reconciled_without_a_second_post(self):
        self.dm_environment();state=self.app.adventures.state
        ident=state.reminder(7,1,'Private action',self.now+60);self.now+=61
        async def lose(channel,*,params):
            await self.dm_post(channel,params=params)
            raise TimeoutError('synthetic loss')
        self.app.http.send_message=AsyncMock(side_effect=lose)
        await self.app.adventures.deliver_reminder(state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,)))
        self.assertEqual(state.one('SELECT state FROM bot_tool_reminders WHERE id=?',(ident,))['state'],'uncertain')
        await self.app.adventures.deliver_reminder(state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,)))
        self.assertEqual(state.one('SELECT state FROM bot_tool_reminders WHERE id=?',(ident,))['state'],'sent')
        self.assertEqual(len(self.posts),1)

    async def test_uncertain_without_evidence_never_reposts_or_blocks_new_due_items(self):
        self.dm_environment();state=self.app.adventures.state
        old=state.reminder(7,1,'Unknown previous attempt',self.now+60)
        new=state.reminder(7,1,'New known reminder',self.now+61)
        with state.db:state.db.execute("UPDATE bot_tool_reminders SET state='uncertain',attempted=? WHERE id=?",(self.now,old))
        self.now+=62
        await self.app.adventures.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertIn('New known reminder',self.posts[0][1]['content'])
        self.assertEqual(state.one('SELECT state FROM bot_tool_reminders WHERE id=?',(old,))['state'],'uncertain')
        await self.app.adventures.cycle()
        self.assertEqual(len(self.posts),1)

    async def test_cancel_during_dm_lookup_stops_publication(self):
        self.dm_environment();state=self.app.adventures.state
        ident=state.reminder(7,1,'Cancel before send',self.now+60);self.now+=61
        self.person.dm_channel=None
        async def cancel():
            state.cancel(7,ident);return self.dm
        self.person.create_dm=cancel
        await self.app.adventures.deliver_reminder(state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,)))
        self.assertEqual(self.posts,[])

    async def test_module_disabled_during_dm_lookup_stops_publication(self):
        self.dm_environment();state=self.app.adventures.state
        ident=state.reminder(7,1,'Disabled before send',self.now+60);self.now+=61
        self.person.dm_channel=None
        async def disable():
            data,version=state.settings(1);data['modules']=[];state.configure(1,7,data,version)
            return self.dm
        self.person.create_dm=disable
        await self.app.adventures.deliver_reminder(state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,)))
        self.assertEqual(self.posts,[])

    async def test_closed_dms_mark_blocked_without_public_fallback(self):
        self.dm_environment();state=self.app.adventures.state
        ident=state.reminder(7,1,'Private action',self.now+60);self.now+=61
        self.app.http.send_message=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),{'code':50007,'message':'Synthetic closed DMs'}))
        await self.app.adventures.deliver_reminder(state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,)))
        row=state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,))
        self.assertEqual(row['state'],'blocked')
        self.assertIn('No public fallback',row['error'])
        self.assertEqual(self.posts,[])

    async def test_overdue_reminders_make_one_digest_with_individual_receipts(self):
        self.dm_environment();state=self.app.adventures.state
        ids=[state.reminder(7,1,'Task '+str(n),self.now+60+n) for n in range(3)]
        self.now+=1000
        await self.app.adventures.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertIn('digest',self.posts[0][1]['content'])
        rows=state.rows('SELECT state,message FROM bot_tool_reminders')
        self.assertEqual({r['state'] for r in rows},{'sent'})
        self.assertEqual(len({r['message'] for r in rows}),1)

    async def test_cancel_one_item_before_digest_send_preserves_other_requested_reminders(self):
        self.dm_environment();state=self.app.adventures.state
        first=state.reminder(7,1,'One',self.now+60)
        second=state.reminder(7,1,'Two',self.now+61)
        self.now+=1000;state.bundle_due();state.cancel(7,first)
        await self.app.adventures.cycle()
        self.assertEqual(len(self.posts),1)
        self.assertNotIn('\nOne\n',self.posts[0][1]['content'])
        self.assertIn('Two',self.posts[0][1]['content'])

    async def test_feed_opt_out_after_bundling_prevents_notifications(self):
        self.dm_environment();state=self.app.adventures.state
        ids=[state.reminder(7,1,'Source '+str(n),self.now+60) for n in range(2)]
        with state.db:state.db.execute("UPDATE bot_tool_reminders SET purpose='feed'")
        self.now+=61;state.bundle_due()
        await self.app.adventures.cycle();await self.app.adventures.cycle()
        self.assertEqual(self.posts,[])

    async def test_quiet_hours_postpone_only_the_reminder(self):
        self.dm_environment();state=self.app.adventures.state
        ident=state.reminder(7,1,'Quiet action',self.now+60);self.now+=61
        hour=datetime.fromtimestamp(self.now,timezone.utc).hour
        state.set_preferences(7,'UTC',hour,(hour+1)%24)
        await self.app.adventures.deliver_reminder(state.one('SELECT * FROM bot_tool_reminders WHERE id=?',(ident,)))
        self.assertFalse(self.posts)
        self.assertGreater(state.one('SELECT due FROM bot_tool_reminders WHERE id=?',(ident,))['due'],self.now)

    async def test_party_preview_does_not_publish_and_actual_publish_is_once(self):
        state=self.app.adventures.state;self.app.store.clock=lambda:self.now
        channel=self.channels[10];channel.is_nsfw.return_value=False;channel.type=discord.ChannelType.text
        data,version=state.settings(1);data['party_channel']='10';state.configure(1,7,data,version)
        ident=state.party(1,10,7,'Dungeon',self.now+60,4)
        i=self.interaction();view=PartyPreview(self.app,i,ident)
        self.assertFalse(self.sent)
        sent=[]
        async def post(channel,*,params):sent.append(params.payload);return {'id':'9001'}
        self.app.http.send_message=AsyncMock(side_effect=post)
        first=await self.app.adventures.publish_party(ident,i)
        again=await self.app.adventures.publish_party(ident,i)
        self.assertEqual(first['message'],again['message'])
        self.assertEqual(len(sent),1)
        self.assertTrue(sent[0]['enforce_nonce'])
        self.assertEqual(state.party_record(ident,1)['state'],'open')

    async def test_party_lost_ack_stays_uncertain_without_republishing(self):
        state=self.app.adventures.state;self.app.store.clock=lambda:self.now
        channel=self.channels[10];channel.is_nsfw.return_value=False;channel.type=discord.ChannelType.text
        data,version=state.settings(1);data['party_channel']='10';state.configure(1,7,data,version)
        ident=state.party(1,10,7,'Dungeon',self.now+60,4)
        self.app.http.send_message=AsyncMock(side_effect=TimeoutError())
        with self.assertRaises(ValueError):await self.app.adventures.publish_party(ident,self.interaction())
        with self.assertRaises(ValueError):await self.app.adventures.publish_party(ident,self.interaction())
        self.assertEqual(self.app.http.send_message.await_count,1)
        self.assertEqual(state.party_record(ident,1)['state'],'uncertain')

    async def test_group_channel_cannot_be_a_feed_or_global_channel(self):
        self.app.banners.configure(1,10)
        self.channels[10].is_nsfw.return_value=False
        with self.assertRaises(ValueError):self.app.adventures.normal_channel(self.channels[10],SimpleNamespace(id=7))

    async def test_feed_setup_is_a_preview_until_confirmed(self):
        i=self.interaction();i.response.send_modal=AsyncMock()
        view=FeedSetupReview(self.app,i,'daily',10)
        self.assertIn('Review',view.description())
        self.assertIsNone(self.app.daily.target(1))
        await view.confirm.callback(i)
        self.assertEqual(self.app.daily.target(1)['channel_id'],'10')
        with self.assertRaises(ValueError):await view.confirm.callback(i)

    async def test_every_game_form_has_a_working_private_submission_path(self):
        from adventure_views import ToolForm
        self.app.store.clock=lambda:self.now
        state=self.app.adventures.state
        data,version=state.settings(1);data['party_channel']='10';state.configure(1,7,data,version)
        valid={
          'units':{'query':'Shinobi'},'items':{'query':'Star Fruit'},'guides':{'query':'Evolution'},
          'filter':{'query':'','damage':'magic','element':'','placement':''},
          'compare':{'first':'sasuke_3_evolved','second':'sasuke_3'},
          'team':{'name':'My team','units':'sasuke_3_evolved\nrukia','notes':'Manual team'},
          'coverage':{'units':'sasuke_3_evolved\nrukia'},
          'goal':{'name':'My evolution','unit':'sasuke_3_evolved','priority':'1'},
          'materials':{'materials':'StarFruit=12'},'owned':{'unit':'sasuke_3_evolved','status':'wanted'},
          'dps':{'damage':'10000','spa':'5','crit':'20','multiplier':'1.5','towers':'3'},
          'chance':{'rate':'1','attempts':'100','target':'95'},'budget':{'resources':'100','price':'5'},
          'farm':{'missing':'10','reward':'2','minutes':'3','success':'100'},
          'run':{'name':'Manual run','mode':'Dungeon','minutes':'25','result':'completed','loot':'Observed three chests'},
          'daily':{'objective':'safety','modifiers':'Flight, Regen','coverage':'Manual air coverage'},
          'dungeon':{'objective':'chests','modifiers':"Rare Chest, Genie Lamp, Golden Fishhook, Archmage's Hat, Philosopher's Stone",'coverage':'Magic team'},
          'party':{'mode':'Dungeon','when':'30','capacity':'4','requirements':'Review before publishing'},
          'template':{'name':'Dungeon template','mode':'Dungeon','capacity':'4','requirements':'Magic team'},
          'reminder':{'body':'Explicitly requested reminder','when':'60'},
          'preferences':{'timezone':'America/Sao_Paulo','start':'22','end':'8','alerts':'no'},
        }
        for action,values in valid.items():
            with self.subTest(action=action):
                i=self.interaction();i.user.bot=False;i.user.created_at=discord.utils.utcnow()-timedelta(days=30)
                form=ToolForm(self.app,i,action)
                for key,value in values.items():form.inputs[key]._value=value
                await form.on_submit(i)
                self.assertTrue(i.followup.send.await_count or i.response.send_message.await_count if hasattr(i.response,'send_message') else i.followup.send.await_count)
        self.assertEqual(self.sent,[])
        self.assertEqual(state.one("SELECT count(*) n FROM bot_tool_parties WHERE state='draft'")['n'],1)

    async def test_source_notifications_require_opt_in_and_skip_retracted_updates(self):
        self.dm_environment();state=self.app.adventures.state
        state.set_preferences(7,'UTC',alerts=True,guild=1)
        self.relay.configure(1,10)
        self.relay.status='ready'
        self.relay.diagnostics.poll()
        self.relay.diagnostics.observe('123456789012345678',self.now)
        self.relay.diagnostics.received(message_id='123456789012345678',created=self.now)
        self.app.adventures.feed_notifications()  # Seed, do not advertise history.
        self.assertEqual(state.rows('SELECT * FROM bot_tool_reminders'),[])
        self.now+=60;self.relay.diagnostics.poll()
        source='123456789012345679'
        self.relay.diagnostics.observe(source,self.now)
        self.relay.diagnostics.received(message_id=source,created=self.now)
        self.app.adventures.feed_notifications()
        rows=state.rows('SELECT * FROM bot_tool_reminders')
        self.assertEqual(len(rows),1)
        self.relay.diagnostics.retract(source)
        await self.app.adventures.deliver_reminder(rows[0])
        self.assertEqual(self.posts,[])
        self.assertEqual(state.one('SELECT state FROM bot_tool_reminders')['state'],'cancelled')

    async def test_native_events_require_administrator_opt_in_and_close_only_owned_events(self):
        from adventure_views import PartyAction
        self.dm_environment();state=self.app.adventures.state
        channel=self.channels[10];channel.is_nsfw.return_value=False;channel.type=discord.ChannelType.text
        data,version=state.settings(1);data['party_channel']='10';state.configure(1,7,data,version)
        ident=state.party(1,10,7,'Dungeon',self.now+60,4)
        with state.db:state.db.execute("UPDATE bot_tool_parties SET state='open',message='9001' WHERE id=?",(ident,))
        event=SimpleNamespace(id=5001,creator_id=42,status=discord.EventStatus.scheduled,edit=AsyncMock())
        self.guild.create_scheduled_event=AsyncMock(return_value=event)
        self.guild.fetch_scheduled_event=AsyncMock(return_value=event)
        self.guild.scheduled_events=[]
        self.guild.me.guild_permissions=discord.Permissions(create_events=True)
        i=self.interaction();i.user.bot=False;i.user.created_at=discord.utils.utcnow()-timedelta(days=30);i.message=SimpleNamespace(id=9001)
        action=PartyAction('event',ident)
        await action.callback(i)
        self.guild.create_scheduled_event.assert_not_awaited()
        data,version=state.settings(1);data['modules'].append('events');state.configure(1,7,data,version)
        await action.callback(i)
        self.guild.create_scheduled_event.assert_awaited_once()
        self.assertIn('Group '+ident,self.guild.create_scheduled_event.call_args.kwargs['description'])
        with state.db:state.db.execute("UPDATE bot_tool_parties SET state='closed',message=NULL,version=version+1 WHERE id=?",(ident,))
        await self.app.adventures.cycle()
        event.edit.assert_awaited_once()
        self.assertEqual(event.edit.call_args.kwargs['status'],discord.EventStatus.cancelled)


class CasesCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=feeds.BannerCase.asyncSetUp
    asyncTearDown=feeds.BannerCase.asyncTearDown
    add_channel=feeds.BannerCase.add_channel
    send=feeds.BannerCase.send
    event=feeds.BannerCase.event
    interaction=feeds.BannerCase.interaction

    def report(self):
        self.app.store.clock=lambda:self.now
        with self.app.store.connection:
            cursor=self.app.store.connection.execute('INSERT INTO global_reports(source_id,reporter,guild_id,reason,created) VALUES(?,?,?,?,?)',('synthetic-source','8','1','Synthetic case reason',self.now))
        return cursor.lastrowid

    async def test_case_access_is_bound_to_reporter_and_guild(self):
        ident=self.report()
        self.assertEqual(case(self.app,self.interaction(actor=8),'report',ident)['user'],'8')
        for i in (self.interaction(actor=9),self.interaction(guild=2,channel=20,actor=8)):
            with self.assertRaises(ValueError):case(self.app,i,'report',ident)
        with self.assertRaises(ValueError):case(self.app,self.interaction(actor=8),'feedback',ident)

    async def test_staff_answer_is_private_and_requires_current_case_version(self):
        ident=self.report();i=self.interaction(actor=7)
        first=CaseReview(self.app,i,'report',ident);second=CaseReview(self.app,i,'report',ident)
        first.action._values=['answer'];first.body._value='Your report was reviewed.'
        await first.on_submit(i)
        row=followup(self.app,1,'report',ident)
        self.assertEqual(row['answer'],'Your report was reviewed.')
        self.assertEqual(self.sent,[])
        second.action._values=['answer'];second.body._value='A stale conflicting answer.'
        with self.assertRaises(ValueError):await second.on_submit(i)

    async def test_non_moderator_cannot_assume_or_answer_case(self):
        ident=self.report()
        with self.assertRaises(ValueError):CaseReview(self.app,self.interaction(actor=9,admin=False),'report',ident)

    async def test_screenshot_is_removed_from_snapshot_and_expires_in_live_state(self):
        ident=self.report();state=self.app.adventures.state
        with state.db:state.db.execute('INSERT INTO bot_case_followup(kind,case_id,guild,image,image_type,image_expires,updated) VALUES(?,?,?,?,?,?,?)',('report',ident,'1',b'private screenshot bytes','png',self.now+86400,self.now))
        snapshot,_=make_snapshot(self.app.store.path)
        with sqlite3.connect(snapshot) as db:self.assertIsNone(db.execute('SELECT image FROM bot_case_followup').fetchone()[0])
        self.assertIsNotNone(followup(self.app,1,'report',ident)['image'])
        self.now+=86401;state.cleanup()
        self.assertIsNone(followup(self.app,1,'report',ident)['image'])
