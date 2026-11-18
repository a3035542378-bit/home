import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import group_workers as workers
from ergou import agent_wechat as wx, group_tools, jobs
from ergou.db import DEFAULT, closing_db, dump, initialize
from ergou.engine import step
from tests.test_agent_wechat import Fixture


class ServerHandoffTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "snapshot.sqlite"
        initialize(path)
        self.db = self.enterContext(closing_db(path))
        self.api = Fixture()
        self.secret = "synthetic-node-key" * 3
        self.db.execute("CREATE TABLE migration_handoff(grp TEXT PRIMARY KEY,account TEXT,binding INTEGER)")
        self.db.execute("INSERT INTO account VALUES(?,'adapter','SUSPENDED')", (self.api.account,))
        self.seed_group(self.api.room)

    def seed_group(self,group):
        self.db.execute("INSERT INTO groups(id,account,binding,paused,config) VALUES(?,?,4,1,?)",
                        (group,self.api.account,dump(DEFAULT)))
        self.db.execute("INSERT INTO migration_handoff VALUES(?,?,4)",(group,self.api.account))

    def test_explicit_handoff_from_live_cursor_and_exact_directed_authorization(self):
        self.seed_group("other@chatroom")
        with self.assertRaisesRegex(ValueError,"多个候选"):
            workers.take_over(self.db,self.api,self.secret)
        self.assertTrue(workers.take_over(self.db,self.api,self.secret,self.api.room))
        self.assertEqual(self.db.execute("SELECT cursor FROM agent_wechat_links").fetchone()[0],"12")
        self.assertEqual(self.db.execute("SELECT grp FROM migration_handoff").fetchone()[0],"other@chatroom")
        listener = workers.DirectedListener(self.db,self.api,self.secret,None,4)
        listener.verify()
        self.assertTrue(listener.linked())
        self.assertEqual(wx.recovery_plan(self.db,self.api.slot),dict(listen=True,replies=True))
        for name in ("outbox","voice_approvals","member_notice_approvals","live_notices"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],0)
        self.assertEqual(workers.take_over(self.db,self.api,self.secret),False)
        from datetime import datetime, timezone
        self.api.details.update(body="二狗积分",createdAt=datetime.now(timezone.utc).isoformat())
        event = dict(cursor="13",kind="message.committed",data=dict(
            threadId=self.api.room,messageId=self.api.details["id"],direction="incoming",origin="live"))
        listener.consume(event)
        step(self.db)
        task = jobs.claim(self.db,self.api.account,directed_group=self.api.room)
        self.assertEqual((task["body"], task["grp"]),("本群积分 0",self.api.room))
        self.assertFalse(workers.take_over(self.db,self.api,self.secret))
        self.assertEqual(self.db.execute("SELECT cursor FROM agent_wechat_links").fetchone()[0],"13")
        self.db.execute("UPDATE groups SET paused=1 WHERE id=?", (self.api.room,))
        self.assertFalse(listener.linked())
        with self.assertRaises(wx.LinkRemoved):
            listener.consume(event)
        with self.assertRaises(ValueError):
            workers.take_over(self.db,self.api,self.secret,self.api.room)

    def test_not_member_wrong_account_changed_binding_and_pending_work(self):
        self.api.member_state="absent"
        with self.assertRaises(ValueError):
            workers.take_over(self.db,self.api,self.secret)
        self.api.member_state="present"
        with patch.object(self.api,"identity",return_value="other-account"), self.assertRaises(ValueError):
            workers.take_over(self.db,self.api,self.secret)
        self.db.execute("UPDATE groups SET binding=binding+1")
        with self.assertRaises(ValueError):
            workers.take_over(self.db,self.api,self.secret)
        self.db.execute("UPDATE groups SET binding=4")
        self.db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
                        VALUES('old',?,?,4,'测试','PENDING',?,?,?)""",(self.api.account,self.api.room,1,time.time()+60,1))
        with self.assertRaisesRegex(ValueError,"旧任务"):
            workers.take_over(self.db,self.api,self.secret)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],0)
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM migration_handoff").fetchone())

    def test_resume_and_repeat_takeover_never_restore_revocation(self):
        self.assertFalse(workers.current(self.db,self.api.slot))
        workers.take_over(self.db,self.api,self.secret)
        self.db.execute("DELETE FROM directed_groups")
        self.assertFalse(workers.current(self.db,self.api.slot))
        with self.assertRaises(ValueError):
            workers.take_over(self.db,self.api,self.secret)
        self.db.execute("INSERT INTO group_profile(grp) VALUES(?)",(self.api.room,))
        group_tools._detach(self.db,self.api.room,4)
        with self.assertRaises(ValueError):
            workers.take_over(self.db,self.api,self.secret)
        with patch.object(workers,"SLOT",self.api.slot):
            self.assertIn("没有可恢复", workers.run(self.db,"listen",Path("/missing")))
            self.assertIn("没有可恢复", workers.run(self.db,"replies",Path("/missing")))

    def test_transaction_rolls_back_partial_registration(self):
        with patch.object(workers,"audit",side_effect=RuntimeError), self.assertRaises(RuntimeError):
            workers.take_over(self.db,self.api,self.secret)
        for table in ("nodes","agent_wechat_links","node_grants","directed_groups"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT paused FROM groups").fetchone()[0],1)
        self.assertTrue(workers.take_over(self.db,self.api,self.secret))

    def test_direct_group_lookup_uses_only_the_explicit_event_boundary(self):
        member_page = self.api.base + "/groups/test%40chatroom/members?limit=1"
        original_get = self.api.get
        def get(path):
            if path == member_page:
                return {"items":[], "nextCursor":"99999"}
            return original_get(path)
        with patch.object(self.api,"resolve",side_effect=AssertionError("broad group search")):
            with patch.object(self.api,"get",side_effect=get), self.assertRaisesRegex(ValueError,"当前事件游标"):
                workers.take_over(self.db,self.api,self.secret)
            self.assertIsNone(self.db.execute("SELECT 1 FROM agent_wechat_links").fetchone())
            self.assertTrue(workers.take_over(self.db,self.api,self.secret))
            self.api.reads.clear()
            self.assertFalse(workers.take_over(self.db,self.api,self.secret))
            self.assertNotIn(member_page,self.api.reads)
