"""Process fresh, authorized voice messages outside the SSE and SQLite write loops."""
import http.client
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

from . import speech, voice_policy
from .db import allowed, closing_db, record_failure, transaction

VERSION="agent-wechat-voice/2.7.1"
# Published v2.7.1 SHA-256 sums for the supported daemon builds.
WX_DIGESTS = {
    "win32": {"d63a9a7c1484d814c6e53b9a0f47353fcad0f7575107666ca3a9b072e28a59d5"},
    "linux": {"4bc4d57153536f35a6d98179a2439fe2435b15bbb5ba247254164b92a7f53601",
              "163443907fa6a01b0d3c4536b039c3dfaa7bffaae5450e9f45934cdb525b49f6"},
}
SCHEMA="""
CREATE TABLE IF NOT EXISTS native_voice_events(
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, account TEXT NOT NULL,
 binding INTEGER NOT NULL, generation INTEGER NOT NULL, slot TEXT NOT NULL, server_id TEXT NOT NULL,
 message_id TEXT NOT NULL, source TEXT NOT NULL, member TEXT NOT NULL, source_time REAL NOT NULL,
 state TEXT NOT NULL, seq INTEGER UNIQUE REFERENCES inbox, UNIQUE(account,source)
);
CREATE INDEX IF NOT EXISTS native_voice_pending ON native_voice_events(slot,state,id);
CREATE VIEW IF NOT EXISTS valid_voice_events AS SELECT v.* FROM native_voice_events v
 JOIN active_native_voice p ON p.grp=v.grp AND p.account=v.account AND p.binding=v.binding
 AND p.generation=v.generation AND p.server_id=v.server_id AND p.slot=v.slot AND p.approved<=v.source_time;
"""


def wake_command(text):
    match=re.match(r"^\s*二狗[\s，,。！!?？、：:]*二狗[\s，,。！!?？、：:+]*(.*)$",text,re.S)
    if match is None:
        return None
    return match[1].strip().rstrip("。！!？?")[:1800]


def capture(listener,message,stamp):
    db=listener.db
    now=time.time()
    if stamp is None or not now-120<stamp<=now+5:
        return
    if (message.get("accountId")!=listener.client.slot or message.get("threadId")!=listener.group
            or message.get("type")!=34 or message.get("direction")!="incoming" or message.get("recall")):
        return
    from .agent_wechat import number, valid_id
    sender,source=message.get("senderId"),message.get("serverId")
    if (not valid_id(sender) or sender==listener.account or not number(source) or int(source)<=0
            or not isinstance(message.get("id"),str) or not 1<=len(message["id"])<=8192):
        return
    with transaction(db):
        p=db.execute("""SELECT p.*,g.config FROM active_native_voice p JOIN groups g ON g.id=p.grp
                     WHERE p.grp=? AND p.account=? AND p.slot=? AND p.server_id=? AND p.approved<=?""",
                     (listener.group,listener.account,listener.client.slot,listener.server,stamp)).fetchone()
        if (not p or sender in json.loads(p["config"])["bots"] or
                voice_policy.active(db,listener.group,listener.account,p["binding"])!=p["generation"]):
            return
        db.execute("""INSERT OR IGNORE INTO native_voice_events(grp,account,binding,generation,slot,server_id,
                   message_id,source,member,source_time,state) VALUES(?,?,?,?,?,?,?,?,?,?,'PENDING')""",
                   (listener.group,listener.account,p["binding"],p["generation"],p["slot"],p["server_id"],
                    message["id"],source,sender,stamp))


def event_authorized(db,seq):
    row=db.execute("SELECT * FROM valid_voice_events WHERE seq=? AND state='AWAKE' AND source_time>?",
                   (seq,time.time()-120)).fetchone()
    return bool(row and voice_policy.active(db,row["grp"],row["account"],row["binding"])==row["generation"])


def input_authorized(db,row):
    return (row["source_time"]+120>time.time() and
            voice_policy.active(db,row["grp"],row["account"],row["binding"])==row["generation"] and
            db.execute("SELECT 1 FROM valid_voice_events WHERE id=? AND state='PROCESSING'",(row["id"],)).fetchone() is not None)


def reply_authorized(db,task):
    return (event_authorized(db,task["voice_seq"]) and
            db.execute("""SELECT 1 FROM outbox o JOIN inbox i ON i.event_id=o.biz
                        LEFT JOIN chat_requests q ON q.seq=i.seq
                        WHERE o.id=? AND o.attempts=? AND o.state='SENDING' AND o.expires>?
                        AND i.seq=? AND o.grp=i.grp AND o.account=i.account AND o.binding=i.binding
                        AND (q.state IS NULL OR q.state!='CANCELLED')""",
                       (task["id"],task["attempt"],time.time(),task["voice_seq"])).fetchone() is not None)


class Cancelled(Exception):
    pass


