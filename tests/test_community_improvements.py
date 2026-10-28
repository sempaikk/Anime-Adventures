"""Local moderator access, official-only feedback and member-visible failure reasons."""

import unittest
from types import SimpleNamespace

import discord

import test_global_chat as fixtures
from bot_permissions import require_moderator
from community_feedback import CommunityFeedback,FeedbackInbox
from community_hub import CENTRAL_GUILD_ID
from community_views import GlobalModeratorView,MemberHome
from global_views import GlobalMemberView,ModerationModal,GlobalAdminView
from global_reports import ReportInbox,ReportDecision


class CommunityImprovements(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ChatCase.asyncSetUp
    asyncTearDown=fixtures.ChatCase.asyncTearDown
    fetch=fixtures.ChatCase.fetch
    history=fixtures.ChatCase.history
    send_notice=fixtures.ChatCase.send_notice
    message=fixtures.ChatCase.message
    interaction=fixtures.ChatCase.interaction
    copies=fixtures.ChatCase.copies
    flush=fixtures.ChatCase.flush
    asset=fixtures.ChatCase.asset

    def moderator(self):
        i=self.interaction(gid=2,user=9,admin=False)
        i.permissions=discord.Permissions(manage_messages=True,moderate_members=True)
        return i

    async def test_moderator_can_review_only_local_reports_without_manage_server(self):
        source=self.message()
        await self.engine.ingest(source)
        await self.flush()
        self.engine.store.report(source.id,8,2,'A synthetic local moderation report')
        i=self.moderator()
        require_moderator(i)
        view=GlobalModeratorView(self.app,i)
        self.assertEqual({x.label for x in view.children},{'Server reports','Local restrictions','My participation'})
        inbox=ReportInbox(self.app,i)
        row=self.engine.store.report_page(2)[0][0]
        self.assertIn('this server',inbox.description())
        modal=ReportDecision(self.app,i,row,2)
        modal.action._values=['block-hour']
        modal.reason._value='A private temporary moderation decision'
        await modal.on_submit(i)
        self.assertTrue(self.engine.store.blocked(7,2))
        self.assertFalse(self.engine.store.blocked(7,3))
        with self.assertRaises(ValueError):
            self.app.require_admin(i)

    async def test_local_moderator_cannot_forge_owner_or_configuration_access(self):
        i=self.moderator()
        with self.assertRaises(ValueError):
            GlobalAdminView(self.app,i).require(i)
        with self.assertRaises(ValueError):
            ReportInbox(self.app,i,network=True).require(i)
        modal=ModerationModal(self.app,i,network=True)
        modal.action._values=['block-guild']
        modal.target._value='3'
        modal.reason._value='A forged network-wide decision'
        with self.assertRaises(ValueError):
            await modal.on_submit(i)
        self.assertFalse(self.engine.store.blocked(0,3))

    async def test_failed_attempt_is_private_without_message_content_and_expires(self):
        self.author.send.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),{'code':50007,'message':'Cannot send'})
        source=self.message(content='PRIVATE_BODY_SENTINEL',attachments=[self.asset('wrong.png',b'not an image')])
        await self.engine.ingest(source)
        attempt=self.engine.store.last_attempt(7,1)
        self.assertEqual(attempt['state'],'not_shared')
        self.assertNotIn(source.content,str(attempt))
        view=GlobalMemberView(self.app,self.interaction())
        self.assertIn('Last attempt',view.description())
        self.now[0]+=3601
        self.engine.store.cleanup()
        self.assertIsNone(self.engine.store.last_attempt(7,1))

    async def test_feedback_is_official_only_deduplicated_private_and_bounded(self):
        self.app.feedback=CommunityFeedback(self.app)
        ordinary=self.interaction()
        with self.assertRaises(ValueError):
            self.app.feedback.submit(ordinary,'bug','A synthetic bug description')
        official=self.interaction()
        official.guild_id=CENTRAL_GUILD_ID
        ident=self.app.feedback.submit(official,'suggestion','A synthetic community suggestion')
        self.assertEqual(self.app.feedback.submit(official,'suggestion','A synthetic community suggestion'),ident)
        self.assertNotIn('Feedback',{x.label for x in MemberHome(self.app,ordinary).children})
        self.assertIn('Feedback',{x.label for x in MemberHome(self.app,official).children})
        owner=FeedbackInbox(self.app,official)
        self.assertIn('synthetic',owner.description())
        intruder=self.interaction(user=8)
        intruder.guild_id=CENTRAL_GUILD_ID
        with self.assertRaises(ValueError):
            FeedbackInbox(self.app,intruder)
        await owner.resolve.callback(official)
        self.assertEqual(self.base.rows('SELECT status FROM bot_feedback')[0]['status'],'resolved')
        self.assertFalse([m for m in self.messages.values() if not m.guild])
        self.now[0]+=30*86400+1
        self.app.feedback.cleanup()
        self.assertEqual(self.base.rows('SELECT * FROM bot_feedback'),[])

    async def test_shared_celebration_text_does_not_restrict_entire_server(self):
        for uid in range(100,108):
            author=SimpleNamespace(**{**vars(self.author),'id':uid})
            self.engine.store.consent(uid)
            await self.engine.ingest(self.message(content='Happy birthday, community friend!',author=author))
        self.assertFalse(self.engine.store.restriction(7,1))

    async def test_feedback_review_rejects_stale_decisions(self):
        self.app.feedback=CommunityFeedback(self.app)
        i=self.interaction()
        i.guild_id=CENTRAL_GUILD_ID
        self.app.feedback.submit(i,'bug','A synthetic issue for versioned review')
        first,second=FeedbackInbox(self.app,i),FeedbackInbox(self.app,i)
        first.description();second.description()
        await first.resolve.callback(i)
        with self.assertRaises(ValueError):
            await second.dismiss.callback(i)

    async def test_one_account_burst_does_not_restrict_other_members(self):
        for n in range(121):
            await self.engine.ingest(self.message(content='Synthetic distinct burst attempt '+str(n)))
        self.assertTrue(self.engine.store.restriction(7,1))
        self.assertFalse(self.engine.store.restriction(9,1))

    async def test_confirmed_community_invite_and_minimum_install_permissions(self):
        from community_views import HelpView
        from urllib.parse import urlsplit,parse_qs
        view=HelpView(self.app,self.interaction())
        links={item.label:item.url for item in view.children}
        self.assertEqual(links['Official community'],'https://discord.gg/qwH7DvdtDZ')
        permissions=discord.Permissions(int(parse_qs(urlsplit(links['Add Adventures']).query)['permissions'][0]))
        self.assertFalse(permissions.administrator)
        self.assertFalse(permissions.manage_roles)
        self.assertTrue(permissions.manage_webhooks)
