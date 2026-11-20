import sqlite3
import tempfile
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ergou import db, engine, fish_grades as grades
from ergou.fishing_waters import SPECIES, size_grade


class Ticket:
    def __init__(self, value):
        self.value = value

    def randrange(self, limit):
        assert limit == 10000
        return self.value


class GradeTests(unittest.TestCase):
    def test_requested_draws_and_caps(self):
        cases = [
            ("鲤鱼", 600, False, 9999, "传说"),
            ("金色锦鲤", 650, False, 9988, "传说"),
            ("鲤鱼", 17000, True, 9990, "神话"),
            ("鲤鱼", 2200, False, 0, "普通"),
            ("金色锦鲤", 3500, False, 9999, "传说"),
        ]
        for fish, grams, event, ticket, expected in cases:
            with self.subTest(fish=fish, ticket=ticket):
                grade = grades.final_grade(fish, grams, "", event, Ticket(ticket))
                self.assertEqual(grades.GRADES[grade.final], expected)
        for grams, expected in [(1549, "小型"), (1550, "标准"), (3125, "大型"), (12000, "巨物")]:
            self.assertEqual(size_grade("鲤鱼", grams), expected)
        self.assertEqual(size_grade("泥鳅", 213), "大型")
        self.assertEqual(size_grade("泥鳅", 214), "巨物")

    def test_exhaustive_odds_and_prices(self):
        for tier, counts in grades.TICKETS.items():
            actual = Counter(grades.roll_upgrade(tier, Ticket(n)) for n in range(10000))
            self.assertEqual(tuple(actual[k] for k in range(5)), counts)
        for fish, grams, event, expected in [
            ("鲤鱼", 600, False, {4: 2}), ("金色锦鲤", 650, False, {4: 12}),
            ("鲤鱼", 17000, True, {3: 9700, 4: 290, 5: 10}),
        ]:
            actual = Counter(grades.final_grade(fish, grams, "", event, Ticket(n)).final for n in range(10000))
            for level, count in expected.items():
                self.assertEqual(actual[level], count)
        self.assertEqual(grades.price("鲤鱼", 500, 0), 4)
        self.assertEqual(grades.price("鲤鱼", 4000, 4), 56)
        self.assertEqual(grades.price("鲤鱼", 25000, 5), 135)

    def test_actual_catch_reward_replay_and_exhibit_swap(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))/"game.sqlite"
        db.initialize(path)
        db.demo(path, ("one", "two"))
        conn = self.enterContext(db.closing_db(path))

        def say(source, text, now, group="one"):
            seq = engine.receive(conn,"sim-account",group,"player",source,{"text":"二狗"+text},now=now)
            engine.step(conn)
            return conn.execute("SELECT body FROM inbox JOIN outbox ON biz=event_id WHERE seq=?", (seq,)).fetchone()[0]

        with patch("ergou.fishing.random.Random") as factory, patch("ergou.fish_grades.Random", return_value=Ticket(9999)):
            rng = factory.return_value
            rng.choice.side_effect = lambda pool: SPECIES["鲤鱼"] if isinstance(pool[0], tuple) else pool[0]
            rng.choices.return_value = ["普通"]
            rng.triangular.side_effect = [600, 610]
            first = say("catch", "抛竿", 1)
            self.assertIn("＋500 积分", first)
            self.assertIn("欧皇", first)
            self.assertEqual(first, say("catch", "抛竿", 2))
            self.assertIn("已点亮", say("exhibit", "收入图鉴#1", 3))
            self.assertNotIn("＋500", say("second", "抛竿", 21))
        self.assertIn("已换入", say("swap", "收入图鉴#2", 22))
        self.assertIn("传说 ✨升品", say("bag", "查看鱼包", 23))
        self.assertIn("传说 ✨升品", say("page", "图鉴 新手池塘", 24))
        self.assertIn("升品传说鱼　2 条", say("home", "全图鉴", 25))
        self.assertIn("升品传说鱼　0 条", say("other-group", "图鉴", 25, "two"))
        self.assertIn("卖出", say("sell", "卖鱼#1", 26))
        self.assertEqual(tuple(conn.execute("SELECT best_grams,best_grade,best_grade_upgraded FROM fishing_species").fetchone()), (610,4,1))
        self.assertEqual(tuple(conn.execute("SELECT sum(points),count(*) FROM ledger").fetchone()), (500,1))

    def test_legacy_migration_keeps_value_without_reroll(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))/"old.sqlite"
        with closing(sqlite3.connect(path)) as old, old:
            old.executescript("""
                CREATE TABLE fishing_pond(id INTEGER PRIMARY KEY,grp TEXT,member TEXT,fish TEXT,grams INTEGER,price INTEGER);
                CREATE TABLE fishing_exhibits(grp TEXT,member TEXT,fish TEXT,item_id INTEGER,grams INTEGER,price INTEGER);
                CREATE TABLE fishing_species(grp TEXT,member TEXT,fish TEXT,best_grams INTEGER,PRIMARY KEY(grp,member,fish));
                INSERT INTO fishing_pond VALUES(1,'one','p','鲤鱼',600,12);
                INSERT INTO fishing_exhibits VALUES('one','p','金色锦鲤',2,3500,70);
                INSERT INTO fishing_species VALUES('one','p','金色锦鲤',3500);""")
        db.initialize(path)
        db.initialize(path)
        with db.closing_db(path) as conn:
            self.assertEqual(tuple(conn.execute("SELECT grade,grade_upgraded,price FROM fishing_exhibits").fetchone()),(4,0,70))
            self.assertEqual(tuple(conn.execute("SELECT grade,grade_upgraded,price FROM fishing_pond").fetchone()),(0,0,12))
            self.assertEqual(tuple(conn.execute("SELECT best_grade,best_grade_upgraded FROM fishing_species").fetchone()),(4,0))
            self.assertEqual(conn.execute("SELECT count(*) FROM ledger").fetchone()[0],0)
