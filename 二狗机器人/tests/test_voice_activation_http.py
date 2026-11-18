import base64
import json
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from unittest.mock import patch

from ergou import admin, agent_wechat, speech, voice_policy, web
from ergou.db import closing_db, initialize
from tests.test_agent_wechat import Fixture


class VoiceActivationHTTP(unittest.TestCase):
    def test_operator_can_preview_then_activate_in_an_approved_group(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"activation.sqlite"
        initialize(path)
        db=self.enterContext(closing_db(path))
        wx=Fixture()
        agent_wechat.link(db,wx,"测试群","a"*40)
        admin.user(db,"ops","test-password-voice","运营管理员",[wx.room])
        actor=dict(name="ops",role="运营管理员",scopes=json.dumps([wx.room]))
        voice_policy.configure(db,actor,wx.room,dict(action="switch",version=0,enabled=True))
        voice_policy.approve(db,voice_policy.preview(db,wx.room))
        self.enterContext(patch("ergou.models.protect",side_effect=lambda raw,decrypt=False:raw[::-1]))

        server=web.server(path,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join,2)
        self.addCleanup(server.shutdown)
        base=f"http://127.0.0.1:{server.server_port}"
        client=build_opener(ProxyHandler({}),HTTPCookieProcessor(CookieJar()))
        def post(route,fields):
            request=Request(base+route,data=json.dumps(fields).encode(),headers={"Content-Type":"application/json"})
            with client.open(request,timeout=4) as response:
                return json.load(response)
        with client.open(base+"/voice-sample.wav") as response:
            self.assertEqual(response.headers.get_content_type(),"audio/wav")
            sample=response.read()
        pcm=speech.pcm_from_wav(sample)
        self.assertTrue(any(pcm))
        credential="fictional-api-key"
        version=voice_policy.settings(db,actor,wx.room)["version"]
        fields=dict(group=wx.room,version=version,kind="key",secret=credential,
                    audio=base64.b64encode(sample).decode("ascii"))
        heard="二狗，二狗，语音测试。"
        def baidu(host,route,body,key,limit):
            self.assertEqual(key,credential)
            if host=="vop.baidu.com":
                self.assertEqual(base64.b64decode(body["speech"]),pcm)
                return "application/json",json.dumps({"err_no":0,"result":[heard]}).encode()
            self.assertEqual((host,body["format"]),("aip.baidubce.com","wav"))
            return "audio/wav",sample
        policy="/api/voice-policy"
        with patch("ergou.speech._post",side_effect=baidu) as provider:
            with self.assertRaises(HTTPError) as error:
                post(policy+"/test",fields)
            self.assertEqual(error.exception.code,401)
            post("/api/login",dict(name="ops",password="test-password-voice"))
            with self.assertRaises(HTTPError) as error:
                post(policy+"/test",dict(fields,group="another-room"))
            self.assertEqual(error.exception.code,403)
            provider.assert_not_called()
            preview=post(policy+"/test",fields)
            self.assertEqual(preview["transcript"],heard)
            self.assertTrue(preview["reply"])
            self.assertEqual(preview["mime"],"audio/wav")
            self.assertEqual(speech.pcm_from_wav(base64.b64decode(preview["audio"])),pcm)
            self.assertNotIn(credential,json.dumps(preview))
            self.assertIsNone(voice_policy.active(db,wx.room,wx.account,1))
            activated=post(policy,dict(group=wx.room,version=version,action="activate",ticket=preview["ticket"]))
            self.assertTrue(activated["credential_verified"] and activated["enabled"])
            self.assertEqual(voice_policy.active(db,wx.room,wx.account,1),activated["version"])
            self.assertEqual(provider.call_count,2)
        for table in ("inbox","outbox","native_voice_events"):
            self.assertFalse(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone())