def work(db,client,private,*,fetch=None,recognize=None):
    from .agent_wechat import Client
    from .engine import receive
    from .native_voice_media import fetch_pcm
    if not db.execute("SELECT 1 FROM native_voice_events WHERE slot=? AND state='PENDING' LIMIT 1",(client.slot,)).fetchone():
        return False
    with transaction(db):
        now=time.time()
        db.execute("""UPDATE native_voice_events SET state='EXPIRED' WHERE slot=?
                   AND state IN ('PENDING','PROCESSING') AND source_time<=?""",(client.slot,now-120))
        row=db.execute("SELECT * FROM native_voice_events WHERE slot=? AND state='PENDING' ORDER BY id LIMIT 1",(client.slot,)).fetchone()
        if not row:
            return False
        db.execute("UPDATE native_voice_events SET state='PROCESSING' WHERE id=?",(row["id"],))
        if not input_authorized(db,row):
            db.execute("UPDATE native_voice_events SET state='CANCELLED' WHERE id=?",(row["id"],))
            return True
        if not allowed(db,"wx-voice/asr/"+row["grp"],12,60,now):
            db.execute("UPDATE native_voice_events SET state='RATE_LIMITED' WHERE id=?",(row["id"],))
            return True
    def check():
        if not input_authorized(db,row):
            raise Cancelled()
    stage="微信媒体凭据不可用"
    try:
        token=(private/"ergou-media-token").read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError()
        media=Client(client.port,client.slot,token)
        stage="微信语音下载或解码失败"
        if (client.get("/v1/status").get("serverId")!=row["server_id"] or client.identity()!=row["account"]
                or not client.member(row["grp"],row["account"])):
            raise Cancelled()
        check()
        pcm=(fetch or fetch_pcm)(media,row["message_id"],check)
        stage="百度语音识别失败"
        with transaction(db):
            check()
            auth=voice_policy.verified_credentials(db,row["grp"])
        text=(recognize or speech.recognize)(pcm,auth)
        command=wake_command(text)
        with transaction(db):
            check()
            if command is None:
                db.execute("UPDATE native_voice_events SET state='NOT_ADDRESSED' WHERE id=?",(row["id"],))
            else:
                seq=receive(db,row["account"],row["grp"],row["member"],row["source"],{"text":"二狗 "+command},
                            message_type="voice",adapter_version=VERSION,now=row["source_time"])
                original=db.execute("SELECT grp,member,binding,message_type,adapter_version FROM inbox WHERE seq=?",(seq,)).fetchone()
                if tuple(original)!=(row["grp"],row["member"],row["binding"],"voice",VERSION):
                    raise Cancelled()
                db.execute("UPDATE native_voice_events SET seq=?,state='AWAKE' WHERE id=?",(seq,row["id"]))
    except Cancelled:
        db.execute("UPDATE native_voice_events SET state='CANCELLED' WHERE id=? AND state='PROCESSING'",(row["id"],))
    except (OSError,http.client.HTTPException,ValueError) as exc:
        with transaction(db):
            failed=db.execute("UPDATE native_voice_events SET state='FAILED' WHERE id=? AND state='PROCESSING'",(row["id"],)).rowcount
            if failed:
                record_failure(db,row["grp"],None,"微信语音",stage)
        if failed:
            logging.getLogger(__name__).warning("微信语音处理失败：%s (%s)",stage,type(exc).__name__)
    return True


def prepare_media(db,client,private,exe):
    """Provision the media-only account token after the operator has granted voice consent."""
    from .agent_wechat import listener_lock
    with listener_lock(db,client.slot+"-voice-provision"):
        row=db.execute("SELECT * FROM active_native_voice WHERE slot=?",(client.slot,)).fetchone()
        if not row:
            return
        target=private/"ergou-media-token"
        if target.is_file() and target.stat().st_size:
            return
        if (client.get("/v1/status").get("serverId")!=row["server_id"] or client.identity()!=row["account"]
                or not client.member(row["grp"],row["account"])):
            raise ValueError("微信绑定或成员身份已变化")
        with exe.open("rb") as native:
            if hashlib.file_digest(native,"sha256").hexdigest() not in WX_DIGESTS.get(sys.platform, ()):
                raise ValueError("微信插件版本与媒体接口不符")
        result=subprocess.run([str(exe.resolve()),"--data-dir",str(private),"--server",f"http://127.0.0.1:{client.port}",
                               "--json","tokens","create","ergou-voice-media","--accounts",client.slot,"--scopes","media"],
                              capture_output=True,timeout=20)
        if result.returncode:
            raise ValueError("微信插件无法创建当前账号的媒体下载凭据")
        token=json.loads(result.stdout).get("token")
        if not isinstance(token,str) or not re.fullmatch(r"[!-~]{32,1024}",token):
            raise ValueError("微信媒体凭据返回格式无效")
        with tempfile.NamedTemporaryFile(dir=private,delete=False) as tmp:
            temp_name=tmp.name
            try:
                tmp.write(token.encode("ascii"))
                tmp.flush()
                os.fsync(tmp.fileno())
            except BaseException:
                tmp.close()
                os.unlink(temp_name)
                raise
        try:
            os.replace(temp_name,target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class Monitor:
    def __init__(self,listener,private):
        self.path=listener.db.execute("PRAGMA database_list").fetchone()[2]
        self.client,self.private=listener.client,private
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,name="wechat-voice",daemon=True)

    def run(self):
        with closing_db(self.path) as db:
            while not self.stop.is_set():
                try:
                    if work(db,self.client,self.private):
                        continue
                except (sqlite3.Error,OSError,ValueError) as exc:
                    logging.getLogger(__name__).warning("语音处理队列暂不可用 (%s)",type(exc).__name__)
                self.stop.wait(.8)
