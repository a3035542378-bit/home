from pathlib import Path
import tempfile
import time
import unittest

from ergou import agent_wechat, engine, native_voice
from ergou.db import closing_db, demo, initialize
from ergou.reply_diagnostics import recent
from tests.test_agent_wechat import Fixture


class ReplyDiagnostics(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "trace.sqlite"
        initialize(path)
        demo(path)
        self.db = self.enterContext(closing_db(path))
        self.api = Fixture()
        secret = "diagnostic-fixture" * 3
        agent_wechat.link(self.db, self.api, "测试群", secret)
        agent_wechat.Listener(self.db, self.api, secret).verify()
        self.group = self.api.room
        self.now = time.time()
        self.db.execute("INSERT INTO directed_groups VALUES(?,?,1,?)", (self.group,self.api.account,self.now-60))

    def message(self, source, body, at, *, mentioned=False):
        payload = dict(text=body, source_time=at)
        if mentioned:
            payload["mention_account"] = self.api.account
        seq = engine.receive(self.db, self.api.account, self.group, "PRIVATE-MEMBER", source, payload,
                             adapter_version=agent_wechat.VERSION, now=at)
        self.assertTrue(engine.step(self.db))
        return seq

    def voice(self, source, state, at, seq=None):
        self.db.execute("""INSERT INTO native_voice_events(grp,account,binding,generation,slot,server_id,
            message_id,source,member,source_time,state,seq) VALUES(?,?,1,1,?,'daemon-id',?,?,?,?,?,?)""",
            (self.group,self.api.account,self.api.slot,"PRIVATE-VOICE-ID",source,"PRIVATE-MEMBER",at,state,seq))

    def test_only_directed_text_and_current_binding_with_private_data_excluded(self):
        self.message("ordinary","PRIVATE-CONVERSATION",self.now-1)
        self.message("prefix","二狗菜单",self.now)
        seq = self.message("mention","积分",self.now+1,mentioned=True)
        event_id = self.db.execute("SELECT event_id FROM inbox WHERE seq=?", (seq,)).fetchone()[0]
        self.db.execute("""UPDATE outbox SET state='UNKNOWN', attempts=2,
                        body='PRIVATE-BODY',detail='PRIVATE-KEY' WHERE biz=?""", (event_id,))
        result = recent(self.db,self.group)
        self.assertEqual([(r["received"],r["kind"],r["status"]) for r in result], [
            (self.now+1,"点名文字","发送结果待核对"), (self.now,"点名文字","等待发送")])
        self.assertEqual(set(result[0]), {"received","kind","status","attempts","ack_at","detail"})
        self.assertEqual(result[0]["attempts"], 2)
        self.assertNotIn("PRIVATE", str(result))
        self.assertEqual(recent(self.db,self.group,1), result[:1])
        self.assertEqual(recent(self.db,"demo-group"), [])
        self.assertEqual(recent(self.db,"other-room"), [])
        self.db.execute("UPDATE outbox SET binding=2")
        self.assertTrue(all(r["status"]=="暂无发送记录" for r in recent(self.db,self.group)))
        self.db.execute("UPDATE groups SET binding=2 WHERE id=?", (self.group,))
        self.assertEqual(recent(self.db,self.group), [])

    def test_manual_unknown_and_accepted_have_distinct_evidence_levels(self):
        self.message("receipt","二狗积分",self.now)
        for state,detail,label in [
            ("ACKNOWLEDGED","微信已受理，已回读核对本群发件记录","微信发件已核对"),
            ("ACKNOWLEDGED","微信已受理，发件记录暂未核验","微信已受理"),
            ("ACKNOWLEDGED","管理员核对","人工确认送达"),
            ("CANCELLED","管理员核对","人工结束跟进"),
            ("ACKNOWLEDGED","PRIVATE: unrecognized historical record","任务已确认"),
            ("UNKNOWN","微信已受理，已回读核对本群发件记录","发送结果待核对")]:
            with self.subTest(state=state,detail=detail):
                self.db.execute("UPDATE outbox SET state=?,detail=?,ack_at=?", (state,detail,self.now+4))
                row, = recent(self.db,self.group)
                self.assertEqual(row["status"], label)
                self.assertEqual(row["ack_at"],self.now+4 if state=="ACKNOWLEDGED" and detail!="管理员核对" else None)
                self.assertNotIn("PRIVATE",str(row))

    def test_voice_capture_and_wake_share_one_row_with_matching_reply(self):
        for index,state in enumerate(("PENDING","PROCESSING","FAILED","NOT_ADDRESSED","EXPIRED","RATE_LIMITED","CANCELLED")):
            self.voice(str(index),state,self.now+index)
        at = self.now+8
        seq = engine.receive(self.db,self.api.account,self.group,"PRIVATE-MEMBER","wake",{"text":"PRIVATE-TRANSCRIPT"},
                             adapter_version=native_voice.VERSION,message_type="voice",now=at)
        self.voice("wake","AWAKE",at,seq)
        biz = self.db.execute("SELECT event_id FROM inbox WHERE seq=?", (seq,)).fetchone()[0]
        self.db.execute("INSERT INTO directed_events VALUES(?,?)",(biz,at))
        self.db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready,attempts,detail,ack_at)
                        VALUES(?,?,?,1,'PRIVATE-BODY','ACKNOWLEDGED',?,?,?,1,'已核对本群原生语音的微信回执和发件记录',?)""",
                        (biz,self.api.account,self.group,at,at+120,at,at+3))
        rows = recent(self.db,self.group)
        self.assertEqual([r["status"] for r in rows], ["微信发件已核对","语音处理已取消","语音识别受限","语音已过期",
                         "未唤醒","语音处理失败","识别中","等待识别"])
        self.assertEqual((rows[0]["kind"],rows[0]["attempts"],rows[0]["ack_at"]),("群语音",1,at+3))
        self.assertNotIn("PRIVATE",str(rows))
        self.db.execute("UPDATE groups SET binding=2 WHERE id=?", (self.group,))
        self.assertEqual(recent(self.db,self.group), [])

    def test_query_stays_visible_before_a_reply_is_enqueued(self):
        seq = self.message("query","二狗 天气 北京", self.now)
        row, = recent(self.db,self.group)
        self.assertEqual((row["status"],row["attempts"],row["ack_at"]),("生活查询等待处理",0,None))
        self.assertNotIn("北京",str(row))
        self.db.execute("UPDATE queries SET state='FAILED',result='PRIVATE-PROVIDER-BODY' WHERE id=?", (seq,))
        self.db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
                        SELECT event_id,account,grp,binding,'PRIVATE-FALLBACK','PENDING',arrived,arrived+120,arrived
                        FROM inbox WHERE seq=?""", (seq,))
        row, = recent(self.db,self.group)
        self.assertEqual(row["status"], "等待发送")
        self.assertIn("生活查询失败",row["detail"])
        self.assertNotIn("PRIVATE",str(row))
