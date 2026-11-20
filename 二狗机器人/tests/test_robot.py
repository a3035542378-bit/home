import concurrent.futures
import csv
import json
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from ergou import admin,community,jobs,queries
from ergou.db import BJ,DEFAULT,backup,connect,demo,dump,initialize,restore,transaction,window
from ergou.engine import receive,step
from ergou.games import GAMES,example


class Robot(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"test.sqlite"
        initialize(self.path);demo(self.path,("a","b"))
        self.db=connect(self.path)
        self.clock=time.time()
        self.admin={"name":"owner","role":"系统管理员","scopes":"[]"}

    def tearDown(self):
        self.db.close();self.tmp.cleanup()

    def say(self,text,member="operator",key=None,group="a",**kw):
        self.clock+=.02
        seq=receive(self.db,"sim-account",group,member,key or uuid.uuid4().hex,{"text":text},now=self.clock,**kw)
        while step(self.db):pass
        return self.db.execute("SELECT state,body FROM inbox LEFT JOIN (SELECT biz,body FROM outbox) ON event_id=biz WHERE seq=?",(seq,)).fetchone()

    def scalar(self,sql,args=()):
        return self.db.execute(sql,args).fetchone()[0]

    def test_catalog(self):
        self.assertGreaterEqual(len(GAMES),120)
        self.assertEqual(len(GAMES),len({g.id for g in GAMES.values()}))
        report=[]
        for i,game in enumerate(GAMES.values(),1):
            with self.subTest(game=game.id):
                self.clock+=11
                code=f"G{i:02}"
                self.assertIn(code,self.say("二狗 开始 "+game.name)["body"])
                self.assertIn("已加入",self.say("二狗 加入 "+code,"player")["body"])
                self.assertEqual("REJECTED",self.say(f"二狗 {code} 错误动作","player")["state"])
                row=self.db.execute("SELECT * FROM games WHERE code=?",(code,)).fetchone()
                moves=example(game,json.loads(row["board"]))
                self.assertTrue(moves)
                for j,move in enumerate(moves):
                    self.assertEqual("DONE",self.say(f"二狗 {code} {move}","player",f"{i}-{j}")["state"])
                self.assertEqual("FINISHED",self.scalar("SELECT state FROM games WHERE code=?",(code,)))
                self.assertEqual(1,self.scalar("SELECT COUNT(*) FROM ledger WHERE game=?",(row["id"],)))
                self.say(f"二狗 {code} {moves[-1]}","player",f"{i}-{len(moves)-1}")
                report.append((game.id,game.name,game.category,len(moves),"FINISHED","10","PASS"))
        if os.environ.get("ERGOU_RECORD_GAMES"):
            with open("GAME_RESULTS.csv","w",encoding="utf-8-sig",newline="") as f:
                out=csv.writer(f);out.writerow(("game_id","名称","类别","合法动作数","终态","积分","模拟验收"));out.writerows(report)

    def test_dedup_restart_atomic(self):
        self.say("二狗 开始 猜数字")
        secret=json.loads(self.scalar("SELECT board FROM games"))["target"]
        seq=receive(self.db,"sim-account","a","operator","answer",{"text":f"二狗 G01 {secret}"})
        self.db.close();self.db=connect(self.path)
        self.db.execute("CREATE TRIGGER inject BEFORE INSERT ON ledger BEGIN SELECT RAISE(ABORT,'fault'); END;")
        with self.assertRaises(sqlite3.IntegrityError):step(self.db)
        self.assertEqual("RUNNING",self.scalar("SELECT state FROM games"))
        self.db.execute("DROP TRIGGER inject")
        for _ in range(100):
            self.assertEqual(seq,receive(self.db,"sim-account","a","operator","answer",{"text":"二狗 G01 0"}))
        step(self.db)
        self.assertEqual(1,self.scalar("SELECT COUNT(*) FROM ledger"))
        self.assertEqual(2,self.scalar("SELECT COUNT(*) FROM outbox"))

    def test_scoped_config_concurrent(self):
        names=list(GAMES)[:4]
        def run(name):
            db=connect(self.path)
            try:receive(db,"sim-account","a","m",name,{"text":"二狗 开始 "+name});step(db)
            finally:db.close()
        with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(run,names))
        self.assertEqual(3,self.scalar("SELECT COUNT(*) FROM games"))
        self.assertIn("指定会话",self.say("二狗 123")["body"])
        group_admin={"name":"x","scopes":'["a"]',"role":"群管理员"}
        with self.assertRaises(PermissionError):admin.view(self.db,group_admin,"b","会话")
        with self.assertRaises(ValueError):admin.configure(self.db,group_admin,"a",1,{"welcome":"{成员.__class__}"})
        admin.configure(self.db,group_admin,"a",1,{"reward":2})
        with self.assertRaises(ValueError):admin.configure(self.db,group_admin,"a",1,{"reward":5})
        self.assertTrue(all(json.loads(r[0])["reward"]==10 for r in self.db.execute("SELECT rules FROM games")))

    def test_deadline_and_period(self):
        from datetime import datetime
        self.say("二狗 开始 猜数字")
        self.clock=self.scalar("SELECT deadline FROM games")
        self.assertEqual("REJECTED",self.say("二狗 G01 1")["state"])
        self.assertEqual("EXPIRED",self.scalar("SELECT state FROM games"))
        now=datetime(2026,11,1,0,0,tzinfo=BJ)
        self.assertEqual(now.timestamp(),window("月榜",now.timestamp()))
        self.assertEqual(26,datetime.fromtimestamp(window("周榜",now.timestamp()),BJ).day)

    def test_unknown_and_switch(self):
        self.say("二狗 帮助")
        class Drop(jobs.Simulation):
            def send(self,task):raise TimeoutError()
        jobs.send_one(self.db,Drop(),self.clock)
        self.assertEqual("UNKNOWN",self.scalar("SELECT state FROM outbox"))
        self.assertFalse(jobs.send_one(self.db,Drop(),self.clock+60))
        self.db.execute("INSERT INTO account VALUES('next','simulation','ONLINE')")
        self.db.execute("INSERT INTO membership VALUES('next','a')")
        self.assertIn("暂停",jobs.switch(self.db,"a","next","tester"))
        self.assertEqual("sim-account",self.scalar("SELECT account FROM groups WHERE id='a'"))

    def test_welcome_vote_draw(self):
        def event(key,kind,who,data):
            receive(self.db,"sim-account","a",who,key,data,kind=kind,now=self.clock);step(self.db)
        event("base","baseline","system",{"members":["old"]})
        event("j1","join","old",{});event("j2","join","new",{});event("j3","join","new",{})
        self.assertEqual(1,self.scalar("SELECT COUNT(*) FROM outbox"))
        self.say("二狗 投票 创建 多选 午餐|面|饭|饺子")
        self.say("二狗 投票 V01 1,2","m")
        self.assertIn("1 人参与",self.say("二狗 投票 V01 3","m")["body"])
        self.clock+=610
        self.assertEqual("REJECTED",self.say("二狗 投票 V01 1","m")["state"])
        self.say("二狗 抽签 报名","m")
        for _ in range(2):self.say("二狗 抽签 开始","operator","draw")
        self.say("二狗 抽签 重抽 1 重新报名后抽取")
        self.assertEqual(2,self.scalar("SELECT COUNT(*) FROM draws"))

    def test_schedule_backup(self):
        self.db.execute("INSERT INTO schedules(grp,body,period,due,catchup) VALUES('a','提醒','每日',?,1)",(self.clock-2*86400-5,))
        jobs.tick(self.db,self.clock);jobs.tick(self.db,self.clock)
        self.assertEqual(1,self.scalar("SELECT COUNT(*) FROM outbox"))
        dest=self.path.parent/"copy.db";target=self.path.parent/"restore.db"
        backup(self.path,dest);restore(dest,target)
        db=connect(target)
        try:
            self.assertEqual("UNKNOWN",db.execute("SELECT state FROM outbox").fetchone()[0])
            self.assertEqual("ok",db.execute("PRAGMA integrity_check").fetchone()[0])
        finally:db.close()

    def test_query_budget_and_redaction(self):
        self.say("二狗 天气 上海")
        def fixture(url,params,deadline,headers=None):
            if url==queries.GEO:return {"results":[{"name":"上海","latitude":31,"longitude":121}]}
            return {"current":{"temperature_2m":16,"time":"2026-11-18T12:00"}}
        queries.work(self.db,fixture)
        self.assertIn("16 °C",self.scalar("SELECT body FROM outbox"))
        self.assertIn("缓存",self.say("二狗 天气 上海")["body"])
        with patch.dict(os.environ,{"ERGOU_DHL_KEY":"test"}):
            parcel=queries.lookup("快递","123456",lambda *a:{"shipments":[{"status":{"statusCode":"delivered","address":"private"}}]})
        self.assertEqual("📦 DHL · 已送达",parcel)
        self.say("二狗 天气 北京")
        queries.work(self.db,lambda *a:(_ for _ in ()).throw(queries.ProviderError("供应商配额已用尽")))
        self.assertEqual("FAILED",self.scalar("SELECT state FROM queries ORDER BY id DESC LIMIT 1"))

