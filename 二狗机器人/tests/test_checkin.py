import sqlite3
import tempfile
import time
import unittest
from tests.menu_commands import commands
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from ergou import agent_wechat, db, engine, fishing_bait, jobs
from tests.test_agent_wechat import Fixture


class CheckinTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "checkin.sqlite"
        db.initialize(self.path)
        db.demo(self.path, ("east", "west"))
        self.conn = self.enterContext(db.closing_db(self.path))
        self.midnight = datetime(2026, 11, 21, tzinfo=db.BJ).timestamp()
        self.seq = 0

    def say(self, text, now, group="east", member="leaf", source=None):
        self.seq += 1
        seq = engine.receive(self.conn, "sim-account", group, member, source or str(self.seq),
                             {"text":text}, now=now)
        engine.step(self.conn)
        row = self.conn.execute("SELECT body FROM outbox JOIN inbox ON biz=event_id WHERE seq=?", (seq,)).fetchone()
        return row[0] if row else None

    def test_day_boundary_restart_replay_and_isolation(self):
        before = self.midnight - .0001
        receipt = self.say("二狗签到", before, source="original")
        self.assertEqual(receipt, "✅ 签到到账 +3 积分，本群余额 3 分。\n离高级鱼饵还差 2 分。")
        self.assertIn("已经签过啦，本群积分 3 分", self.say("二狗打卡", before))
        self.assertEqual(self.say("二狗打卡", before, group="west"), receipt)
        self.assertEqual(self.say("二狗签到", before, member="other"), receipt)
        self.conn.close()
        db.initialize(self.path)
        self.conn = self.enterContext(db.closing_db(self.path))
        self.assertEqual(self.say("二狗签到", self.midnight, source="original"), receipt)
        second = self.say("二狗打卡", self.midnight)
        self.assertIn("本群余额 6 分", second)
        self.assertEqual(second.splitlines()[-1], "二狗鱼饵")
        self.assertIn("高级鱼饵　5 积分", self.say(second.splitlines()[-1], self.midnight))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ledger WHERE kind='签到'").fetchone()[0], 4)

    def test_concurrent_clicks_across_connections(self):
        barrier = Barrier(6)
        def click(n):
            with db.closing_db(self.path) as conn:
                barrier.wait(5)
                engine.receive(conn, "sim-account", "east", "leaf", f"click-{n}", {"text":"二狗打卡"}, now=self.midnight)
                engine.step(conn)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(click, range(6)))
        replies = [r[0] for r in self.conn.execute("SELECT body FROM outbox")]
        self.assertEqual(len(replies),6)
        self.assertEqual(sum("签到到账" in r for r in replies),1)
        self.assertEqual(sum("已经签过" in r for r in replies),5)
        self.assertEqual(fishing_bait.balance(self.conn,("east","leaf")),3)

    def test_failed_reply_rolls_back_credit_and_can_retry(self):
        engine.receive(self.conn,"sim-account","east","leaf","retry",{"text":"二狗签到"},now=self.midnight)
        self.conn.execute("""CREATE TEMP TRIGGER fail_reply BEFORE INSERT ON outbox
                             BEGIN SELECT RAISE(ABORT,'fixture failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            engine.step(self.conn)
        self.assertFalse(self.conn.execute("SELECT 1 FROM ledger").fetchone())
        self.conn.execute("DROP TRIGGER fail_reply")
        engine.step(self.conn)
        self.assertEqual(fishing_bait.balance(self.conn,("east","leaf")),3)

    def test_spend_credit_on_bait_and_redeem_other_group_reward(self):
        day = self.midnight
        for group in ("east","west"):
            self.say("二狗签到",day-1,group=group)
            self.say("二狗打卡",day,group=group)
        bait = self.say("二狗鱼饵",day)
        command = next(cmd for cmd in commands(bait) if cmd=="二狗抛竿 高级鱼饵")
        with patch("ergou.fish_grades.award_first_grade_points",return_value=0):
            self.assertIn("扣饵后余 1 分",self.say(command,day))
        self.assertIn("已经签过啦，本群积分 1 分",self.say("二狗签到",day))
        self.conn.execute("INSERT INTO reward_offers VALUES('west','选片权',5)")
        command = self.say("二狗兑换列表",day,group="west").splitlines()[-1]
        self.assertIn("已扣 5 分，剩余 1 分",self.say(command,day,group="west"))
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT grp,kind,points FROM ledger WHERE points<0 ORDER BY grp")],
                         [("east","鱼饵",-5),("west","兑换",-5)])

    def test_closed_fishing_and_custom_prefix(self):
        self.conn.execute("INSERT INTO reward_offers VALUES('west','选片权',5)")
        for field in ("'$.disabled_games',json_array('钓鱼')","'$.games',json('false')"):
            self.conn.execute(f"UPDATE groups SET config=json_set(config,'$.prefix','团团',{field}) WHERE id='west'")
            for i in range(2):
                reply=self.say("团团签到",self.midnight+86400*i,group="west",member=field)
                self.assertNotIn("鱼饵",reply)
                self.assertIn("团团兑换列表",reply)
        self.conn.execute("DELETE FROM reward_offers WHERE grp='west'")
        self.assertIn("团团积分",self.say("团团打卡",self.midnight,group="west",member="new"))
        self.assertIn("【签到】",self.say("团团菜单",self.midnight+86400,group="west"))

    def test_wechat_real_mention_and_local_prefix(self):
        api=Fixture()
        secret="fixture"*8
        agent_wechat.link(self.conn,api,"测试群",secret)
        listener=agent_wechat.Listener(self.conn,api,secret)
        listener.verify()
        self.conn.execute("INSERT INTO directed_groups VALUES(?,?,1,?)",(api.room,api.account,time.time()-5))
        self.conn.execute("INSERT INTO chat_models VALUES(?,1,'glm','fixture',?,?)",(api.room,b'fixture',time.time()))
        self.conn.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES(?,1,1)",(api.room,))
        def send(n, text, mentioned=False):
            api.details.update(body=text,serverId=str(n),createdAt=datetime.now(timezone.utc).isoformat(),
                               mentions={"state":"known","self":mentioned,"all":False,"userIds":[api.account] if mentioned else []})
            seq=listener.consume(dict(cursor=str(n),kind="message.committed",data=dict(
                threadId=api.room,messageId=api.details["id"],origin="live",direction="incoming")))
            engine.step(self.conn)
            return seq
        self.assertIsNone(send(13,"签到"))
        self.assertIsNone(send(14,"打卡"))
        send(15,"@二狗\u2005签到",True)
        self.assertEqual(self.conn.execute("SELECT prompt FROM chat_requests").fetchone()[0],"签到")
        self.assertFalse(self.conn.execute("SELECT 1 FROM ledger").fetchone())
        send(16,"二狗签到")
        task=jobs.claim(self.conn,api.account,directed_group=api.room)
        self.assertIn("本群余额 3 分",task["body"])
        jobs.finish(self.conn,api.account,task["id"],task["attempt"],"ACKNOWLEDGED","fixture")
        send(17,"二狗打卡")
        task=jobs.claim(self.conn,api.account,directed_group=api.room)
        self.assertEqual(task["mention_sender"],api.details["senderId"])
        self.assertEqual(task["body"],"今天已经签过啦，本群积分 3 分。")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ledger").fetchone()[0],1)
