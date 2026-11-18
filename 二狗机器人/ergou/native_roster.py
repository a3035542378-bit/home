"""Observe changes between complete, authorized native WeChat group rosters."""
import hashlib
import http.client
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from urllib.parse import quote, urlencode

from . import member_notices, member_policy
from .db import closing_db, dump, transaction


SCHEMA = """
CREATE TABLE IF NOT EXISTS native_rosters (
 grp TEXT PRIMARY KEY, slot TEXT NOT NULL, account TEXT NOT NULL, binding INTEGER NOT NULL,
 server_id TEXT NOT NULL, continuity TEXT NOT NULL, policy TEXT NOT NULL, members TEXT NOT NULL,
 observed REAL NOT NULL,
 FOREIGN KEY(slot,grp) REFERENCES agent_wechat_links(slot,grp) ON DELETE CASCADE
);
"""
LOG = logging.getLogger("ergou.native_roster")
MIN_REFRESH = 20
POLL_INTERVAL = 120


class RosterError(ValueError):
    """Contains only local diagnostics, never member names or upstream bodies."""


def stable(value, limit=160):
    return isinstance(value,str) and 0<len(value)<=limit and value.strip()==value and value.isprintable()


def is_member_event(event,group):
    data=event.get("data")
    return (event.get("kind")=="group.updated" and isinstance(data,dict) and data.get("groupId")==group
            and data.get("source")=="remote_sync_refresh" and data.get("origin")=="live"
            and data.get("membersRefreshed") is True)


def start_refresh(client,group):
    conn=http.client.HTTPConnection("127.0.0.1",client.port,timeout=8)
    try:
        path=client.base+"/groups/"+quote(group,safe="")+"/members/refresh"
        conn.request("POST",path,headers={"Authorization":"Bearer "+client.token,"Accept":"application/json"})
        response=conn.getresponse()
        if response.status!=202:
            raise RosterError(f"成员名册刷新 HTTP {response.status}")
        raw=response.read(65537)
        if len(raw)>65536:
            raise RosterError("名册刷新回执超限")
        return json.loads(raw)
    finally:
        conn.close()


class Changed(Exception):
    """The listener or authorization changed during the read."""


def fetch_snapshot(client,group,account,check,start=start_refresh,wait=time.sleep):
    check()
    op=start(client,group)
    opid=op.get("id") if isinstance(op,dict) else None
    if not stable(opid):
        raise RosterError("缺少名册刷新操作 ID")
    deadline=time.monotonic()+125
    while True:
        check()
        if (not isinstance(op,dict) or op.get("id")!=opid or op.get("accountId")!=client.slot
                or op.get("kind")!="metadata"):
            raise RosterError("名册刷新回执身份不符")
        if op.get("state")=="succeeded":
            break
        if op.get("state") not in ("queued","running") or time.monotonic()>=deadline:
            raise RosterError("名册刷新未完成")
        wait(1)
        check()
        op=client.get(client.base+"/operations/"+quote(opid,safe=""))
    result=op.get("result")
    if not isinstance(result,dict) or result.get("completeRoster") is not True:
        raise RosterError("上游未确认完整成员名册")
    count=result.get("memberCount")
    if type(count) is not int or not 1<=count<=10000:
        raise RosterError("名册刷新人数无效")
    members,seen={},set()
    cursor=version=None
    while True:
        check()
        params={"limit":200}
        if cursor:
            params["cursor"]=cursor
        page=client.get(client.base+"/groups/"+quote(group,safe="")+"/members?"+urlencode(params))
        generation,asof=page.get("sourceGeneration"),page.get("asOfEventCursor")
        coverage=page.get("coverage")
        if (not stable(generation,1024) or not isinstance(asof,str) or not asof.isascii() or not asof.isdecimal()
                or not isinstance(coverage,dict) or coverage.get("partial") is not False
                or not isinstance(page.get("items"),list) or "nextCursor" not in page):
            raise RosterError("成员分页快照不完整")
        if version is not None and version!=(generation,asof):
            raise RosterError("分页期间成员名册版本发生变化")
        version=(generation,asof)
        for item in page["items"]:
            uid=item.get("id") if isinstance(item,dict) else None
            if not stable(uid) or item.get("username")!=uid or uid in members:
                raise RosterError("成员记录重复、已删除或身份无效")
            # displayName can contain a private contact remark. Use only group/public names.
            label=next((item[k] for k in ("roomDisplayName","nickname") if isinstance(item.get(k),str)
                        and item[k].strip()),None)
            members[uid]=" ".join(label.split())[:80] if label else "一位群成员"
        cursor=page["nextCursor"]
        if cursor is None:
            break
        if (not stable(cursor,8192) or cursor in seen or len(seen)>=100 or not page["items"]
                or len(members)>=count or time.monotonic()>=deadline):
            raise RosterError("成员分页游标无效")
        seen.add(cursor)
    if len(members)!=count or account not in members:
        raise RosterError("名册人数或当前账号校验失败")
    return opid,members


