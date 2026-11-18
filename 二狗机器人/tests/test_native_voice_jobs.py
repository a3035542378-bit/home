import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ergou import agent_wechat,jobs,native_voice,voice_policy
from ergou.db import closing_db,initialize
from ergou.engine import receive
from tests.test_agent_wechat import Fixture
from tests.voice_credentials import preview_credential,verify_credential


class VoiceClaimTests(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"claims.sqlite"
        initialize(path)
        self.db=self.enterContext(closing_db(path))
        self.enterContext(patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_KEY":"synthetic"}))
        api=self.api=Fixture()
        self.admin=dict(name="owner",role="系统管理员",scopes="[]")
        agent_wechat.link(self.db,api,"测试群","x"*40)
        agent_wechat.Listener(self.db,api,"x"*40).verify()
        voice_policy.configure(self.db,self.admin,api.room,dict(action="switch",enabled=True,version=0))
        voice_policy.approve(self.db,voice_policy.preview(self.db,api.room))
        verify_credential(self.db,self.admin,api.room)
        self.p=self.db.execute("SELECT * FROM active_native_voice").fetchone()
        self.now=time.time()
        self.seq=receive(self.db,api.account,api.room,"member","77",{"text":"二狗积分"},
                         now=self.now,message_type="voice",adapter_version=native_voice.VERSION)
        self.db.execute("""INSERT INTO native_voice_events(grp,account,binding,generation,slot,server_id,message_id,
                        source,member,source_time,state,seq) VALUES(?,?,?,?,?,?,?,?,?,?,'AWAKE',?)""",
                        (api.room,api.account,self.p["binding"],self.p["generation"],api.slot,"daemon-id","m1",
                         "77","member",self.now,self.seq))
        self.db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
                        SELECT event_id,account,grp,binding,'本群积分 0','PENDING',?,?,? FROM inbox WHERE seq=?""",
                        (self.now,self.now+300,self.now,self.seq))

    def claim(self,now=None):
        return jobs.claim(self.db,self.api.account,self.now if now is None else now,directed_group=self.api.room)

    def test_only_directed_room_claims_voice_with_long_lease(self):
        self.assertFalse(jobs.claim(self.db,self.api.account,self.now,directed_group="elsewhere"))
        task=self.claim()
        self.assertEqual(task["voice_seq"],self.seq)
        self.assertEqual(task["lease"],self.now+120)
        self.assertFalse(self.claim(self.now+31))
        self.assertEqual(self.db.execute("SELECT state FROM outbox").fetchone()[0],"SENDING")

    def test_old_voice_not_claimed_even_if_outbox_has_time_left(self):
        self.db.execute("UPDATE nodes SET last_seen=?",(self.now+120,))
        self.assertFalse(self.claim(self.now+120))
        self.assertFalse(self.db.execute("SELECT 1 FROM attempts").fetchone())

    def test_voice_cannot_fall_into_text_or_generic_sender_on_revocation(self):
        self.db.execute("INSERT INTO directed_groups VALUES(?,?,?,?)",(self.api.room,self.api.account,
                        self.p["binding"],self.now-60))
        self.db.execute("INSERT INTO directed_events SELECT event_id,? FROM inbox WHERE seq=?",(self.now,self.seq))
        voice_policy.configure(self.db,self.admin,self.api.room,
                               dict(action="switch",enabled=False,version=self.p["generation"]))
        self.assertFalse(self.claim())
        self.db.execute("UPDATE account SET state='ONLINE' WHERE id=?",(self.api.account,))
        self.assertFalse(jobs.claim(self.db,self.api.account,self.now))
        self.assertFalse(self.db.execute("SELECT 1 FROM attempts").fetchone())

    def test_removed_credentials_cancel_pending_voice(self):
        with patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_KEY":"","ERGOU_BAIDU_SPEECH_TOKEN":""}):
            self.assertIs(self.claim(),True)
        self.assertEqual(tuple(self.db.execute("SELECT state,body FROM outbox").fetchone()),("CANCELLED",""))
        self.assertFalse(self.db.execute("SELECT 1 FROM attempts").fetchone())

    def test_cleanup_expires_stalled_recognition_and_deletes_day_old_metadata(self):
        for source,age,state in (("78",120,"PENDING"),("79",121,"PROCESSING"),("80",86400,"NOT_ADDRESSED")):
            self.db.execute("""INSERT INTO native_voice_events(grp,account,binding,generation,slot,server_id,
                   message_id,source,member,source_time,state) SELECT grp,account,binding,generation,slot,server_id,
                   message_id,?,member,?,? FROM native_voice_events WHERE seq=?""",(source,self.now-age,state,self.seq))
        jobs.cleanup(self.db,self.now)
        retained=dict(self.db.execute("SELECT source,state FROM native_voice_events"))
        self.assertEqual(retained,{"77":"AWAKE","78":"EXPIRED","79":"EXPIRED"})

    def test_cleanup_discards_expired_auditions_and_preserves_active_key(self):
        preview_credential(self.db,self.admin,self.api.room)
        expires=self.db.execute("SELECT expires FROM voice_test_tickets").fetchone()[0]
        jobs.cleanup(self.db,expires-.01)
        self.assertTrue(self.db.execute("SELECT 1 FROM voice_test_tickets").fetchone())
        jobs.cleanup(self.db,expires)
        self.assertFalse(self.db.execute("SELECT 1 FROM voice_test_tickets").fetchone())
        self.assertEqual(voice_policy.verified_credentials(self.db,self.api.room),("synthetic",""))
