import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ergou import agent_wechat,speech,voice_policy
from ergou.db import closing_db,demo,initialize
from tests.test_agent_wechat import Fixture
from tests.test_speech import recording


class VoiceValidation(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"voice.sqlite"
        initialize(path)
        demo(path,("other",))
        self.db=self.enterContext(closing_db(path))
        self.other_db=self.enterContext(closing_db(path))
        self.api=Fixture()
        self.grp=self.api.room
        agent_wechat.link(self.db,self.api,"测试群","s"*40)
        self.user=dict(name="voice-operator",role="运营管理员",scopes=json.dumps([self.grp,"other"]))
        self.enterContext(patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_KEY":"","ERGOU_BAIDU_SPEECH_TOKEN":""}))
        self.enterContext(patch("ergou.models.protect",side_effect=lambda raw,decrypt=False:raw[::-1]))
        self.post=self.enterContext(patch("ergou.speech._post",side_effect=self.response))
        self.sample=recording()
        self.transcript="二狗，二狗，语音测试。"
        self.fields("switch",enabled=True)
        voice_policy.approve(self.db,voice_policy.preview(self.db,self.grp))

    def response(self,host,path,body,key,limit):
        if host=="vop.baidu.com":
            return "application/json",json.dumps({"err_no":0,"result":[self.transcript]}).encode()
        self.assertEqual((host,body["format"],body["sample_rate"]),("aip.baidubce.com","wav",16000))
        return "audio/wav",base64.b64decode(self.sample)

    def fields(self,action,**extra):
        version=self.state()["version"]
        return voice_policy.configure(self.db,self.user,self.grp,dict(action=action,version=version,**extra))

    def state(self):
        return voice_policy.settings(self.db,self.user,self.grp)

    def preview_candidate(self,**extra):
        return voice_policy.test_credential(self.db,self.user,self.grp,
                                            dict(version=self.state()["version"],audio=self.sample,**extra))

    def activate(self,secret):
        preview=self.preview_candidate(kind="key",secret=secret)
        return self.fields("activate",ticket=preview["ticket"])

    def test_preview_never_sends_or_enables_and_ticket_promotes_only_the_tested_value(self):
        current=self.state()["version"]
        result=self.preview_candidate(kind="key",secret="private-candidate")
        self.assertEqual(result["transcript"],self.transcript)
        self.assertEqual(result["mime"],"audio/wav")
        self.assertTrue(speech.pcm_from_wav(base64.b64decode(result["audio"])))
        self.assertEqual(self.post.call_args_list[1].args[2]["text"],result["reply"])
        self.assertEqual([c.args[3] for c in self.post.call_args_list],["private-candidate"]*2)
        self.assertNotIn("private-candidate",str(result))
        for table in ("inbox","outbox","chat_requests","voice_credentials","native_voice_events","voice_verifications"):
            self.assertEqual(0,self.db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0])
        self.assertTrue(self.state()["approved"])
        self.assertFalse(self.state()["enabled"])
        with self.assertRaises(ValueError):
            voice_policy.verified_credentials(self.db,self.grp)
        with self.assertRaises(ValueError):
            self.fields("credential",kind="key",secret="bypass")
        state=self.fields("activate",ticket=result["ticket"],kind="key",secret="never-tested")
        self.assertTrue(state["enabled"])
        self.assertTrue(state["credential_verified"])
        self.assertGreater(state["version"],current)
        self.assertEqual(voice_policy.verified_credentials(self.db,self.grp),("private-candidate",""))
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            self.fields("activate",ticket=result["ticket"])

    def test_failures_and_abandoned_preview_keep_prior_working_credentials(self):
        before=self.activate("known-good")
        self.transcript="二狗，语音测试。"
        calls=self.post.call_count
        result=self.preview_candidate(kind="token",secret="untested-token")
        self.assertEqual(result["transcript"],self.transcript)
        self.assertFalse(result["ticket"] or result["audio"])
        self.assertEqual(calls+1,self.post.call_count)
        with patch.object(speech,"recognize",side_effect=ValueError("识别失败")),self.assertRaises(ValueError):
            self.preview_candidate(kind="key",secret="rejected")
        self.transcript="二狗二狗，测试"
        def damaged(host,*args):
            if host=="aip.baidubce.com":
                return "audio/wav",b"broken WAV"
            return self.response(host,*args)
        with patch("ergou.speech._post",side_effect=damaged):
            failed=self.preview_candidate(kind="key",secret="rejected")
        self.assertEqual(failed["transcript"],self.transcript)
        self.assertIn("合成测试失败",failed["error"])
        self.assertFalse(failed["ticket"] or failed["audio"])
        self.preview_candidate(kind="key",secret="abandoned")
        self.assertEqual(self.state(),before)
        self.assertEqual(voice_policy.verified_credentials(self.db,self.grp),("known-good",""))

    def test_only_current_group_actor_binding_and_ticket_lifetime_can_activate(self):
        actor=dict(self.user,name="second-operator")
        version=self.state()["version"]
        ticket=self.preview_candidate(kind="token",secret="private-token")["ticket"]
        def activate(user,group,v):
            voice_policy.configure(self.db,user,group,dict(action="activate",version=v,ticket=ticket))
        with self.assertRaisesRegex(ValueError,"CONFLICT"):activate(actor,self.grp,version)
        with self.assertRaisesRegex(ValueError,"CONFLICT"):activate(self.user,"other",0)
        with self.assertRaises(PermissionError):activate(dict(self.user,role="群管理员"),self.grp,version)
        self.db.execute("UPDATE groups SET binding=binding+1 WHERE id=?",(self.grp,))
        with self.assertRaisesRegex(ValueError,"CONFLICT"):activate(self.user,self.grp,version)
        self.db.execute("UPDATE groups SET binding=binding-1 WHERE id=?",(self.grp,))
        self.db.execute("UPDATE voice_test_tickets SET expires=0")
        with self.assertRaisesRegex(ValueError,"CONFLICT"):activate(self.user,self.grp,version)
        self.assertFalse(self.state()["enabled"])

    def test_existing_and_environment_credentials_require_their_own_test(self):
        self.db.execute("INSERT INTO voice_credentials VALUES(?, 'key', ?)",(self.grp,b"existing"[::-1]))
        self.assertFalse(self.state()["credential_verified"])
        saved=self.preview_candidate()
        self.fields("activate",ticket=saved["ticket"])
        self.assertEqual(voice_policy.verified_credentials(self.db,self.grp),("existing",""))
        self.fields("clear")
        with patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_TOKEN":"environment-token"}):
            self.assertFalse(self.state()["enabled"])
            first=self.preview_candidate()
            os.environ["ERGOU_BAIDU_SPEECH_TOKEN"]="rotated"
            with self.assertRaisesRegex(ValueError,"CONFLICT"):self.fields("activate",ticket=first["ticket"])
            second=self.preview_candidate()
            self.fields("activate",ticket=second["ticket"])
            self.assertEqual(voice_policy.verified_credentials(self.db,self.grp),("","rotated"))
            self.assertFalse(self.db.execute("SELECT 1 FROM voice_credentials").fetchone())
            os.environ["ERGOU_BAIDU_SPEECH_KEY"]="untested"
            self.assertFalse(self.state()["enabled"])
            self.assertIsNone(voice_policy.active(self.db,self.grp,self.api.account,1))
            with self.assertRaises(ValueError):voice_policy.verified_credentials(self.db,self.grp)

    def test_concurrent_group_change_after_asr_prevents_synthesis(self):
        def revoke(*args):
            version=self.state()["version"]
            voice_policy.configure(self.other_db,self.user,self.grp,dict(action="switch",enabled=False,version=version))
            return self.transcript
        with patch.object(speech,"recognize",side_effect=revoke),self.assertRaisesRegex(ValueError,"CONFLICT"):
            self.preview_candidate(kind="key",secret="new")
        self.post.assert_not_called()
        self.assertFalse(self.db.execute("SELECT 1 FROM voice_test_tickets").fetchone())

    def test_concurrent_activation_during_synthesis_keeps_winning_value(self):
        version=self.state()["version"]
        first=self.preview_candidate(kind="key",secret="first")
        def other_completed(*args):
            voice_policy.configure(self.other_db,self.user,self.grp,dict(action="activate",version=version,ticket=first["ticket"]))
            return base64.b64decode(self.sample)
        with patch.object(speech,"synthesize_wav",side_effect=other_completed),self.assertRaisesRegex(ValueError,"CONFLICT"):
            self.preview_candidate(kind="key",secret="stale")
        self.assertEqual(voice_policy.verified_credentials(self.db,self.grp),("first",""))

    def test_invalid_recording_or_scope_stops_before_baidu(self):
        fields=dict(version=self.state()["version"],kind="key",secret="test",audio=self.sample)
        for user in (dict(self.user,role="只读人员"),dict(self.user,scopes='["other"]')):
            with self.assertRaises(PermissionError):
                voice_policy.test_credential(self.db,user,self.grp,fields)
        for payload in (dict(fields,audio="bad"),dict(fields,secret="bad key"),dict(fields,version=-1)):
            with self.assertRaises(ValueError):
                voice_policy.test_credential(self.db,self.user,self.grp,payload)
        self.post.assert_not_called()
