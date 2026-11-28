import sqlite3
import unittest

from ergou import fishing_bait
from ergou.social_gifts import PRICES
from . import test_robot


class GroupGifts(unittest.TestCase):
    setUp=test_robot.Robot.setUp
    tearDown=test_robot.Robot.tearDown
    say=test_robot.Robot.say

    def test_gift_replay_balance_and_group_collection(self):
        self.db.execute("INSERT INTO simulation_members VALUES('a','friend')")
        self.say("二狗签到")
        command="二狗送礼 小雏菊 @friend"
        self.assertIn("已送给",self.say(command,key="gift")["body"])
        self.say(command,key="gift")
        self.assertIn("还差",self.say(command)["body"])
        self.assertEqual(fishing_bait.balance(self.db,("a","operator")),3-PRICES["小雏菊"])
        self.assertIn("收到 1 件",self.say("二狗我的礼物",member="friend")["body"])
        self.assertIn("还没收到",self.say("二狗我的礼物",member="friend",group="b")["body"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM social_gifts").fetchone()[0],1)

    def test_invalid_targets_and_gift_do_not_debit(self):
        self.db.executemany("INSERT OR IGNORE INTO simulation_members VALUES(?,?)",
                            [("b","elsewhere"),("a","operator"),("a","friend")])
        for suffix in ("小雏菊 @elsewhere","小雏菊 @operator","小雏菊 @friend @other","不存在 @friend"):
            self.assertIn("请",self.say("二狗送礼 "+suffix)["body"])
        self.assertEqual(fishing_bait.balance(self.db,("a","operator")),0)
        self.assertIn("积分",self.say("二狗礼物商店")["body"])
        self.assertTrue(self.say("二狗赞美")["body"])

    def test_failure_rolls_back_both_writes(self):
        self.db.execute("INSERT INTO simulation_members VALUES('a','friend')")
        self.say("二狗签到")
        self.db.execute("""CREATE TEMP TRIGGER fail_gift BEFORE INSERT ON social_gifts
            BEGIN SELECT RAISE(ABORT,'gift interrupted'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.say("二狗送礼 小雏菊 @friend",key="retry")
        self.assertEqual(fishing_bait.balance(self.db,("a","operator")),3)
        self.db.execute("DROP TRIGGER fail_gift")
        self.say("二狗送礼 小雏菊 @friend",key="retry")
        self.assertEqual(self.db.execute("SELECT count(*) FROM social_gifts").fetchone()[0],1)
