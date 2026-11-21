import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ergou import admin, agent_wechat, exhibit_rewards, jobs
from ergou.db import BJ, closing_db, initialize, transaction
from tests.test_agent_wechat import Fixture


class ExhibitAnnouncements(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))/"bot.sqlite"
        initialize(path)
        self.db = self.enterContext(closing_db(path))
        self.api = Fixture()
        self.secret = "a"*40
        agent_wechat.link(self.db,self.api,"测试群",self.secret)
        agent_wechat.Listener(self.db,self.api,self.secret).verify()
        self.group = self.api.room
        self.now = time.time()
        self.period = (datetime.fromtimestamp(self.now,BJ).date()-timedelta(days=1)).isoformat()
        self.db.execute("INSERT INTO exhibit_reward_clock VALUES(?,?,1)",(self.group,self.period))
        self.ops = dict(name="fixture",role="运营管理员",scopes='["test@chatroom"]')

    def toggle(self,on):
        version=self.db.execute("SELECT version FROM groups WHERE id=?",(self.group,)).fetchone()[0]
        admin.configure(self.db,self.ops,self.group,version,dict(exhibit_board_push=on))

    def settle(self):
        with transaction(self.db):
            exhibit_rewards.maintenance(self.db,self.now)

    def seed(self):
        for i in range(12):
            key=(self.group,f"fixture-uid-{i:02}")
            self.db.execute("INSERT INTO fishing_wallets(grp,member) VALUES(?,?)",key)
            self.db.execute("INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price) VALUES(?,?,'白条',?,50,5)",(*key,i+1))
            self.db.execute("INSERT INTO asset_display_names VALUES(?,1,?,?,?)",(self.group,key[1],f"钓手{i}",self.now))

    def test_actual_credits_single_text_and_wechat_receipt(self):
        self.seed()
        self.toggle(True)
        self.settle()
        self.settle()
        self.assertEqual(self.db.execute("SELECT count(*) FROM outbox").fetchone()[0],1)
        with patch.object(agent_wechat,"send_direct",return_value=("ACKNOWLEDGED","微信已受理")) as sender:
            self.assertTrue(agent_wechat.replies(self.db,self.api,self.secret,"test",group=self.group,once=True))
            self.assertFalse(agent_wechat.replies(self.db,self.api,self.secret,"test",group=self.group,once=True))
            task=sender.call_args.args[2]
            self.assertEqual(task["grp"],self.group)
            rows=self.db.execute("SELECT member,points FROM ledger WHERE kind='图鉴日榜' ORDER BY id").fetchall()
            lines=task["body"].splitlines()
            self.assertEqual(len(rows),10)
            self.assertEqual(lines[1:-1],[f"第 {i+1} 名　钓手{i}　+{r['points']} 积分" for i,r in enumerate(rows)])
            self.assertIn(self.period,lines[0])
            self.assertIn("200 积分",lines[-1])
            self.assertNotIn("fixture-uid",task["body"])
            sender.assert_called_once()
        self.assertEqual(self.db.execute("SELECT state FROM outbox").fetchone()[0],"ACKNOWLEDGED")

    def test_off_does_not_change_rewards_or_replay_on_enable(self):
        self.seed()
        self.settle()
        self.toggle(True)
        self.settle()
        self.assertEqual(self.db.execute("SELECT sum(points) FROM ledger").fetchone()[0],200)
        self.assertIsNone(self.db.execute("SELECT 1 FROM outbox").fetchone())

    def test_empty_board_and_revocation(self):
        self.toggle(True)
        self.settle()
        self.assertIn("本期无人上榜",self.db.execute("SELECT body FROM outbox").fetchone()[0])
        self.toggle(False)
        self.toggle(True)
        self.assertFalse(jobs.claim(self.db,self.api.account,directed_group=self.group))
        self.assertEqual(self.db.execute("SELECT state FROM outbox").fetchone()[0],"CANCELLED")

    def test_switch_off_after_claim_and_forged_body(self):
        from ergou import exhibit_announcements
        self.toggle(True)
        self.settle()
        claim=jobs.claim(self.db,self.api.account,directed_group=self.group)
        self.assertTrue(exhibit_announcements.matches(self.db,claim))
        self.assertFalse(exhibit_announcements.matches(self.db,dict(claim,body="别的消息")))
        self.toggle(False)
        self.toggle(True)
        self.assertFalse(exhibit_announcements.matches(self.db,claim))
