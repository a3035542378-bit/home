import hashlib
import io
import json
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit
from unittest.mock import Mock,patch

from ergou import native_voice_send as voice, speech
from ergou.agent_wechat import Client


def recording(rate=16000,seconds=.1):
    out=io.BytesIO()
    with wave.open(out,"wb") as wav:
        wav.setparams((1,2,rate,0,"NONE","not compressed"))
        wav.writeframes(bytes(2*int(rate*seconds)))
    return out.getvalue()


class VoiceReceiver(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def reply(self,status,data):
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        ctx=self.server.ctx
        data=self.rfile.read(int(self.headers["Content-Length"]))
        ctx.calls.append((self.command,self.path,self.headers["Authorization"]))
        if self.path.endswith("/uploads"):
            boundary=self.headers["Content-Type"].split("boundary=")[1].encode()
            header,audio=data.split(b"\r\n\r\n",1)
            expected=b'--'+boundary+b'\r\nContent-Disposition: form-data; name="file"; filename="reply.wav"\r\nContent-Type: audio/wav'
            mime="image/jpeg" if getattr(ctx,"image",False) else "audio/wav"
            if mime=="image/jpeg":
                expected=expected.replace(b"reply.wav",b"card.jpg").replace(b"audio/wav",b"image/jpeg")
            footer=b"\r\n--"+boundary+b"--\r\n"
            if header!=expected or not audio.endswith(footer) or audio[:-len(footer)]!=ctx.wav:
                return self.reply(400,{})
            digest=hashlib.sha256(ctx.wav).hexdigest() if ctx.intact else "0"*64
            return self.reply(201,dict(id="upload-incorrect" if ctx.bad_id else "upload_A",
                                       mediaType=mime,sha256=digest,byteLength=len(ctx.wav)))
        if self.path.endswith("/sends"):
            ctx.payload=json.loads(data)
            ctx.key=self.headers["Idempotency-Key"]
            if ctx.lost:
                self.close_connection=True
                return
            return self.reply(202,dict(ctx.job,state="running"))
        self.reply(404,{})

    def do_GET(self):
        ctx=self.server.ctx
        ctx.calls.append((self.command,self.path,self.headers["Authorization"]))
        if self.path.endswith("/jobs/job_A") or ("/sends/by-idempotency-key?" in self.path
                and parse_qs(urlsplit(self.path).query).get("key")==[ctx.key]):
            return self.reply(200,ctx.job)
        if self.path.endswith("/messages/m%2F1"):
            return self.reply(200,ctx.message)
        self.reply(404,{})

    def do_DELETE(self):
        self.server.ctx.calls.append((self.command,self.path,self.headers["Authorization"]))
        self.reply(200,dict(released=True))


class VoiceDispatchTests(unittest.TestCase):
    def setUp(self):
        self.wav=recording()
        self.post=self.enterContext(patch.object(speech,"_post",return_value=("audio/wav",self.wav)))
        self.calls=[]
        self.intact=True
        self.bad_id=self.lost=False
        self.key=None
        self.task=dict(grp="family@chatroom",binding=3,biz="voice-event",body="本群积分 0")
        self.message=dict(id="m/1",accountId="local",threadId=self.task["grp"],direction="outgoing",
                          serverId="555",type=34)
        self.job=dict(id="job_A",accountId="local",kind="send",sourceId="upload_A",
                      threadId=self.task["grp"],state="accepted",serverMessageId="555",
                      result=dict(messageIds=["m/1"],nativeReceipt=dict(status="server_accepted",
                                  clientIdMatches=True,serviceCode=0,serverMessageId="555")))
        server=ThreadingHTTPServer(("127.0.0.1",0),VoiceReceiver)
        server.ctx=self
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,kwargs={"poll_interval":.01},daemon=True).start()
        self.client=Client(server.server_port,"local","read-test")

    def send(self,authorized=lambda:True,timeout=.5):
        return voice.send_voice(self.client,"send-test",self.task,authorized,("tts-test",""),timeout=timeout)[0]

    def test_single_native_note_and_remote_readback(self):
        self.assertEqual(self.send(),"ACKNOWLEDGED")
        self.assertEqual(self.payload,dict(kind="voice",threadId=self.task["grp"],sourceId="upload_A"))
        self.assertRegex(self.key,r"^ergou-voice-[0-9a-f]{64}$")
        self.assertEqual([(m,p.removeprefix(self.client.base),t) for m,p,t in self.calls],[
            ("POST","/uploads","Bearer send-test"),("POST","/sends","Bearer send-test"),
            ("GET","/jobs/job_A","Bearer send-test"),("GET","/messages/m%2F1","Bearer read-test"),
            ("DELETE","/uploads/upload_A","Bearer send-test")])
        host,path,params,key,_=self.post.call_args.args
        self.assertEqual((host,path,params["format"],params["sample_rate"],key),
                         ("aip.baidubce.com",speech.TTS_PATH,"wav",16000,"tts-test"))

    def test_prepared_jpeg_single_submit_without_game_event(self):
        from tools.check_sample_card import SAMPLE
        self.wav=SAMPLE.read_bytes()
        self.image=True
        self.message["type"]=3
        self.task["biz"]="sample-"+hashlib.sha256(self.wav).hexdigest()
        self.lost=True
        state,_=voice.send_media(self.client,"send-test",self.task,lambda:True,self.wav,"image",timeout=.2)
        self.assertEqual(state,"ACKNOWLEDGED")
        self.assertEqual(sum(method=="POST" and path.endswith("/sends") for method,path,_ in self.calls),1)

    def test_image_lost_submit_and_wrong_projection(self):
        self.image=self.lost=True
        self.wav=b"fixture-image"
        self.message["type"]=3
        def send():
            return voice.send_media(self.client,"send-test",self.task,lambda:True,self.wav,"image",timeout=.1)[0]
        self.assertEqual("ACKNOWLEDGED",send())
        self.assertEqual(self.payload["kind"],"image")
        self.assertEqual(sum(m=="POST" and p.endswith("/sends") for m,p,_ in self.calls),1)
        self.calls.clear()
        self.task["biz"]="another-image"
        self.message["type"]=1
        self.assertEqual("UNKNOWN",send())
        self.assertEqual(sum(m=="POST" and p.endswith("/sends") for m,p,_ in self.calls),1)

    def test_lost_ack_uses_only_idempotency_readback(self):
        self.lost=True
        self.assertEqual(self.send(),"ACKNOWLEDGED")
        self.assertEqual([p for m,p,_ in self.calls if m=="POST"],[self.client.base+"/uploads",self.client.base+"/sends"])
        self.assertTrue(any("/sends/by-idempotency-key?" in p for _,p,_ in self.calls))

    def test_revocation_before_tts_after_tts_and_after_upload(self):
        self.assertEqual(self.send(lambda:False),"FAILED")
        self.post.assert_not_called()
        self.assertEqual(self.send(Mock(side_effect=[True,False])),"FAILED")
        self.assertFalse(self.calls)
        self.assertEqual(self.send(Mock(side_effect=[True,True,False])),"FAILED")
        self.assertEqual([m for m,_,_ in self.calls],["POST","DELETE"])
        self.assertFalse(self.key)

    def test_damaged_source_and_invalid_wav_never_submitted(self):
        self.post.return_value=("audio/wav",recording(rate=8000))
        self.assertEqual(self.send(),"FAILED")
        self.assertFalse(self.calls)
        self.post.return_value=("audio/wav",self.wav)
        self.intact=False
        self.assertEqual(self.send(),"FAILED")
        self.assertEqual([p for _,p,_ in self.calls],[self.client.base+"/uploads"])

    def test_accepted_receipt_mismatched_message_stays_unknown(self):
        self.message["threadId"]="elsewhere"
        self.assertEqual(self.send(),"UNKNOWN")
        self.assertFalse(any(m=="DELETE" for m,_,_ in self.calls))
        self.job["sourceId"]="upload_other"
        self.calls.clear()
        self.assertEqual(self.send(),"UNKNOWN")
        self.assertFalse(any("/messages/" in p for _,p,_ in self.calls))

    def test_unknown_receipt_is_not_resent(self):
        self.job["state"]="needs_review"
        self.assertEqual(self.send(),"UNKNOWN")
        self.assertEqual(sum(m=="POST" and p.endswith("/sends") for m,p,_ in self.calls),1)

    def test_long_reply_abbreviated_to_single_note(self):
        self.task["body"]="积分"*140
        self.assertEqual(self.send(),"ACKNOWLEDGED")
        self.assertEqual(self.post.call_args.args[2]["text"],"积分"*60+"。回复较长，先读到这里。")

    def test_provider_audio_cannot_produce_multiple_voice_notes(self):
        self.post.return_value=("audio/wav",recording(seconds=61))
        self.assertEqual(self.send(),"FAILED")
        self.assertFalse(self.calls)
