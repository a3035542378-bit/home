import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ergou import asset_actions, db, engine


class AssetAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "assets.sqlite"
        db.initialize(self.path)
        db.demo(self.path, ("one", "two"))
        self.conn = self.enterContext(db.closing_db(self.path))
        self.conn.execute("INSERT INTO reward_offers VALUES('one','茶',10)")
        self.conn.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                             VALUES('one','甲',0,'调分',50,'seed','seed',1,'积分')""")

    def send(self, source, text, member="甲", group="one", conn=None, **payload):
        return engine.receive(conn or self.conn, "sim-account", group, member, source, {"text":text, **payload})

    def drain(self):
        while engine.step(self.conn):
            continue

    def reply(self, seq):
        return self.conn.execute("SELECT body FROM inbox JOIN outbox ON event_id=biz WHERE seq=?", (seq,)).fetchone()[0]

    def test_two_producers_one_redemption_and_replay(self):
        gate = threading.Barrier(2)
        def submit(source):
            with db.closing_db(self.path) as conn:
                gate.wait(timeout=3)
                return self.send(source, "二狗兑换 茶", conn=conn)
        with ThreadPoolExecutor(max_workers=2) as pool:
            seqs = list(pool.map(submit, ("first","second")))
        self.assertEqual(self.send("first", "二狗兑换 茶"), seqs[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM outbox WHERE body=?", (asset_actions.BUSY_REPLY,)).fetchone()[0],1)
        self.drain()
        replies = [self.reply(seq) for seq in seqs]
        self.assertEqual(replies.count(asset_actions.BUSY_REPLY), 1)
        self.assertEqual(self.conn.execute("SELECT SUM(points) FROM ledger").fetchone()[0], 40)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM redemptions").fetchone()[0], 1)
        next_seq = self.send("third", "二狗兑换 茶")
        self.drain()
        self.assertIn("兑换单", self.reply(next_seq))

    def test_writer_in_progress_rejects_after_commit(self):
        # 暂停实际结算事务；另一个连接先从 WAL 看到占用，再等待写入回执。
        first = self.send("first", "二狗兑换 茶")
        started = threading.Event()
        observed = threading.Event()
        release = threading.Event()
        from ergou import group_tools
        redeem, pending = group_tools.redeem, asset_actions.pending
        def held(*args):
            started.set()
            self.assertTrue(release.wait(3))
            return redeem(*args)
        def check(*args):
            value = pending(*args)
            if value:
                observed.set()
            return value
        def settle():
            with db.closing_db(self.path) as conn:
                return engine.step(conn)
        def overlap():
            with db.closing_db(self.path) as conn:
                return self.send("second","二狗甩竿高级饵",conn=conn)
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(group_tools,"redeem",held), patch.object(asset_actions,"pending",check):
            worker = pool.submit(settle)
            try:
                self.assertTrue(started.wait(3))
                later = pool.submit(overlap)
                self.assertTrue(observed.wait(3))
            finally:
                release.set()
            self.assertTrue(worker.result(3))
            second = later.result(3)
        self.drain()
        self.assertIn("兑换单", self.reply(first))
        self.assertEqual(self.reply(second), asset_actions.BUSY_REPLY)
        self.assertFalse(self.conn.execute("SELECT 1 FROM fishing_experience").fetchone())

    def test_two_party_conflict_isolation_read_only_and_restart(self):
        self.send("raid", "二狗偷鱼 @甲",member="乙",pond_target="甲")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM asset_action_holds").fetchone()[0],2)
        db.initialize(self.path)
        blocked = [self.send("exhibit","二狗收入图鉴#17"), self.send("cast","二狗抛竿",member="乙"),
                   self.send("other-raid","二狗偷鱼 @甲",member="丙",pond_target="甲")]
        other_group = self.send("offgroup","二狗抛竿",group="two")
        other_member = self.send("offmember","二狗抛竿",member="丁")
        view = self.send("view","二狗积分")
        self.drain()
        self.assertTrue(all(self.reply(seq)==asset_actions.BUSY_REPLY for seq in blocked))
        for seq in (other_group, other_member, view):
            self.assertNotEqual(self.reply(seq), asset_actions.BUSY_REPLY)
        self.assertFalse(self.conn.execute("SELECT 1 FROM asset_action_holds").fetchone())

    def test_cancel_rollback_and_smart_mention(self):
        with self.assertRaises(ValueError), db.transaction(self.conn):
            self.send("rollback","二狗抛竿")
            raise ValueError("rollback")
        seq = self.send("cancel","二狗抛竿")
        self.conn.execute("UPDATE inbox SET state='IGNORED' WHERE seq=?", (seq,))
        self.assertFalse(self.conn.execute("SELECT 1 FROM asset_action_holds").fetchone())
        self.conn.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)", (b'fixture',))
        self.send("smart","@二狗 抛竿",mention_account="sim-account")
        self.assertFalse(self.conn.execute("SELECT 1 FROM asset_action_holds").fetchone())
        first = self.send("retry","二狗兑换 茶")
        with patch("ergou.group_tools.redeem", side_effect=RuntimeError("temporary")):
            engine.step(self.conn)
            engine.step(self.conn)
        blocked = self.send("overlap","二狗卖鱼#17")
        self.drain()
        self.assertIn("兑换单",self.reply(first))
        self.assertEqual(self.reply(blocked),asset_actions.BUSY_REPLY)

    def test_cross_process_and_duplicate_source(self):
        first = self.send("first","二狗抛竿")
        script = """from ergou import db, engine
