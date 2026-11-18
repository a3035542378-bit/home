"""Read one authorized incoming message's normal voice variant from Agent WeChat."""
import hashlib
import http.client
import json
import re
import time
from urllib.parse import quote

from .speech import pcm_from_wav

MAX_BYTES=60*48000*4+8192


def _identifier(value):
    return isinstance(value,str) and 0<len(value)<=8192 and value.isprintable()


def _playable(client,path,message_id):
    page=client.get(path)
    items=page.get("items")
    if not isinstance(items,list) or any(not isinstance(a,dict) or a.get("accountId")!=client.slot
                                          or a.get("messageId")!=message_id for a in items):
        raise ValueError("微信语音附件与来源消息不符")
    matches=[a for a in items if a.get("kind")=="voice" and a.get("variant")=="normal"]
    if len(matches)!=1 or not _identifier(matches[0].get("id")):
        raise ValueError("未找到唯一的微信语音播放副本")
    return matches[0]


def _start(client,path,message_id,asset_id):
    conn=http.client.HTTPConnection("127.0.0.1",client.port,timeout=8)
    try:
        conn.request("POST",path,body=json.dumps(dict(messageId=message_id,assetId=asset_id,quality="normal")).encode(),
                     headers={"Authorization":"Bearer "+client.token,"Content-Type":"application/json"})
        response=conn.getresponse()
        if response.status!=202:
            raise ValueError(f"微信语音下载请求返回 HTTP {response.status}")
        raw=response.read(65537)
        if len(raw)>65536:
            raise ValueError("微信语音下载回执过大")
        return json.loads(raw)
    finally:
        conn.close()


def _wait_job(client,job,asset_id,check,deadline):
    job_id=job.get("id") if isinstance(job,dict) else None
    if not _identifier(job_id):
        raise ValueError("微信语音下载回执无效")
    while True:
        if (job.get("id")!=job_id or job.get("accountId")!=client.slot or job.get("assetId")!=asset_id
                or job.get("kind")!="download"):
            raise ValueError("微信语音下载任务与附件不符")
        if job.get("state")=="available":
            return
        if job.get("state") not in ("queued","running") or time.monotonic()>=deadline:
            raise ValueError("微信语音下载未完成")
        time.sleep(.35)
        check()
        job=client.get(client.base+"/jobs/"+quote(job_id,safe=""))


def fetch_pcm(client,message_id,check):
    """Caller owns group/sender verification. check() must raise on revocation or expiry."""
    check()
    if not _identifier(message_id):
        raise ValueError("微信语音消息 ID 无效")
    path=client.base+"/messages/"+quote(message_id,safe="")+"/media"
    asset=_playable(client,path,message_id)
    asset_id=asset["id"]
    if asset.get("state")=="pending":
        check()
        job_id=asset.get("jobId")
        if job_id is None:
            job=_start(client,path+"-transfers",message_id,asset_id)
        elif _identifier(job_id):
            job=client.get(client.base+"/jobs/"+quote(job_id,safe=""))
        else:
            raise ValueError("微信语音下载任务标识无效")
        _wait_job(client,job,asset_id,check,time.monotonic()+18)
        check()
        asset=_playable(client,path,message_id)
    if (asset["id"]!=asset_id or asset.get("state")!="available" or asset.get("actualVariant")!="normal"
            or asset.get("contentType")!="audio/wav"):
        raise ValueError("微信语音播放副本不可用")
    length,digest=asset.get("byteLength"),asset.get("sha256")
    if type(length) is not int or not 44<=length<=MAX_BYTES or not isinstance(digest,str) or not re.fullmatch("[0-9a-f]{64}",digest):
        raise ValueError("微信语音长度或校验信息无效")
    check()
    # Use our own account-scoped localhost route. A returned contentUrl is never followed.
    conn,response=client.connect(client.base+"/media/"+quote(asset_id,safe="")+"/content","audio/wav")
    try:
        if response.getheader("Content-Type","").partition(";")[0].strip().lower()!="audio/wav":
            raise ValueError("微信语音媒体格式不符")
        raw=response.read(length+1)
    finally:
        conn.close()
    if len(raw)!=length or hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError("微信语音下载内容校验失败")
    check()
    return pcm_from_wav(raw,convert=True)