def apply_snapshot(db,group,account,binding,server_id,continuity,policy,operation,members,now):
    with transaction(db):
        link=db.execute("""SELECT l.slot,g.* FROM agent_wechat_links l JOIN groups g ON g.id=l.grp AND g.account=l.account
                         WHERE l.grp=? AND l.account=? AND l.server_id=? AND g.binding=?""",
                        (group,account,server_id,binding)).fetchone()
        if not link or not policy or policy!=member_policy.active(db,group,account,binding):
            return False
        last=db.execute("SELECT * FROM native_rosters WHERE grp=?",(group,)).fetchone()
        if (last and (last["account"],last["binding"],last["server_id"],last["continuity"])==
                (account,binding,server_id,continuity) and 0<=now-last["observed"]<=POLL_INTERVAL*2):
            previous=json.loads(last["members"])
            old_policy=json.loads(last["policy"])
            for kind,names,other in (("join",members,previous),("leave",previous,members)):
                if kind not in policy or policy[kind]!=old_policy.get(kind):
                    continue
                for uid in sorted(names.keys()-other.keys()):
                    raw=dump([group,account,binding,server_id,operation,kind,uid])
                    key="member/"+kind+"/"+hashlib.sha256(raw.encode()).hexdigest()
                    member_notices.enqueue(db,link,kind,uid,names[uid],key,now)
        db.execute("INSERT OR REPLACE INTO native_rosters VALUES(?,?,?,?,?,?,?,?,?)",
                   (group,link["slot"],account,binding,server_id,continuity,dump(policy),dump(members),now))
    return True


class Monitor:
    def __init__(self,listener):
        self.path=listener.db.execute("PRAGMA database_list").fetchone()[2]
        self.client,self.group,self.account,self.server=listener.client,listener.group,listener.account,listener.server
        self.changed=threading.Condition()
        self.session=None
        self.signal=0
        self.stopped=False
        self.thread=threading.Thread(target=self.run,name="wechat-member-roster",daemon=True)

    def online(self):
        with self.changed:
            if self.session is None:
                self.session=uuid.uuid4().hex
                self.changed.notify_all()

    def offline(self):
        with self.changed:
            self.session=None
            self.changed.notify_all()

    def signal_event(self,event):
        if is_member_event(event,self.group):
            with self.changed:
                self.signal+=1
                self.changed.notify_all()

    def close(self):
        with self.changed:
            self.session=None
            self.stopped=True
            self.changed.notify_all()
        self.thread.join(timeout=10)

    def policy(self,db):
        row=db.execute("""SELECT g.binding FROM groups g JOIN agent_wechat_links l ON l.grp=g.id AND l.account=g.account
                       WHERE g.id=? AND g.account=? AND l.server_id=? AND l.slot=?""",
                       (self.group,self.account,self.server,self.client.slot)).fetchone()
        return (row[0],member_policy.active(db,self.group,self.account,row[0])) if row else (None,{})

    def run(self):
        with closing_db(self.path) as db:
            previous=None
            last_refresh=-POLL_INTERVAL
            interval=POLL_INTERVAL
            while True:
                with self.changed:
                    if self.stopped:
                        return
                    if not self.session:
                        self.changed.wait(4)
                        continue
                    session,signal=self.session,self.signal
                try:
                    binding,policy=self.policy(db)
                    state=(session,signal,binding,policy)
                    now=time.monotonic()
                    gap=MIN_REFRESH if previous!=state else interval
                    if policy and now-last_refresh>=gap:
                        last_refresh=now
                        previous=state
                        interval=POLL_INTERVAL
                        def check():
                            with self.changed:
                                if self.session!=session or self.stopped:
                                    raise Changed()
                            if self.policy(db)!=(binding,policy):
                                raise Changed()
                        def verify():
                            check()
                            if (self.client.get("/v1/status").get("serverId")!=self.server
                                    or self.client.identity()!=self.account):
                                raise RosterError("名册服务或账号已改变")
                        verify()
                        operation,members=fetch_snapshot(self.client,self.group,self.account,check)
                        verify()
                        with self.changed:
                            if self.session==session:
                                apply_snapshot(db,self.group,self.account,binding,self.server,session,policy,
                                               operation,members,time.time())
                    elif not policy and previous is not None:
                        db.execute("DELETE FROM native_rosters WHERE grp=?",(self.group,))
                        previous=None
                except Changed:
                    pass
                except (ValueError,OSError,http.client.HTTPException,sqlite3.Error) as exc:
                    interval=45
                    public_reason=isinstance(exc,RosterError) or re.fullmatch(r"Agent WeChat HTTP [1-5][0-9]{2}",str(exc))
                    LOG.warning("群成员名册暂时无法核实，将重试（%s）",str(exc) if public_reason else type(exc).__name__)
                with self.changed:
                    if not self.stopped:
                        self.changed.wait(3)
