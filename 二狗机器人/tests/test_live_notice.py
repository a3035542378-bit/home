import tempfile
import time
import unittest
from pathlib import Path

from ergou import agent_wechat, jobs, live_notice
from ergou.db import closing_db, initialize
from tests.test_agent_wechat import Fixture


class ApprovedNotices(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"robot.sqlite"
        initialize(path)
        self.db=self.enterContext(closing_db(path))
        self.api=Fixture()
        secret="t"*40
        agent_wechat.link(self.db,self.api,"测试群",secret)
        agent_wechat.Listener(self.db,self.api,secret).verify()
        self.now=time.time()
        self.due=self.now+4
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups",(self.now,))

    def notice(self,text="唯一原文",period="一次"):
        return self.db.execute("""INSERT INTO schedules(grp,body,period,due,catchup)
                               VALUES(?,?,?,?,0)""",(self.api.room,text,period,self.due)).lastrowid

    def claim(self):
        return jobs.claim(self.db,self.api.account,self.due+.3,directed_group=self.api.room)

    def test_confirm_exactly_once(self):
        sid=self.notice()
        self.notice("另一条")
        live_notice.approve(self.db,live_notice.preview(self.db,sid))
        jobs.tick(self.db,self.due+.1)
        jobs.tick(self.db,self.due+.2)
        task=self.claim()
        self.assertEqual(task["body"],"唯一原文")
        self.assertEqual(task["attempt"],1)
        self.assertFalse(self.claim())
        self.assertEqual(self.db.execute("SELECT count(*) FROM outbox").fetchone()[0],1)

    def test_edit_or_revoke_before_post(self):
        sid=self.notice()
        snap=live_notice.preview(self.db,sid)
        self.db.execute("UPDATE schedules SET body='已改',version=2 WHERE id=?",(sid,))
        with self.assertRaises(ValueError):live_notice.approve(self.db,snap)
        key=live_notice.approve(self.db,live_notice.preview(self.db,sid))
        jobs.tick(self.db,self.due)
        self.assertFalse(live_notice.matches(self.db,self.api.room,key,"旧原文"))
        self.db.execute("UPDATE schedules SET version=3 WHERE id=?",(sid,))
        self.assertFalse(live_notice.matches(self.db,self.api.room,key,"已改"))
        self.assertFalse(self.claim())

    def test_no_blanket_or_dynamic_approval(self):
        with self.assertRaises(ValueError):live_notice.preview(self.db,self.notice(period="每日"))
        sid=self.notice()
        self.db.execute("INSERT INTO bulletin_types VALUES(?,'weather')",(sid,))
        with self.assertRaises(ValueError):live_notice.preview(self.db,sid)
        self.db.execute("DELETE FROM directed_groups")
        with self.assertRaises(ValueError):live_notice.preview(self.db,self.notice())
