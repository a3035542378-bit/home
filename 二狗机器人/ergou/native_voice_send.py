"""Submit a single native voice note through Agent WeChat 2.7.1's loopback API."""
import hashlib
import http.client
import json
import re
import secrets
import time
from urllib.parse import quote, urlencode

from . import speech
from .db import dump


class _Status(ValueError):
    def __init__(self,status):
        self.status=status
        super().__init__(f"插件 HTTP {status}")


_ERRORS=(ValueError,OSError,http.client.HTTPException)
_REVOKED=("FAILED","本群语音回复授权已变化")
_UNKNOWN=("UNKNOWN","语音提交结果待核对")


def _request(client,token,method,path,body=None,headers=None):
    conn=http.client.HTTPConnection("127.0.0.1",client.port,timeout=6)
    try:
        conn.request(method,client.base+path,body=body,
                     headers={"Authorization":"Bearer "+token,"Accept":"application/json",**(headers or {})})
        response=conn.getresponse()
        if not 200<=response.status<300:
            raise _Status(response.status)
        raw=response.read(65537)
        if len(raw)>65536:
            raise ValueError("插件回执过大")
        result=json.loads(raw)
        if not isinstance(result,dict):
            raise ValueError("插件回执格式错误")
        return result
    finally:
        conn.close()


def _id(value,prefix):
    return isinstance(value,str) and re.fullmatch(prefix+r"_[a-zA-Z0-9-]{1,100}",value) is not None


def _upload(client,token,audio):
    boundary="ergou-"+secrets.token_hex(20)
    start=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reply.wav"\r\n'
           'Content-Type: audio/wav\r\n\r\n').encode("ascii")
    body=start+audio+f"\r\n--{boundary}--\r\n".encode("ascii")
    return _request(client,token,"POST","/uploads",body,{"Content-Type":"multipart/form-data; boundary="+boundary})


def _release(client,token,source):
    try:
        _request(client,token,"DELETE","/uploads/"+source)
    except _ERRORS:
        pass  # Cleanup cannot change a previously verified delivery result.


def _receipt(client,token,group,source,key,job,timeout):
    path="/sends/by-idempotency-key?"+urlencode({"key":key})
    deadline=time.monotonic()+timeout
    while True:
        try:
            if job is None:
                job=_request(client,token,"GET",path)
            job_id=job.get("id")
            if (not _id(job_id,"job") or job.get("kind")!="send" or job.get("sourceId")!=source
                    or job.get("threadId")!=group or job.get("accountId")!=client.slot):
                return "UNKNOWN","媒体任务的身份与本群语音不符"
            path="/jobs/"+job_id
            state=job.get("state")
            if state in ("failed","cancelled","expired","unsupported"):
                return "FAILED","插件未完成本群语音发送"
            if state=="accepted":
                result=job.get("result")
                result=result if isinstance(result,dict) else {}
                native=result.get("nativeReceipt")
                sid=job.get("serverMessageId")
                if (not isinstance(native,dict) or native.get("status")!="server_accepted"
                        or native.get("clientIdMatches") is not True or native.get("serviceCode")!=0
                        or not isinstance(sid,str) or not re.fullmatch("[0-9]{1,20}",sid)
                        or not 0<int(sid)<2**64 or native.get("serverMessageId")!=sid):
                    return _UNKNOWN
                mids=result.get("messageIds")
                if isinstance(mids,list) and len(mids)==1 and isinstance(mids[0],str) and 0<len(mids[0])<=4096:
                    msg=client.get(client.base+"/messages/"+quote(mids[0],safe=""))
                    fields=(msg.get("id"),msg.get("accountId"),msg.get("threadId"),msg.get("direction"),msg.get("serverId"),msg.get("type"))
                    if fields==(mids[0],client.slot,group,"outgoing",sid,34):
                        return "ACKNOWLEDGED","已核对本群原生语音的微信回执和发件记录"
                    return "UNKNOWN","微信语音回执与发件记录不符"
                if mids or result.get("profileProjection")=="complete":
                    return _UNKNOWN
            elif state not in ("queued","running"):
                return _UNKNOWN
        except _ERRORS:
            pass  # Recover a lost submit response or lagging projection by reading only.
        job=None
        remaining=deadline-time.monotonic()
        if remaining<=0:
            return _UNKNOWN
        time.sleep(min(.4,remaining))


def send_voice(client,send_token,task,authorized,auth,*,timeout=10):
    """Return an outbox result. Ambiguous submissions are inspected, never repeated."""
    if not authorized():
        return _REVOKED
    text=task["body"].strip()
    if not text:
        return "FAILED","语音回复为空"
    if len(text)>120:
        text=text[:120].rstrip("。，、：； ")+"。回复较长，先读到这里。"
    try:
        audio=speech.synthesize_wav(text,auth)
    except _ERRORS:
        return "FAILED","百度语音合成失败，请检查凭据、额度和音频格式"
    if not authorized():
        return _REVOKED
    try:
        upload=_upload(client,send_token,audio)
    except _ERRORS:
        return "FAILED","本机插件接收语音素材失败"
    source=upload.get("id")
    if (not _id(source,"upload") or upload.get("byteLength")!=len(audio)
            or upload.get("sha256")!=hashlib.sha256(audio).hexdigest() or upload.get("mediaType")!="audio/wav"):
        return "FAILED","插件的语音素材完整性校验失败"
    key="ergou-voice-"+hashlib.sha256(dump([client.slot,task["grp"],task["binding"],task["biz"]]).encode()).hexdigest()
    body=dump({"kind":"voice","threadId":task["grp"],"sourceId":source}).encode()
    release=True
    try:
        if not authorized():
            return _REVOKED
        release=False
        try:
            job=_request(client,send_token,"POST","/sends",body,
                         {"Content-Type":"application/json","Idempotency-Key":key})
        except _Status as error:
            if error.status in (400,401,403,404,413,422):
                release=True
                return "FAILED",f"本机插件拒绝语音发送 HTTP {error.status}"
            job=None
        except _ERRORS:
            job=None
        state,detail=_receipt(client,send_token,task["grp"],source,key,job,timeout)
        release=state in ("ACKNOWLEDGED","FAILED")
        return state,detail
    finally:
        if release:
            _release(client,send_token,source)
