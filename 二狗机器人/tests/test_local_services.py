import tempfile
import time
import unittest
from pathlib import Path

from ergou import admin, jobs
from ergou.db import closing_db, demo, initialize
from ergou.engine import receive, step
from ergou.intents import interpret


class LocalServices(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"robot.sqlite"
        initialize(path)
        demo(path,("a","b"))
        self.db=self.enterContext(closing_db(path))
        self.actor=dict(role="运营管理员",scopes='["a"]',name="ops")
        self.seq=0

    def event(self,text,member="member",kind="message",group="a"):
        self.seq+=1
        no=receive(self.db,"sim-account",group,member,str(self.seq),{"text":text,"name":member},kind=kind)
        step(self.db)
        return self.db.execute("SELECT i.state,o.body FROM inbox i LEFT JOIN outbox o ON o.biz=i.event_id WHERE i.seq=?",(no,)).fetchone()

    def test_tools_and_game_switches(self):
        self.assertEqual(interpret("帮我查一下北京今天的天气怎么样？",{}),"天气 北京")
        self.assertEqual(interpret("今天天气真好呀",{}),"今天天气真好呀")
        self.assertIn("双鱼座",self.event("二狗双鱼座今天运势怎么样")[1])
        self.assertIn("题面",self.event("二狗来一局猜歌名")[1])
        admin.configure(self.db,self.actor,"a",1,{"disabled_games":["猜成语"]})
        self.assertEqual(self.event("二狗玩猜成语")[0],"REJECTED")
        self.assertIn("题面",self.event("二狗玩猜成语",group="b")[1])

    def test_moderation_and_welcome(self):
        admin.configure(self.db,self.actor,"a",1,dict(words=["测试匹配词"],moderation="移出群聊",
                        welcome="欢迎 {nickname}",rules_url="https://example.com/rules"))
        self.event("测试匹配词")
        self.assertEqual(self.event("二狗积分")[0],"IGNORED")
        self.assertEqual(self.event("二狗积分",group="b")[0],"DONE")
        row=admin.view(self.db,self.actor,"a","规则命中")[0]
        self.assertEqual(row["执行结果"],"模拟执行完成")
        self.assertEqual(self.event("",kind="join")[1],"欢迎 member\n群规：https://example.com/rules")
        self.assertIn("积分",self.event("二狗积分")[1])
        admin.configure(self.db,self.actor,"a",2,dict(welcome_window=10))
        self.event("",kind="join",member="new")
        jobs.tick(self.db,time.time()+11)
        self.assertIn("欢迎 new",self.db.execute("SELECT body FROM outbox WHERE biz LIKE 'welcome/%'").fetchone()[0])
