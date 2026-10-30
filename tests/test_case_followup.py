"""Case access, private replies and screenshot retention with fake APIs."""

import sqlite3
import unittest

from bot_storage import make_snapshot
from case_followup import CaseReview, case, followup
import test_banners as feeds


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
        ident=self.report();state=self.app.cases
        with state.db:state.db.execute('INSERT INTO bot_case_followup(kind,case_id,guild,image,image_type,image_expires,updated) VALUES(?,?,?,?,?,?,?)',('report',ident,'1',b'private screenshot bytes','png',self.now+86400,self.now))
        snapshot,_=make_snapshot(self.app.store.path)
        with sqlite3.connect(snapshot) as db:self.assertIsNone(db.execute('SELECT image FROM bot_case_followup').fetchone()[0])
        self.assertIsNotNone(followup(self.app,1,'report',ident)['image'])
        self.now+=86401;state.cleanup()
        self.assertIsNone(followup(self.app,1,'report',ident)['image'])

