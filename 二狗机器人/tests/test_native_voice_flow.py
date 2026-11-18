import os
import tempfile
import time
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import Mock,patch

from ergou import agent_wechat,engine,jobs,native_voice,voice_policy
from ergou.db import closing_db,initialize
from tests.test_agent_wechat import Fixture
from tests.voice_credentials import verify_credential


class Idle(Exception):
    """End the worker at its first idle wait."""


class VoiceFlow(unittest.TestCase):
    def setUp(self):
        self.private=Path(self.enterContext(tempfile.TemporaryDirectory()))
        path=self.private/"flow.sqlite"
        initialize(path)
        self.db=self.enterContext(closing_db(path))
        self.enterContext(patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_KEY":"asr-tts-fixture","ERGOU_BAIDU_SPEECH_TOKEN":""}))
        (self.private/"ergou-media-token").write_text("fixture-media-scope",encoding="utf-8")
        self.api=Fixture()
        self.secret="worker-test-key"*4
        self.owner=dict(name="owner",role="系统管理员",scopes="[]")
        agent_wechat.link(self.db,self.api,"测试群",self.secret)
        self.listener=agent_wechat.Listener(self.db,self.api,self.secret,self.private)
        self.listener.verify()
        self.fetch=Mock(side_effect=self.media)
        self.recognize=Mock(return_value="二狗，二狗，积分。")
        self.send=self.enterContext(patch("ergou.native_voice_send.send_voice",side_effect=self.deliver))
        self.text=self.enterContext(patch("ergou.agent_wechat.send_direct",side_effect=AssertionError("语音意外进入文字发送器")))
        verify_credential(self.db,self.owner,self.api.room)

    def switch(self,on,confirm=False):
        settings=voice_policy.settings(self.db,self.owner,self.api.room)
        voice_policy.configure(self.db,self.owner,self.api.room,dict(action="switch",version=settings["version"],enabled=on))
        if confirm:
            # Real WeChat timestamps have coarser precision than the approval clock.
            with patch.object(voice_policy.time,"time",return_value=time.time()-1):
                voice_policy.approve(self.db,voice_policy.preview(self.db,self.api.room))

    def media(self,client,message_id,check):
        self.assertEqual((client.slot,client.token,message_id),(self.api.slot,"fixture-media-scope","upstream-row"))
        check()
        return b"fixture-pcm"

    def deliver(self,client,token,task,authorized,auth):
        self.assertIs(client,self.api)
        self.assertEqual(token,"fixture-send-scope")
        self.assertEqual(auth,("asr-tts-fixture",""))
        self.assertEqual((task["grp"],task["body"]),(self.api.room,"本群积分 0"))
        self.assertTrue(authorized())
        return "ACKNOWLEDGED","测试语音回执"

    def listen(self,n,source="987",*,group=None,age=0,recalled=False):
        stamp=datetime.fromtimestamp(time.time()-age,timezone.utc).isoformat()
        self.api.details.update(serverId=source,type=34,body=None,createdAt=stamp,recall=recalled)
        self.listener.consume(dict(cursor=str(n),kind="message.committed",data=dict(threadId=group or self.api.room,
                                   messageId="upstream-row",origin="live",direction="incoming")))

    def asr(self):
        return native_voice.work(self.db,self.api,self.private,fetch=self.fetch,recognize=self.recognize)

    def run_replies(self):
        with patch.object(agent_wechat.time,"sleep",side_effect=Idle),self.assertRaises(Idle):
            agent_wechat.replies(self.db,self.api,self.secret,"fixture-send-scope")

    def test_voice_loop_through_real_dispatch_and_replay(self):
        self.switch(True,confirm=True)
        self.listen(13)
        self.listen(14)  # Same server ID, different SSE cursor.
        self.assertTrue(self.asr())
        self.assertFalse(self.asr())
        self.recognize.assert_called_once_with(b"fixture-pcm",("asr-tts-fixture",""))
        self.assertTrue(engine.step(self.db))
        self.run_replies()
        task=self.send.call_args.args[2]
        row=self.db.execute("SELECT seq,state FROM native_voice_events").fetchone()
        self.assertEqual((task["voice_seq"],row["state"]),(row["seq"],"AWAKE"))
        self.assertEqual(tuple(self.db.execute("SELECT state,attempts FROM outbox").fetchone()),("ACKNOWLEDGED",1))
        self.listen(15)
        self.assertFalse(self.asr())
        self.assertFalse(engine.step(self.db))
        self.assertFalse(jobs.claim(self.db,self.api.account,directed_group=self.api.room))
        self.assertEqual(self.send.call_count,1)
        self.text.assert_not_called()

    def test_disabled_unconfirmed_old_other_group_recalled_and_single_wake(self):
        self.listen(13,source="101")
        self.switch(True)
        self.listen(14,source="102")
        self.switch(True,confirm=True)
        self.listen(15,source="103",group="other@chatroom")
        self.listen(16,source="104",age=121)
        self.listen(17,source="105",recalled=True)
        self.assertFalse(self.asr())
        self.fetch.assert_not_called()
        self.recognize.assert_not_called()
        self.recognize.return_value="二狗积分"
        self.listen(18,source="106")
        self.assertTrue(self.asr())
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT source,state FROM native_voice_events")],
                         [("106","NOT_ADDRESSED")])
        self.assertFalse(engine.step(self.db))
        self.run_replies()
        self.send.assert_not_called()
        self.text.assert_not_called()

    def test_disabling_in_flight_during_asr_discards_transcript(self):
        self.switch(True,confirm=True)
        self.listen(13)
        def complete(*args):
            self.switch(False)
            return "二狗二狗积分"
        self.recognize.side_effect=complete
        self.assertTrue(self.asr())
        self.assertEqual(self.db.execute("SELECT state FROM native_voice_events").fetchone()[0],"CANCELLED")
        self.assertFalse(engine.step(self.db))
        self.assertFalse(jobs.claim(self.db,self.api.account,directed_group=self.api.room))
        self.assertFalse(self.db.execute("SELECT 1 FROM outbox").fetchone())

    def test_upgrade_preserves_consent_but_requires_a_verified_legacy_key(self):
        self.switch(True,confirm=True)
        self.db.execute("DROP TABLE voice_test_tickets")
        self.db.execute("DROP TABLE voice_verifications")
        with patch("ergou.models.protect",side_effect=lambda data,decrypt=False:data[::-1]):
            self.db.execute("INSERT INTO voice_credentials VALUES(?,?,?)",(self.api.room,"key",b"yek-dlo"))
            initialize(self.private/"flow.sqlite")
            policy=voice_policy.settings(self.db,self.owner,self.api.room)
            self.assertTrue(policy["approved"])
            self.assertFalse(policy["enabled"])
            self.listen(13,source="500")
            self.assertFalse(self.asr())
            self.fetch.assert_not_called()
            self.recognize.assert_not_called()
            with self.assertRaises(ValueError):
                voice_policy.verified_credentials(self.db,self.api.room)
            verify_credential(self.db,self.owner,self.api.room)
            self.listen(14,source="501")
            self.assertTrue(self.asr())
            self.recognize.assert_called_once_with(b"fixture-pcm",("old-key",""))
        sources=self.db.execute("SELECT source FROM native_voice_events").fetchall()
        self.assertEqual([r[0] for r in sources],["501"])

    def test_changed_environment_key_stops_audio_before_provider(self):
        self.switch(True,confirm=True)
        self.listen(13)
        def change_key(client,message_id,check):
            pcm=self.media(client,message_id,check)
            os.environ["ERGOU_BAIDU_SPEECH_KEY"]="replacement-never-tested"
            return pcm
        self.fetch.side_effect=change_key
        self.assertTrue(self.asr())
        self.recognize.assert_not_called()
        self.assertEqual(self.db.execute("SELECT state FROM native_voice_events").fetchone()[0],"CANCELLED")
        self.listen(14,source="988")
        self.assertFalse(self.asr())
        self.fetch.assert_called_once()
        self.assertFalse(self.db.execute("SELECT 1 FROM outbox").fetchone())

    def test_revocation_between_claim_and_submit(self):
        self.switch(True,confirm=True)
        self.listen(13)
        self.assertTrue(self.asr())
        self.assertTrue(engine.step(self.db))
        claim=jobs.claim
        def claim_and_disable(*args,**kwargs):
            task=claim(*args,**kwargs)
            self.assertIsInstance(task,dict)
            self.switch(False)
            return task
        with patch.object(jobs,"claim",side_effect=claim_and_disable):
            agent_wechat.replies(self.db,self.api,self.secret,"fixture-send-scope")
        self.assertEqual(self.db.execute("SELECT state FROM outbox").fetchone()[0],"FAILED")
        self.send.assert_not_called()
        self.text.assert_not_called()
