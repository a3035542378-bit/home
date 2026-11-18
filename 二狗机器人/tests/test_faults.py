import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from ergou import admin,jobs
from ergou.db import connect,demo,initialize
from ergou.engine import receive,step


class Faults(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/"db"
        initialize(self.path);demo(self.path);self.db=connect(self.path)
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def ingest(self,key):
        return receive(self.db,"sim-account","demo-group","p",key,{"text":"二狗 帮助"})

    def test_locked_or_full_not_accepted(self):
        other=connect(self.path)
        try:
            other.execute("BEGIN IMMEDIATE");self.db.execute("PRAGMA busy_timeout=30")
            with self.assertRaises(sqlite3.OperationalError):self.ingest("locked")
            other.rollback()
            self.assertEqual(0,self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0])
            pages=self.db.execute("PRAGMA page_count").fetchone()[0]
            self.db.execute(f"PRAGMA max_page_count={pages}")
            for i in range(100):
                try:
                    receive(self.db,"sim-account","demo-group","p",f"full{i}",{"text":"x"*7900})
                except sqlite3.OperationalError as exc:
                    self.assertEqual(sqlite3.SQLITE_FULL,exc.sqlite_errorcode)
                    self.assertFalse(self.db.execute("SELECT 1 FROM inbox WHERE source=?",(f"full{i}",)).fetchone())
                    break
            else:self.fail("SQLITE_FULL was not triggered")
        finally:other.close()

    def test_kill_inflight_transaction(self):
        code="""import os,sys
from ergou.db import connect
from ergou.engine import receive
db=connect(sys.argv[1])
seq=receive(db,'sim-account','demo-group','p','crash',{'text':'二狗 帮助'})
db.execute('BEGIN IMMEDIATE')
db.execute("UPDATE inbox SET state='DONE' WHERE seq=?",(seq,))
os._exit(73)
"""
        result=subprocess.run([sys.executable,"-c",code,str(self.path)])
        self.assertEqual(73,result.returncode)
        self.assertEqual("PENDING",self.db.execute("SELECT state FROM inbox").fetchone()[0])
        self.assertTrue(step(self.db));self.assertFalse(step(self.db))

    def test_expired_lease_and_bounded_retry(self):
        self.ingest("lost");step(self.db)
        now=time.time()
        task=jobs.claim(self.db,"sim-account",now)
        jobs.claim(self.db,"sim-account",now+31)
        self.assertEqual("UNKNOWN",self.db.execute("SELECT state FROM outbox WHERE id=?",(task["id"],)).fetchone()[0])
        self.ingest("retry");step(self.db)
        class Retry(jobs.Simulation):
            def send(self,task):return "RETRY_WAIT","明确未发送"
        for t in (0,5,15,30):jobs.send_one(self.db,Retry(),now+t+.1)
        self.assertEqual(("FAILED",4),tuple(self.db.execute("SELECT state,attempts FROM outbox ORDER BY id DESC LIMIT 1").fetchone()))

    def test_merge_and_alias(self):
        u={"role":"系统管理员","name":"admin"}
        admin.configure(self.db,u,"demo-group",1,{"welcome_window":5,"aliases":{"菜单":"帮助"}})
        now=time.time()
        for i in range(3):
            receive(self.db,"sim-account","demo-group",f"member{i}",f"j{i}",{},kind="join",now=now+i);step(self.db)
        jobs.tick(self.db,now+8)
        self.assertEqual(1,self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
        receive(self.db,"sim-account","demo-group","p","help",{"text":"二狗 菜单"});step(self.db)
        self.assertIn("命令前缀",self.db.execute("SELECT body FROM outbox ORDER BY id DESC LIMIT 1").fetchone()[0])

