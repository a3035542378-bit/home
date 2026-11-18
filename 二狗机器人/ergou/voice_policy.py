"""Group-scoped Baidu credentials and local consent for native group voice."""
import base64
from dataclasses import dataclass
import hashlib
import json
import os
import re
import secrets
import time

from . import admin, models, speech
from .db import allowed, audit, dump, transaction


SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_settings(
 grp TEXT PRIMARY KEY REFERENCES groups, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_credentials(
 grp TEXT PRIMARY KEY REFERENCES groups, kind TEXT NOT NULL CHECK(kind IN ('key','token')),
 sealed BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_verifications(
 grp TEXT PRIMARY KEY REFERENCES groups, source TEXT NOT NULL CHECK(source IN ('group','environment')),
 fingerprint BLOB NOT NULL, verified_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_test_tickets(
 digest BLOB PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, actor TEXT NOT NULL, snapshot TEXT NOT NULL,
 origin TEXT NOT NULL CHECK(origin IN ('new','group','environment')), kind TEXT NOT NULL,
 fingerprint BLOB NOT NULL, sealed BLOB, expires REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS voice_ticket_expiry ON voice_test_tickets(expires);
CREATE TABLE IF NOT EXISTS voice_approvals(
 grp TEXT PRIMARY KEY REFERENCES voice_settings, generation INTEGER NOT NULL, account TEXT NOT NULL,
 binding INTEGER NOT NULL, slot TEXT NOT NULL, server_id TEXT NOT NULL, approved REAL NOT NULL
);
CREATE VIEW IF NOT EXISTS active_native_voice AS
 SELECT p.grp,p.account,p.binding,p.slot,p.server_id,p.generation,p.approved
 FROM voice_approvals p JOIN voice_settings s ON s.grp=p.grp AND s.version=p.generation AND s.enabled=1
 JOIN groups g ON g.id=p.grp AND g.account=p.account AND g.binding=p.binding
 JOIN node_grants n ON n.grp=p.grp AND n.account=p.account
 JOIN agent_wechat_links l ON l.grp=p.grp AND l.account=p.account AND l.slot=p.slot AND l.server_id=p.server_id
 WHERE g.paused=0 AND json_extract(g.config,'$.enabled')=1;
"""


def _context(db, group):
    row=db.execute("""SELECT g.id,g.account,g.binding,g.paused,g.config,a.mode,l.slot,l.server_id,
        COALESCE(s.enabled,0) requested,COALESCE(s.version,0) version,
        EXISTS(SELECT 1 FROM node_grants n WHERE n.grp=g.id AND n.account=g.account) granted,
        (SELECT kind FROM voice_credentials WHERE grp=g.id) credential_kind
        FROM groups g JOIN account a ON a.id=g.account LEFT JOIN voice_settings s ON s.grp=g.id
        LEFT JOIN agent_wechat_links l ON l.grp=g.id AND l.account=g.account WHERE g.id=?""",(group,)).fetchone()
    if not row:
        raise ValueError("群不存在")
    return row


@dataclass(frozen=True)
class _Credential:
    source: str
    kind: str
    material: bytes # DPAPI blob for a group credential, process-local bytes for an environment credential.

    @property
    def fingerprint(self):
        return hashlib.sha256(self.kind.encode("ascii")+b"\0"+self.material).digest()

    def auth(self):
        raw=models.protect(self.material,True) if self.source=="group" else self.material
        try:
            value=raw.decode("ascii")
        except UnicodeError:
            raise ValueError("本群百度凭据解密失败，请重新配置") from None
        return (value,"") if self.kind=="key" else ("",value)


def _current_credential(db,group):
    row=db.execute("SELECT kind,sealed FROM voice_credentials WHERE grp=?",(group,)).fetchone()
    if row:
        return _Credential("group",row["kind"],row["sealed"])
    key=os.environ.get("ERGOU_BAIDU_SPEECH_KEY","").strip()
    value=key or os.environ.get("ERGOU_BAIDU_SPEECH_TOKEN","").strip()
    if value and re.fullmatch(r"[!-~]{1,4096}",value):
        return _Credential("environment","key" if key else "token",value.encode("ascii"))
    return None


def credentials(db,group):
    candidate=_current_credential(db,group)
    if not candidate:
        raise ValueError("百度语音服务凭据尚未配置或格式无效")
    return candidate.auth()


def _verification(db,group,candidate):
    if candidate:
        return db.execute("SELECT verified_at FROM voice_verifications WHERE grp=? AND source=? AND fingerprint=?",
                          (group,candidate.source,candidate.fingerprint)).fetchone()


def verified_credentials(db,group):
    candidate=_current_credential(db,group)
    if not _verification(db,group,candidate):
        raise ValueError("本群百度语音凭据需要测试并启用")
    return candidate.auth()


def active(db,group,account,binding):
    row=db.execute("""SELECT p.generation
                   FROM active_native_voice p WHERE p.grp=? AND p.account=? AND p.binding=?""",(group,account,binding)).fetchone()
    return row["generation"] if row and _verification(db,group,_current_credential(db,group)) else None


def settings(db,user,group):
    admin.permitted(user,group)
    row=_context(db,group)
    approved=bool(db.execute("SELECT 1 FROM active_native_voice WHERE grp=?",(group,)).fetchone())
    candidate=_current_credential(db,group)
    source=candidate.source if candidate else "missing"
    verified=_verification(db,group,candidate)
    if row["mode"]=="simulation":
        status="模拟群可手动上传测试录音"
    elif not row["slot"] or not row["granted"]:
        status="当前绑定未接入微信语音插件"
    elif not row["requested"]:
        status="已关闭"
    elif row["paused"] or not json.loads(row["config"])["enabled"]:
        status="本群已暂停"
    elif not approved:
        status="等待本机确认"
    elif source=="missing":
        status="已确认，等待百度凭据"
    elif not verified:
        status="已确认，等待测试并启用凭据"
    else:
        status="语音唤醒已启用，百度凭据已通过测试"
    return dict(group=group,version=row["version"],native=bool(row["slot"] and row["granted"]),
                requested=bool(row["requested"]),approved=approved,enabled=approved and bool(verified),
                credential_source=source,credential_kind=row["credential_kind"],credential_verified=bool(verified),
                verified_at=verified["verified_at"] if verified else None,status=status)


def _cancel_pending(db,group):
    # Keep completed receipts intact. A claimed send still needs its final receipt.
    db.execute("""UPDATE native_voice_events SET state='CANCELLED'
                  WHERE grp=? AND (state IN ('PENDING','PROCESSING') OR (state='AWAKE' AND seq IN (
                    SELECT i.seq FROM inbox i
                    LEFT JOIN queries q ON q.id=i.seq LEFT JOIN chat_requests c ON c.seq=i.seq
                    LEFT JOIN outbox o ON o.biz=i.event_id
                    WHERE i.grp=? AND (i.state='PENDING' OR q.state IN ('PENDING','RUNNING')
                      OR c.state IN ('PENDING','RUNNING') OR o.state IN ('PENDING','SENDING','RETRY_WAIT')))))""",
               (group,group))
    scope="""SELECT seq FROM native_voice_events WHERE grp=:group AND state='CANCELLED' AND seq IS NOT NULL
             UNION ALL SELECT c.seq FROM chat_voice_context c JOIN inbox i ON i.seq=c.seq WHERE i.grp=:group"""
    args={"group":group}
    db.execute(f"""UPDATE inbox SET state='IGNORED',payload=NULL,result='群语音配置已变化'
                   WHERE state='PENDING' AND seq IN ({scope})""",args)
    db.execute(f"""UPDATE queries SET state='CANCELLED',argument=NULL,result=NULL
                   WHERE state IN ('PENDING','RUNNING') AND id IN ({scope})""",args)
    db.execute(f"""UPDATE chat_requests SET state='CANCELLED',prompt=NULL
                   WHERE state IN ('PENDING','RUNNING') AND seq IN ({scope})""",args)
    db.execute(f"""UPDATE outbox SET body='',state=CASE WHEN state='SENDING' THEN state ELSE 'CANCELLED' END,
                   detail=CASE WHEN state='SENDING' THEN detail ELSE '群语音配置已变化' END
                   WHERE state IN ('PENDING','RETRY_WAIT','SENDING') AND biz IN
                     (SELECT event_id FROM inbox WHERE seq IN ({scope}))""",args)
    db.execute(f"DELETE FROM local_turns WHERE seq IN ({scope})",args)


def _operator(user,group):
    admin.permitted(user,group,True)
    if user["role"] not in ("系统管理员","运营管理员"):
        raise PermissionError("FORBIDDEN 仅本群运营管理员或系统管理员可配置语音")


def _expected(db,group,version):
    if type(version) is not int or version<0:
        raise ValueError("语音配置版本无效")
    row=_context(db,group)
    if row["version"]!=version:
        raise ValueError("CONFLICT 本群语音设置已更新，请刷新")
    return row


def _snapshot(row):
    return dump([row[k] for k in ("version","account","binding","slot","server_id","granted","paused","mode")]+
                [json.loads(row["config"])["enabled"]])


def test_credential(db,user,group,data):
    """Verify an operator-supplied recording without submitting it to the group's message queue."""
    from .native_voice import wake_command
    _operator(user,group)
    version=data.get("version")
    snapshot=_snapshot(_expected(db,group,version))
    pcm=speech._pcm(data.get("audio"))
    secret=data.get("secret","")
    if secret=="":
        candidate=_current_credential(db,group)
        if not candidate:
            raise ValueError("请填写要测试的百度官方凭据")
        origin=candidate.source
    else:
        kind=data.get("kind")
        if kind not in ("key","token") or not isinstance(secret,str) or not re.fullmatch(r"[!-~]{1,4096}",secret):
            raise ValueError("请选择百度凭据类型并填写官方完整凭据")
        candidate=_Credential("group",kind,models.protect(secret.encode("ascii")))
        origin="new"
    auth=candidate.auth()

    def current():
        if (_snapshot(_expected(db,group,version))!=snapshot or
                (origin!="new" and candidate!=_current_credential(db,group))):
            raise ValueError("CONFLICT 群绑定或所选凭据已变化，请重新测试")

    with transaction(db):
        current()
        now=time.time()
        db.execute("DELETE FROM voice_test_tickets WHERE expires<=?",(now,))
        if not allowed(db,"voice-credential-test/"+group,8,60,now):
            raise ValueError("RATE_LIMITED 本群语音测试过于频繁，请稍后重试")
    transcript=speech.recognize(pcm,auth)
    command=wake_command(transcript)
    if not command:
        return dict(transcript=transcript,reply="",audio="",mime="",ticket=None)
    current()
    reply="汪，我听到了！二狗的语音识别和合成测试成功。"
    try:
        wav=speech.synthesize_wav(reply,auth)
    except ValueError:
        return dict(transcript=transcript,reply=reply,audio="",mime="",ticket=None,
                    error="百度语音合成测试失败，请核对合成权限、凭据和额度后重试")
    ticket=secrets.token_urlsafe(32)
    with transaction(db):
        current()
        db.execute("DELETE FROM voice_test_tickets WHERE grp=? AND actor=?",(group,user["name"]))
        db.execute("""INSERT INTO voice_test_tickets
                   (digest,grp,actor,snapshot,origin,kind,fingerprint,sealed,expires)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                   (hashlib.sha256(ticket.encode("ascii")).digest(),group,user["name"],snapshot,origin,
                    candidate.kind,candidate.fingerprint,candidate.material if origin=="new" else None,time.time()+600))
    return dict(transcript=transcript,reply=reply,audio=base64.b64encode(wav).decode("ascii"),mime="audio/wav",ticket=ticket)


def _activate(db,user,group,row,ticket):
    if not isinstance(ticket,str) or not re.fullmatch("[a-zA-Z0-9_-]{43}",ticket):
        raise ValueError("请先完成本群语音测试并试听")
    tested=db.execute("""SELECT * FROM voice_test_tickets WHERE digest=? AND grp=? AND actor=?
                         AND snapshot=? AND expires>?""",
                      (hashlib.sha256(ticket.encode("ascii")).digest(),group,user["name"],_snapshot(row),time.time())).fetchone()
    if not tested:
        raise ValueError("CONFLICT 测试结果已失效，请在本群重新测试")
    if tested["origin"]=="new":
        candidate=_Credential("group",tested["kind"],tested["sealed"])
        db.execute("INSERT OR REPLACE INTO voice_credentials VALUES(?,?,?)",(group,candidate.kind,candidate.material))
    else:
        candidate=_current_credential(db,group)
        if not candidate or candidate.source!=tested["origin"]:
            raise ValueError("CONFLICT 待启用凭据已变化，请重新测试")
    if candidate.fingerprint!=tested["fingerprint"]:
        raise ValueError("CONFLICT 待启用凭据已变化，请重新测试")
    db.execute("INSERT OR REPLACE INTO voice_verifications VALUES(?,?,?,?)",
               (group,candidate.source,candidate.fingerprint,time.time()))


def configure(db,user,group,data):
    _operator(user,group)
    version=data.get("version")
    action=data.get("action")
    if action=="credential":
        raise ValueError("请先用测试录音验证百度凭据，再启用到本群")
    if action not in ("switch","activate","clear"):
        raise ValueError("语音配置操作无效")
    with transaction(db):
        row=_expected(db,group,version)
        enabled=bool(row["requested"])
        if action=="switch":
            value=data.get("enabled")
            if type(value) is not bool or (value and not (row["slot"] and row["granted"])):
                raise ValueError("当前绑定不支持微信群语音唤醒")
            if value==enabled:
                return settings(db,user,group)
            enabled=value
            db.execute("DELETE FROM voice_approvals WHERE grp=?",(group,))
            detail="申请开启" if enabled else "关闭"
        elif action=="activate":
            _activate(db,user,group,row,data.get("ticket"))
            detail="识别与合成测试通过，启用本群百度凭据"
        else:
            db.execute("DELETE FROM voice_credentials WHERE grp=?",(group,))
            db.execute("DELETE FROM voice_verifications WHERE grp=?",(group,))
            detail="移除本群百度凭据"
        db.execute("DELETE FROM voice_test_tickets WHERE grp=? OR expires<=?",(group,time.time()))
        db.execute("""INSERT INTO voice_settings VALUES(?,?,?) ON CONFLICT(grp)
                    DO UPDATE SET enabled=excluded.enabled,version=excluded.version""",(group,enabled,version+1))
        _cancel_pending(db,group)
        if action!="switch":
            # Rotation fences earlier jobs and restarts the freshness window.
            db.execute("""UPDATE voice_approvals SET generation=?,approved=? WHERE grp=? AND generation=?
                AND account=? AND binding=? AND slot=? AND server_id=?""",
                (version+1,time.time(),group,version,row["account"],row["binding"],row["slot"],row["server_id"]))
        audit(db,user["name"],group,"配置群语音",detail)
    return settings(db,user,group)


def preview(db,group):
    row=_context(db,group)
    if not row["requested"] or not row["slot"] or not row["granted"] or row["paused"] or not json.loads(row["config"])["enabled"]:
        raise ValueError("请先在已绑定微信的群中申请语音唤醒")
    return dict(group=group,account=row["account"],binding=row["binding"],slot=row["slot"],
                server_id=row["server_id"],version=row["version"])


def approve(db,snapshot):
    with transaction(db):
        row=preview(db,snapshot["group"])
        if row!=snapshot:
            raise ValueError("CONFLICT 语音设置或微信绑定已变化，请重新核对")
        if db.execute("SELECT 1 FROM active_native_voice WHERE grp=?",(row["group"],)).fetchone():
            return
        generation=row["version"]+1
        db.execute("UPDATE voice_settings SET version=? WHERE grp=?",(generation,row["group"]))
        db.execute("INSERT OR REPLACE INTO voice_approvals VALUES(?,?,?,?,?,?,?)",
                   (row["group"],generation,row["account"],row["binding"],row["slot"],row["server_id"],time.time()))
        audit(db,"local-cli",row["group"],"确认群语音","向百度识别本群新语音，双唤醒词触发语音回复")


def confirm_one(db):
    options=[]
    rows=db.execute("""SELECT s.grp,p.alias FROM voice_settings s LEFT JOIN group_profile p ON p.grp=s.grp
                       WHERE s.enabled=1 AND NOT EXISTS(SELECT 1 FROM active_native_voice a WHERE a.grp=s.grp)
                       ORDER BY s.grp""").fetchall()
    for group,alias in rows:
        try:
            snapshot=preview(db,group)
        except ValueError:
            continue
        options.append(snapshot)
        print(f"{len(options)}. {alias or group}（{group}）")
    if not options:
        print("没有等待确认的语音开关。请先在运营后台「语音唤醒」中申请开启。")
        return
    raw=input("输入目标群的编号，或回车退出：").strip()
    if not raw:
        return
    if not re.fullmatch(r"[1-9][0-9]{0,5}",raw) or int(raw)>len(options):
        raise ValueError("请选择列表中的目标群")
    snapshot=options[int(raw)-1]
    print(f"目标微信群：{snapshot['group']}\n启用后，本群收到的 60 秒以内的新语音会交给百度识别。以“二狗二狗”开头的指令按本群聊天设置处理，回答由百度合成并发回该群。百度可能按量收费。")
    if input("同意以上范围请输入「确认启用」：").strip()=="确认启用":
        approve(db,snapshot)
        print("已记录本群语音授权。")
    else:
        print("已取消。")
