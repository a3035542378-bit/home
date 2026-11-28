from datetime import datetime
import unittest

from ergou.db import BJ
from . import test_robot


class DailyProfile(unittest.TestCase):
    setUp=test_robot.Robot.setUp
    tearDown=test_robot.Robot.tearDown
    say=test_robot.Robot.say

    def test_work_day_replay_and_scope(self):
        self.clock=datetime(2026,11,28,23,59,50,tzinfo=BJ).timestamp()
        self.assertIn("到账 1 积分",self.say("二狗打工",key="first")["body"])
        self.say("二狗打工",key="first")
        self.assertIn("已经收工",self.say("二狗打工")["body"])
        self.assertIn("打工已完成",self.say("二狗个人档案")["body"])
        self.assertIn("二狗打工",self.say("二狗个人信息",group="b")["body"])
        self.assertIn("到账 1 积分",self.say("二狗打工",group="b")["body"])
        self.clock+=20
        self.assertIn("到账 1 积分",self.say("二狗打工")["body"])
        self.assertEqual([("a",2),("b",1)],[tuple(x) for x in self.db.execute(
            "SELECT grp,sum(points) FROM ledger WHERE kind='打工' GROUP BY grp ORDER BY grp")])

    def test_achievements_use_history_without_payout(self):
        self.say("二狗签到")
        self.say("二狗抛竿")
        count=self.db.execute("SELECT count(*) FROM ledger").fetchone()[0]
        for command in ("个人档案","成就手册","我的成就"):
            reply=self.say("二狗"+command)["body"]
            self.assertIn("渔场新手",reply)
            self.assertIn("初次签到",reply)
            self.assertNotIn("第一次收工",reply)
        self.assertNotIn("渔场新手",self.say("二狗个人档案",group="b")["body"])
        self.assertEqual(count,self.db.execute("SELECT count(*) FROM ledger").fetchone()[0])
