"""Baidu speech recognition and synthesis for native voice notes and test recordings."""
import base64
import binascii
import hashlib
import http.client
import io
import json
import os
import re
import struct
import time
import wave
from urllib.parse import urlencode

from . import admin
from .db import allowed, dump, transaction
from .engine import receive


MAX_WAV=60*16000*2+8192
VERSION="baidu-speech-simulation/1"
TTS_PATH="/rest/2.0/speech/publiccloudspeech/v1/tts"


def _simulation(db,u,group):
    admin.permitted(u,group,True)
    g=db.execute("""SELECT g.*,a.mode FROM groups g JOIN account a ON a.id=g.account WHERE g.id=?""",(group,)).fetchone()
    if not g or g["mode"]!="simulation":
        raise PermissionError("FORBIDDEN 语音联调仅对已授权模拟群开放")
    if g["paused"] or not json.loads(g["config"])["enabled"]:
        raise ValueError("本群已暂停")
    return g


def _pcm(encoded):
    if not isinstance(encoded,str) or len(encoded)>(MAX_WAV+2)//3*4:
        raise ValueError("请上传不超过 60 秒的 WAV")
    try:
        raw=base64.b64decode(encoded,validate=True)
    except (binascii.Error,ValueError):
        raise ValueError("请上传完整的 16 kHz、16 位、单声道 PCM WAV，最长 60 秒") from None
    return pcm_from_wav(raw)


def pcm_from_wav(raw,*,convert=False):
    """Validate a complete PCM WAV; native media may need channel/rate conversion."""
    limit=60*48000*4+8192 if convert else MAX_WAV
    try:
        if len(raw)>limit:
            raise ValueError()
        with wave.open(io.BytesIO(raw)) as wav:
            frames,rate,channels=wav.getnframes(),wav.getframerate(),wav.getnchannels()
            if (wav.getsampwidth()!=2 or wav.getcomptype()!="NONE" or not 1<=frames<=rate*60
                    or rate not in (8000,12000,16000,22050,24000,32000,44100,48000) or channels not in (1,2)
                    or (not convert and (rate,channels)!=(16000,1))):
                raise ValueError()
            data=wav.readframes(frames)
            if len(data)!=frames*2*channels:
                raise ValueError()
        if (channels,rate)!=(1,16000):
            import audioop  # Windows deployment is pinned to Python 3.12.
            if channels==2:
                data=audioop.tomono(data,2,.5,.5)
            if rate!=16000:
                data,_=audioop.ratecv(data,2,1,rate,16000,None)
        return data
    except (ValueError,EOFError,struct.error,wave.Error,ImportError):
        message="微信语音播放副本格式不支持或超过 60 秒" if convert else "请上传完整的 16 kHz、16 位、单声道 PCM WAV，最长 60 秒"
        raise ValueError(message) from None


def _auth():
    key=os.environ.get("ERGOU_BAIDU_SPEECH_KEY","").strip()
    token=os.environ.get("ERGOU_BAIDU_SPEECH_TOKEN","").strip()
    if not key and not token:
        raise ValueError("百度语音服务凭据尚未配置")
    if not re.fullmatch(r"[!-~]{1,4096}",key or token):
        raise ValueError("百度语音凭据格式无效")
    return key,token


def _post(host,path,body,key,limit):
    headers={"Content-Type":"application/json"}
    if key:headers["Authorization"]="Bearer "+key
    conn=http.client.HTTPSConnection(host,timeout=25)
    try:
        conn.request("POST",path,body=dump(body).encode(),headers=headers)
        response=conn.getresponse()
        if response.status!=200:
            raise ValueError(f"百度语音服务返回 HTTP {response.status}")
        data=response.read(limit+1)
        if len(data)>limit:
            raise ValueError("百度语音响应过大")
        return response.getheader("Content-Type","").split(";")[0].lower(),data
    except (OSError,http.client.HTTPException):
        raise ValueError("百度语音连接失败或超时") from None
    finally:
        conn.close()


def recognize(pcm,auth):
    key,token=auth
    body=dict(format="pcm",rate=16000,channel=1,cuid="ergou-robot",dev_pid=1537,
              speech=base64.b64encode(pcm).decode("ascii"),len=len(pcm))
    if not key:body["token"]=token
    _,raw=_post("vop.baidu.com","/server_api",body,key,65536)
    try:
        result=json.loads(raw)
        if result["err_no"]==0 and isinstance(result["result"][0],str) and result["result"][0].strip():
            return result["result"][0].strip()
    except (KeyError,TypeError,IndexError,ValueError):
        pass
    raise ValueError("百度语音识别失败，请核对录音和服务授权")


