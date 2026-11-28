import json
import unittest
from . import test_robot
from ergou import jobs
from ergou.quiz_rounds import active


class Quiz(unittest.TestCase):
    setUp=test_robot.Robot.setUp
    tearDown=test_robot.Robot.tearDown
    say=test_robot.Robot.say

    def test_two_players_same_answer_and_owner_exit(self):
        import concurrent.futures
        from ergou import engine, db
        self.say("二狗开始 猜成语")
        self.say("二狗开始 猜歌词",group="b")
        row=active(self.db,"a")
        answer=json.loads(row["board"])["answer"]
        def compete(member):
            with db.closing_db(self.path) as conn:
                engine.receive(conn,"sim-account","a",member,member,{"text":"二狗"+answer},now=self.clock+.1)
                engine.step(conn)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(compete,("guest1","guest2")))
        self.assertEqual(2,json.loads(active(self.db,"a")["board"])["number"])
        self.assertEqual(1,self.db.execute("SELECT count(*) FROM ledger WHERE game=?",(row["id"],)).fetchone()[0])
        self.assertIn("已结束",self.say("二狗退出 "+row["code"])["body"])
        self.assertIsNone(active(self.db,"a"))
        self.assertEqual(1,json.loads(active(self.db,"b")["board"])["number"])
        engine.receive(self.db,"sim-account","b","operator","depart",{},kind="leave",now=self.clock+.5)
        engine.step(self.db)
        self.assertIsNone(active(self.db,"b"))

    def test_direct_answer_and_owner_stop(self):
        self.say("二狗开始 猜图片")
        game=active(self.db,"a")
        answer=json.loads(game["board"])["answer"]
        self.assertIsNone(self.say(answer,"guest")["body"])
        self.assertIn("第 2 题",self.say("二狗"+answer,"guest",key="guess")["body"])
        self.say("二狗"+answer,"guest",key="guess")
        self.assertEqual(2,json.loads(active(self.db,"a")["board"])["number"])
        self.assertEqual("REJECTED",self.say("二狗停止游戏","guest")["state"])
        self.assertIn("答对 1 题",self.say("二狗停止游戏")["body"])
        self.assertIsNone(active(self.db,"a"))

    def test_reminder_and_closure(self):
        self.say("二狗开始 猜成语")
        game=active(self.db,"a")
        origin=json.loads(game["rules"])["quiz_origin"]
        self.db.execute("INSERT INTO directed_events VALUES(?,?)",(origin,self.clock))
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,0 FROM groups WHERE id='a'")
        due=game["deadline"]
        jobs.tick(self.db,due-.01)
        self.assertEqual(0,self.db.execute("SELECT count(*) FROM quiz_notices").fetchone()[0])
        jobs.tick(self.db,due)
        jobs.tick(self.db,due)
        self.assertEqual(["operator"],[r[0] for r in self.db.execute("SELECT recipient FROM valid_quiz_notices")])
        self.clock=due+1
        self.assertIn("第 2 题",self.say("二狗继续")["body"])
        self.assertFalse(self.db.execute("SELECT 1 FROM valid_quiz_notices").fetchone())
        due=active(self.db,"a")["deadline"]
        jobs.tick(self.db,due)
        jobs.tick(self.db,due+179)
        self.assertIsNotNone(active(self.db,"a"))
        jobs.tick(self.db,due+180)
        self.assertIsNone(active(self.db,"a"))
        self.assertEqual(1,self.db.execute("SELECT count(*) FROM quiz_notices WHERE NOT reveal").fetchone()[0])

    def test_lyrics_reopens_with_fresh_clues_and_accepts_missing_words(self):
        from ergou.games import QUIZZES
        seen=set()
        for _ in QUIZZES["lyrics_quiz"][2]:
            self.clock+=15
            body=self.say("二狗开始 猜歌词")["body"]
            self.assertIn("只填方框缺的字",body)
            board=json.loads(active(self.db,"a")["board"])
            self.assertEqual(len(board["answer"]), board["clue"].count("□"))
            self.assertNotIn(board["answer"],seen)
            seen.add(board["answer"])
            self.say("二狗停止游戏")
        self.clock+=15
        self.say("二狗开始 猜歌词",group="b")
        self.assertIn("还没填对",self.say("二狗错误填词","guest",group="b")["body"])
        self.assertNotIn("还没填对",self.say("二狗积分","guest",group="b")["body"])
        answer=json.loads(active(self.db,"b")["board"])["answer"]
        self.assertIn("第 2 题",self.say("二狗"+answer+"！","guest",group="b")["body"])
        self.assertEqual(2,self.db.execute("SELECT count(*) FROM quiz_history WHERE grp='b'").fetchone()[0])