import sys
with db.closing_db(sys.argv[1]) as conn:
    for source in ("first","second"):
        print(engine.receive(conn,"sim-account","one","甲",source,{"text":"二狗抛竿"}))
"""
        result = subprocess.run([sys.executable,"-c",script,str(self.path)], check=True, text=True,
                                capture_output=True, cwd=Path(__file__).resolve().parents[1],timeout=10)
        repeat, later = map(int,result.stdout.split())
        self.assertEqual(first,repeat)
        self.assertEqual(self.reply(later),asset_actions.BUSY_REPLY)
        self.drain()
        self.assertEqual(self.conn.execute("SELECT casts FROM fishing_experience").fetchone()[0],1)

    def test_upgrade_pending_and_retry_restore_holds(self):
        from ergou import operations
        first = self.send("first","二狗兑换 茶")
        self.conn.executescript("DROP TRIGGER asset_action_finished; DROP TABLE asset_action_holds;")
        db.initialize(self.path)
        self.assertEqual(self.conn.execute("SELECT seq FROM asset_action_holds").fetchone()[0],first)
        with patch("ergou.group_tools.redeem", side_effect=RuntimeError("temporary")):
            self.drain()
        self.assertFalse(self.conn.execute("SELECT 1 FROM asset_action_holds").fetchone())
        operations.act(self.conn,dict(name="ops",role="系统管理员",scopes="[]"),"one",
                       dict(action="重试入站",key="retry",reason="测试",target=first))
        second = self.send("second","二狗兑换 茶")
        self.assertEqual(self.reply(second),asset_actions.BUSY_REPLY)
        self.drain()
        self.assertIn("兑换单",self.reply(first))

    def test_native_busy_reply_uses_current_binding_and_fresh_event(self):
        import time
        from datetime import datetime, timezone
        from ergou import agent_wechat, jobs
        from tests.test_agent_wechat import Fixture
        api = Fixture()
        secret = "x"*40
        agent_wechat.link(self.conn,api,"测试群",secret)
        listener = agent_wechat.Listener(self.conn,api,secret)
        listener.verify()
        self.conn.execute("INSERT INTO directed_groups VALUES(?,?,1,?)",(api.room,api.account,time.time()-10))
        def cast(number):
            api.details.update(body="二狗抛竿",serverId=str(number),createdAt=datetime.now(timezone.utc).isoformat())
            return listener.consume(dict(cursor=str(number),kind="message.committed",
                data=dict(threadId=api.room,messageId=api.details["id"],origin="live",direction="incoming")))
        first = cast(13)
        second = cast(14)
        self.assertEqual(self.reply(second),asset_actions.BUSY_REPLY)
        task = jobs.claim(self.conn,api.account,directed_group=api.room)
        self.assertEqual(task["body"],asset_actions.BUSY_REPLY)
        self.assertEqual(self.conn.execute("SELECT state FROM inbox WHERE seq=?",(first,)).fetchone()[0],"PENDING")
        self.drain()
        self.assertEqual(self.conn.execute("SELECT casts FROM fishing_experience WHERE grp=?",(api.room,)).fetchone()[0],1)
