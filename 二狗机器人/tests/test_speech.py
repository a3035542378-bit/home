import base64
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import wave
from pathlib import Path
from unittest.mock import patch

from ergou import admin, speech, web
from ergou.db import closing_db, demo, initialize
from ergou.engine import step


def recording(rate=16000,byte=b"\x00"):
    output=io.BytesIO()
    with wave.open(output,"wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(byte*3200)
    return base64.b64encode(output.getvalue()).decode("ascii")


class SpeechTests(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"voice.sqlite"
        initialize(path)
        demo(path,("a","b"))
        self.db=self.enterContext(closing_db(path))
        self.user=dict(name="ops",role="运营管理员",scopes='["a"]')
        self.fields=dict(key="once",audio=recording())
        self.enterContext(patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_KEY":"fake-simulation-key"}))
        self.post=self.enterContext(patch("ergou.speech._post"))

    def test_scoped_voice_loop_and_retry(self):
        self.post.side_effect=[("application/json",json.dumps({"err_no":0,"result":["二狗，二狗，积分。"]}).encode()),
                               ("audio/mp3",b"mock-mp3")]
        first=speech.detect(self.db,self.user,"a",self.fields)
        self.assertTrue(first["addressed"])
        self.assertEqual(first,speech.detect(self.db,self.user,"a",self.fields))
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            speech.detect(self.db,self.user,"a",dict(self.fields,audio=recording(byte=b"1")))
        req=self.post.call_args.args
        self.assertEqual(req[:2],("vop.baidu.com","/server_api"))
        self.assertEqual(req[2]["len"],3200)
        self.assertNotIn("token",req[2])
        self.assertTrue(step(self.db))
        with self.assertRaises(ValueError):
            speech.audio_reply(self.db,dict(self.user,name="other"),"a",first)
        with self.assertRaises(PermissionError):
            speech.audio_reply(self.db,self.user,"b",first)
        result=speech.audio_reply(self.db,self.user,"a",first)
        self.assertEqual(base64.b64decode(result["audio"]),b"mock-mp3")
        self.assertEqual(self.post.call_count,2)
        self.assertEqual(self.post.call_args.args[2]["text"],"本群积分 0")
        self.assertIsNone(self.db.execute("SELECT payload FROM inbox").fetchone()[0])
        self.assertNotIn(self.fields["audio"],str([tuple(r) for r in self.db.execute("SELECT * FROM operations")]))

    def test_nonaddressed_bad_wav_offline_and_real_group(self):
        self.post.return_value=("application/json",b'{"err_no":0,"result":["hello"]}')
        for bad in ("",recording(8000),"!!!"):
            with self.assertRaises(ValueError):
                speech.detect(self.db,self.user,"a",dict(self.fields,audio=bad))
        with patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_KEY":"","ERGOU_BAIDU_SPEECH_TOKEN":""}),self.assertRaisesRegex(ValueError,"凭据"):
            speech.detect(self.db,self.user,"a",self.fields)
        with self.assertRaises(PermissionError):
            speech.detect(self.db,dict(self.user,role="只读人员"),"a",self.fields)
        self.assertFalse(self.post.called)
        for _ in range(2):
            self.assertEqual(speech.detect(self.db,self.user,"a",self.fields),dict(seq=None,addressed=False))
        self.assertEqual(self.post.call_count,1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0],0)
        self.db.execute("UPDATE account SET mode='adapter' WHERE id='sim-account'")
        with self.assertRaises(PermissionError):
            speech.detect(self.db,self.user,"a",dict(self.fields,key="different"))
        self.assertEqual(self.post.call_count,1)

    def test_upload_http_entry_accepts_large_wav(self):
        self.post.return_value=("application/json",json.dumps({"err_no":0,"result":["二狗二狗积分。"]}).encode())
        admin.user(self.db,"http-ops","ui-test-password","运营管理员",["a"])
        dbpath=self.db.execute("PRAGMA database_list").fetchone()[2]
        server=web.server(dbpath,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cookie=""
        def post(path,payload):
            req=urllib.request.Request(f"http://127.0.0.1:{server.server_port}"+path,
                    data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Cookie":cookie})
            with opener.open(req,timeout=4) as response:
                return json.load(response),response.headers.get("Set-Cookie","").split(";")[0]
        _,cookie=post("/api/login",dict(name="http-ops",password="ui-test-password"))
        # A one-second buffer is already larger than the ordinary admin request body limit.
        out=io.BytesIO()
        with wave.open(out,"wb") as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
            wav.writeframes(bytes(32000))
        reply,_=post("/api/speech/detect",dict(group="a",audio=base64.b64encode(out.getvalue()).decode(),key="large"))
        self.assertTrue(reply["addressed"])
        step(self.db)
        self.post.return_value=("audio/mp3",b"test-audio")
        audio,_=post("/api/speech/reply",dict(group="a",seq=reply["seq"]))
        self.assertEqual(base64.b64decode(audio["audio"]),b"test-audio")
