"""Group preferences and local approvals for WeChat roster notifications."""
import json
import time

from . import admin
from .db import audit, transaction

LABELS={"join":"新人入群欢迎","leave":"退群提醒"}
SCHEMA="""
CREATE TABLE IF NOT EXISTS member_notice_settings (
 grp TEXT NOT NULL REFERENCES groups, kind TEXT NOT NULL CHECK(kind IN ('join','leave')),
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), version INTEGER NOT NULL,
 PRIMARY KEY(grp,kind)
);
CREATE TABLE IF NOT EXISTS member_notice_approvals (
 grp TEXT NOT NULL, kind TEXT NOT NULL, generation INTEGER NOT NULL, account TEXT NOT NULL,
 binding INTEGER NOT NULL, slot TEXT NOT NULL, server_id TEXT NOT NULL, approved REAL NOT NULL,
 PRIMARY KEY(grp,kind), FOREIGN KEY(grp,kind) REFERENCES member_notice_settings(grp,kind)
);
CREATE VIEW IF NOT EXISTS active_native_member_notices AS
 SELECT p.grp,p.kind,p.account,p.binding,p.generation,p.server_id,p.slot
 FROM member_notice_approvals p JOIN member_notice_settings s ON s.grp=p.grp AND s.kind=p.kind
 AND s.enabled=1 AND s.version=p.generation
 JOIN groups g ON g.id=p.grp AND g.account=p.account AND g.binding=p.binding
 JOIN node_grants n ON n.grp=p.grp AND n.account=p.account
 JOIN agent_wechat_links l ON l.grp=p.grp AND l.account=p.account AND l.slot=p.slot AND l.server_id=p.server_id
 WHERE g.paused=0 AND json_extract(g.config,'$.enabled')=1;
"""


def _context(db,group):
    row=db.execute("""SELECT g.account,g.binding,g.paused,g.config,a.mode,l.slot,l.server_id,
                    EXISTS(SELECT 1 FROM listener_nodes n WHERE n.account=g.account) listener,
                    EXISTS(SELECT 1 FROM node_grants n WHERE n.grp=g.id AND n.account=g.account) granted
                    FROM groups g JOIN account a ON a.id=g.account LEFT JOIN agent_wechat_links l
                    ON l.grp=g.id AND l.account=g.account WHERE g.id=?""",(group,)).fetchone()
    if not row:
        raise ValueError("群不存在")
    return row


def _requested(db,group,kind,ctx):
    row=db.execute("SELECT enabled,version FROM member_notice_settings WHERE grp=? AND kind=?",
                   (group,kind)).fetchone()
    if row:
        return bool(row["enabled"]),row["version"]
    return kind=="join" and not ctx["listener"],0


def active(db,group,account,binding):
    ctx=_context(db,group)
    if ctx["account"]!=account or ctx["binding"]!=binding or ctx["paused"] or not json.loads(ctx["config"])["enabled"]:
        return {}
    if ctx["listener"]:
        return {r["kind"]:r["generation"] for r in db.execute(
                "SELECT kind,generation FROM active_native_member_notices WHERE grp=? AND account=? AND binding=?",
                (group,account,binding))}
    result={}
    for kind in LABELS:
        enabled,version=_requested(db,group,kind,ctx)
        if enabled and (ctx["mode"]=="simulation" or kind=="join"):
            result[kind]=version
    return result


def _supports(ctx,kind):
    if ctx["listener"]:
        return bool(ctx["slot"] and ctx["granted"])
    return ctx["mode"]=="simulation" or kind=="join"


def settings(db,user,group):
    admin.permitted(user,group)
    ctx=_context(db,group)
    current=active(db,group,ctx["account"],ctx["binding"])
    roster=None
    if ctx["slot"] and current:
        roster=db.execute("""SELECT observed,policy FROM native_rosters WHERE grp=? AND account=? AND binding=?
                          AND slot=? AND server_id=?""",(group,ctx["account"],ctx["binding"],ctx["slot"],ctx["server_id"])).fetchone()
    included=json.loads(roster["policy"]) if roster else {}
    from .native_roster import POLL_INTERVAL
    fresh=bool(roster and 0<=time.time()-roster["observed"]<=POLL_INTERVAL*2)
    items=[]
    for kind,label in LABELS.items():
        requested,version=_requested(db,group,kind,ctx)
        supported=_supports(ctx,kind)
        if not supported:
            status="当前接入未提供此通知"
        elif not requested:
            status="已关闭"
        elif kind in current:
            status="已生效"
        elif ctx["paused"] or not json.loads(ctx["config"])["enabled"]:
            status="本群已暂停"
        else:
            status="等待本机确认"
        ready=fresh and kind in current and current[kind]==included.get(kind)
        items.append(dict(kind=kind,label=label,enabled=kind in current,requested=requested,baseline_ready=ready,
                          supported=supported,status=status,version=version))
    return dict(group=group,native=bool(ctx["slot"]),observed=roster["observed"] if roster else None,items=items)