def _synthesis(text,auth,format_name,types,limit):
    key,token=auth
    if len(text.encode("gbk",errors="replace"))>=1024:
        raise ValueError("回复超过百度短文本语音长度，请查看文字回复")
    path=TTS_PATH if key else TTS_PATH+"?"+urlencode({"access_token":token})
    kind,body=_post("aip.baidubce.com",path,
                    dict(text=text,voice="5003",format=format_name,lang="zh",sample_rate=16000),key,limit)
    if kind not in types or not body:
        raise ValueError("百度语音合成失败，请核对语音合成权限和额度")
    return body


def synthesize(text,auth):
    body=_synthesis(text,auth,"mp3",("audio/mpeg","audio/mp3"),4*1024*1024)
    return {"audio":base64.b64encode(body).decode("ascii"),"mime":"audio/mpeg"}


def synthesize_wav(text,auth):
    """Return a single voice note's worth of canonical PCM WAV for the native sender."""
    body=_synthesis(text,auth,"wav",("audio/wav","audio/x-wav","audio/wave"),MAX_WAV)
    pcm=pcm_from_wav(body)
    output=io.BytesIO()
    with wave.open(output,"wb") as wav:
        wav.setparams((1,2,16000,0,"NONE","not compressed"))
        wav.writeframes(pcm)
    return output.getvalue()


def _actor(u):
    return "operator" if u["role"]=="系统管理员" else "ui-"+u["name"]


def detect(db,u,group,data):
    from .voice_policy import credentials
    from .native_voice import wake_command
    g=_simulation(db,u,group)
    key=data.get("key")
    if not isinstance(key,str) or not 1<=len(key)<=120:
        raise ValueError("语音联调需要幂等键")
    pcm=_pcm(data.get("audio"))
    source="speech/"+hashlib.sha256(dump([group,u["name"],key]).encode()).hexdigest()
    signature=dump([g["binding"],hashlib.sha256(pcm).hexdigest()])
    now=time.time()
    reservation="running/"+str(now)
    with transaction(db):
        old=db.execute("SELECT signature,result FROM operations WHERE grp=? AND key=?",(group,source)).fetchone()
        if old:
            if old["signature"]!=signature:
                raise ValueError("CONFLICT 语音请求的内容或群绑定与原请求不同")
            if old["result"]=="ignored":
                return {"seq":None,"addressed":False}
            seq=db.execute("SELECT seq FROM inbox WHERE account=? AND grp=? AND source=? AND adapter_version=?",
                           (g["account"],group,source,VERSION)).fetchone()
            if seq:return {"seq":seq[0],"addressed":True}
            if float(old["result"].removeprefix("running/"))>now-90:
                raise ValueError("CONFLICT 语音正在识别，请稍后重试")
        auth=credentials(db,group)
        if not allowed(db,"speech/asr/"+group,8,60,now):
            raise ValueError("RATE_LIMITED 本群语音识别请求过于频繁")
        db.execute("INSERT OR REPLACE INTO operations VALUES(?,?,?,?)",(source,group,signature,reservation))
    try:
        text=recognize(pcm,auth).strip()
        current=_simulation(db,u,group)
        if g["binding"]!=current["binding"]:
            raise ValueError("CONFLICT 本群绑定已改变")
        prefix=json.loads(current["config"])["prefix"]
        # An ASR result cannot attest to a platform mention. Only the spoken wake word is accepted.
        cmd=wake_command(text)
        spoken=cmd is not None
        seq=None
        if spoken:
            seq=receive(db,current["account"],group,_actor(u),source,{"text":prefix+" "+cmd},adapter_version=VERSION)
        db.execute("UPDATE operations SET result=? WHERE grp=? AND key=? AND result=?",
                   (str(seq) if spoken else "ignored",group,source,reservation))
        return dict(seq=seq,addressed=spoken)
    except Exception:
        db.execute("DELETE FROM operations WHERE grp=? AND key=? AND result=?",(group,source,reservation))
        raise


def audio_reply(db,u,group,data):
    from .voice_policy import credentials
    g=_simulation(db,u,group)
    seq=data.get("seq")
    if type(seq) is not int or not 1<=seq<2**63:
        raise ValueError("语音回复序号无效")
    reply=db.execute("""SELECT o.body FROM inbox i JOIN outbox o ON o.biz=i.event_id AND o.grp=i.grp
                AND o.account=i.account AND o.binding=i.binding WHERE i.seq=? AND i.grp=? AND i.account=?
                AND i.binding=? AND i.member=? AND i.adapter_version=? AND o.state IN ('PENDING','SENDING','ACKNOWLEDGED')""",
                (seq,group,g["account"],g["binding"],_actor(u),VERSION)).fetchone()
    if not reply or not reply[0]:
        raise ValueError("此模拟语音请求尚无可合成的文字回复")
    auth=credentials(db,group)
    with transaction(db):
        if not allowed(db,"speech/tts/"+group,8,60,time.time()):
            raise ValueError("RATE_LIMITED 本群语音合成请求过于频繁")
    return synthesize(reply[0],auth)
