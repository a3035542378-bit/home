import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from deploy import group_stream
from ergou import agent_wechat as wx, db, engine, jobs
from tests.test_agent_wechat import Fixture


class GroupBindingTests(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"groups.sqlite"
        db.initialize(path)
        self.db=self.enterContext(db.closing_db(path))
        self.client=Fixture()
        self.secret="fixture"*8
        wx.link(self.db,self.client,"测试群",self.secret)
        self.a,self.b=self.client.room,"new@chatroom"
        self.client.member=Mock(return_value=True)
        self.db.execute("INSERT INTO directed_groups VALUES(?,?,1,?)",(self.a,self.client.account,time.time()-60))
        self.db.execute("INSERT INTO binding_streams SELECT slot,account,server_id,cursor FROM agent_wechat_links")
        self.db.execute("INSERT INTO binding_admins VALUES(?,'owner')",(self.client.account,))
        stream=self.db.execute("SELECT * FROM binding_streams").fetchone()
        self.worker=group_stream.Stream(self.db,self.client,self.secret,None,stream)
        self.worker.rosters=Mock()
        self.worker.verify()
        self.cursor=12

    def say(self,room,text,sender="owner",mentioned=True,old=False):
        self.cursor+=1
        now=datetime.fromtimestamp(time.time()-(200 if old else 0),timezone.utc)
        self.client.details.update(threadId=room,body=text,createdAt=now.isoformat(),senderId=sender,
            serverId=str(self.cursor),mentions=dict(state="known",self=mentioned,userIds=[self.client.account]))
        event=dict(cursor=str(self.cursor),kind="message.committed",data=dict(threadId=room,
            messageId=self.client.details["id"],origin="live",direction="incoming"))
        self.worker.consume(event)
        return event

    def test_authority_and_private_traffic(self):
        self.say("friend","@二狗 激活本群")
        self.say(self.b,"@二狗 激活本群",sender="stranger")
        self.say(self.b,"@二狗 激活本群",mentioned=False)
        self.say(self.b,"@二狗 激活本群",old=True)
        self.say(self.b,"二狗积分")
        self.assertFalse(self.db.execute("SELECT 1 FROM groups WHERE id=?",(self.b,)).fetchone())
        for table in ("inbox","outbox","binding_receipts"):
            self.assertEqual(self.db.execute("SELECT count(*) FROM "+table).fetchone()[0],0)

    def test_activate_pause_resume_and_scoped_delivery(self):
        event=self.say(self.b,"@二狗 激活本群")
        self.worker.consume(event)
        self.say(self.b,"@二狗 激活本群")
        self.assertEqual(set(self.worker.rooms),{self.a,self.b})
        with patch("ergou.agent_wechat.send_direct",return_value=("ACKNOWLEDGED","ok")) as send:
            self.assertTrue(group_stream.send_receipt(self.db,self.client,self.worker.stream,"test"))
            self.assertEqual(send.call_args.args[-1]["grp"],self.b)
        for room in (self.a,self.b):
            self.say(room,"二狗积分")
            self.assertTrue(engine.step(self.db))
            task=jobs.claim(self.db,self.client.account,directed_group=room)
            self.assertEqual(task["grp"],room)
            jobs.finish(self.db,self.client.account,task["id"],task["attempt"],"ACKNOWLEDGED","test")
        self.say(self.a,"@二狗 停用本群")
        self.assertEqual(set(self.worker.rooms),{self.b})
        self.say(self.a,"二狗积分")
        self.assertFalse(engine.step(self.db))
        self.say(self.b,"@二狗 停用本群")
        self.assertFalse(self.worker.rooms)
        self.say(self.a,"@二狗 绑定状态")
        self.say(self.a,"@二狗 激活本群")
        self.assertEqual(set(self.worker.rooms),{self.a})
        self.assertEqual(self.db.execute("SELECT count(*) FROM binding_receipts").fetchone()[0],6)
        self.assertEqual(self.db.execute("SELECT binding FROM groups WHERE id=?",(self.a,)).fetchone()[0],2)
        self.db.execute("DELETE FROM binding_admins")
        self.say(self.b,"@二狗 激活本群")
        self.assertEqual(set(self.worker.rooms),{self.a})