def configure(db,user,group,data):
    admin.permitted(user,group,True)
    if user["role"] not in ("系统管理员","运营管理员"):
        raise PermissionError("FORBIDDEN 仅本群运营管理员或系统管理员可编辑成员通知")
    kind,enabled,version=(data.get(k) for k in ("kind","enabled","version"))
    if kind not in ("join","leave") or type(enabled) is not bool or type(version) is not int or version<0:
        raise ValueError("成员通知类型、开关或版本无效")
    with transaction(db):
        ctx=_context(db,group)
        if enabled and not _supports(ctx,kind):
            raise ValueError("当前接入未提供此通知")
        previous,old_version=_requested(db,group,kind,ctx)
        if old_version!=version:
            raise ValueError("CONFLICT 本项开关已变化，请刷新后重试")
        if enabled!=previous:
            db.execute("DELETE FROM member_notice_approvals WHERE grp=? AND kind=?",(group,kind))
            db.execute("""INSERT INTO member_notice_settings VALUES(?,?,?,?) ON CONFLICT(grp,kind)
                        DO UPDATE SET enabled=excluded.enabled,version=excluded.version""",
                       (group,kind,enabled,version+1))
            if not enabled:
                db.execute("""UPDATE outbox SET state='CANCELLED',body='' WHERE grp=? AND state IN ('PENDING','RETRY_WAIT')
                            AND id IN (SELECT task FROM native_member_deliveries WHERE kind=?)""",(group,kind))
                if ctx["slot"] and not db.execute(
                        "SELECT 1 FROM active_native_member_notices WHERE grp=?",(group,)).fetchone():
                    db.execute("DELETE FROM native_rosters WHERE grp=?",(group,))
                db.execute("""UPDATE outbox SET state='CANCELLED',body='' WHERE grp=? AND state IN ('PENDING','RETRY_WAIT')
                            AND biz IN (SELECT event_id FROM inbox WHERE grp=? AND kind=?)""",(group,group,kind))
                if kind=="join":
                    db.execute("DELETE FROM welcomes WHERE grp=?",(group,))
                    db.execute("""UPDATE outbox SET state='CANCELLED',body='' WHERE grp=?
                                AND state IN ('PENDING','RETRY_WAIT') AND biz LIKE 'welcome/%'""",(group,))
            audit(db,user["name"],group,"调整成员通知",LABELS[kind]+("：申请开启" if enabled and ctx["slot"]
                  else "：开启" if enabled else "：关闭"))
    return settings(db,user,group)


def preview(db,group,kind):
    if kind not in ("join","leave"):
        raise ValueError("请选择入群欢迎或退群提醒")
    ctx=_context(db,group)
    desired,version=_requested(db,group,kind,ctx)
    if not (ctx["slot"] and ctx["granted"] and desired) or ctx["paused"] or not json.loads(ctx["config"])["enabled"]:
        raise ValueError("请先在已绑定微信的群中申请开启该项通知")
    return dict(group=group,kind=kind,label=LABELS[kind],account=ctx["account"],binding=ctx["binding"],
                slot=ctx["slot"],server_id=ctx["server_id"],version=version)


def approve(db,snapshot):
    with transaction(db):
        current=preview(db,snapshot["group"],snapshot["kind"])
        if snapshot!=current:
            raise ValueError("CONFLICT 群绑定或本项通知已变化，请重新确认")
        if current["kind"] in active(db,current["group"],current["account"],current["binding"]):
            return
        generation=current["version"]+1
        args=(current["group"],current["kind"])
        db.execute("UPDATE member_notice_settings SET version=? WHERE grp=? AND kind=?",(generation,*args))
        db.execute("INSERT OR REPLACE INTO member_notice_approvals VALUES(?,?,?,?,?,?,?,?)",
                   (*args,generation,current["account"],current["binding"],current["slot"],current["server_id"],time.time()))
        audit(db,"local-cli",current["group"],"确认成员通知",LABELS[current["kind"]])
