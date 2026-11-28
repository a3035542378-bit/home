"""One-group, receive-only Agent WeChat event consumer."""
import argparse
import asyncio
from contextlib import contextmanager
import errno
import hashlib
import http.client
import json
import logging
import os
from datetime import datetime
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import quote, urlencode

from . import bridge, jobs
from .db import audit, closing_db, dump, initialize, transaction

VERSION = "agent-wechat-events/2.7.1"
LOG = logging.getLogger("ergou.agent_wechat")


class CursorExpired(ValueError):
    pass


class LinkRemoved(Exception):
    """The operator unbound this listener while it held its process lock."""


def valid_id(value):
    return isinstance(value, str) and 0 < len(value) <= 160 and value.strip() == value


def mentions_account(message,account):
    mentions=message.get("mentions")
    return (isinstance(mentions,dict) and mentions.get("state")=="known" and mentions.get("self") is True
            and mentions.get("all") is not True and isinstance(mentions.get("userIds"),list)
            and account in mentions["userIds"])


def number(value):
    return isinstance(value, str) and 0 < len(value) <= 20 and value.isascii() and value.isdecimal()


class ListenerBusy(RuntimeError):
    """Another process owns this slot."""


def listener_lock_path(db, slot):
    path = next(row[2] for row in db.execute("PRAGMA database_list") if row[1] == "main")
    if not path:
        raise ValueError("监听进程需要持久化数据库")
    key = hashlib.sha256(slot.encode()).hexdigest()[:24]
    database = Path(path).resolve()
    return database.with_name(f"{database.name}.{key}.lock")


@contextmanager
def listener_lock(db, slot):
    """Keep one consumer per database and slot. Process exit releases the OS lock."""
    lock_path = listener_lock_path(db,slot)
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN) or getattr(exc, "winerror", None) == 33:
                raise ListenerBusy("该槽位已有监听进程") from exc
            raise
        yield handle


class Client:
    def __init__(self, port, slot, token):
        self.port, self.slot, self.token = port, slot, token
        self.base = "/v1/accounts/" + quote(slot, safe="")

    def connect(self, path, accept):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=35 if accept == "text/event-stream" else 8)
        try:
            conn.request("GET", path, headers={"Authorization": "Bearer " + self.token, "Accept": accept})
            response = conn.getresponse()
            if response.status != 200:
                if response.status == 410 and path.split("?")[0] in (self.base + "/events", self.base + "/events/stream"):
                    raw = response.read(4096)
                    try:
                        error = json.loads(raw)
                    except (ValueError, UnicodeError):
                        error = {}
                    detail = error.get("error") if isinstance(error, dict) else None
                    if isinstance(detail, dict) and detail.get("code") == "event_cursor_expired":
                        raise CursorExpired("上游事件游标已过期")
                raise ConnectionError(f"Agent WeChat HTTP {response.status}")
            return conn, response
        except BaseException:
            conn.close()
            raise

    def get(self, path):
        conn, response = self.connect(path, "application/json")
        try:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("本机 JSON 响应过大")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("本机 API 响应格式错误")
            return result
        finally:
            conn.close()

    def events(self, after):
        conn, response = self.connect(self.base + "/events/stream?" + urlencode({"after": after}), "text/event-stream")
        try:
            if response.getheader("Content-Type", "").split(";")[0] != "text/event-stream":
                raise ValueError("未收到 SSE 事件流")
            parts, size = [], 0
            while True:
                line = response.readline(65537)
                if not line:
                    raise ConnectionError("事件流已断开")
                size += len(line)
                if len(line) > 65536 or size > 262144:
                    raise ValueError("事件帧过大")
                line = line.rstrip(b"\r\n")
                if line.startswith(b"data:"):
                    parts.append(line[5:].lstrip(b" "))
                elif not line:
                    frame = json.loads(b"\n".join(parts)) if parts else None
                    if frame is not None:
                        if not isinstance(frame, dict):
                            raise ValueError("无效的 SSE 事件")
                        detail = frame.get("error")
                        if isinstance(detail, dict) and detail.get("code") == "event_cursor_expired":
                            raise CursorExpired("上游事件游标已过期")
                    yield frame
                    parts, size = [], 0
        finally:
            conn.close()

    def identity(self):
        s = self.get(self.base)
        if (s.get("id") != self.slot or s.get("authenticated") is not True or s.get("connection") != "online"
                or not valid_id(s.get("ownUsername"))):
            raise ValueError("账号未登录或未上线")
        return s["ownUsername"]

    def member(self, group, account):
        path = self.base + "/groups/" + quote(group, safe="")
        room = self.get(path)
        if room.get("id") != group or room.get("isInGroup") is False:
            return False
        if room.get("isInGroup") is True:
            return True
        entry = self.get(path + "/members/" + quote(account, safe=""))
        return (entry.get("state") == "present" and entry.get("username") == account
                and entry.get("groupId") == group and isinstance(entry.get("member"), dict)
                and account in (entry["member"].get("id"), entry["member"].get("username")))

    def resolve(self, name):
        page = self.get(self.base + "/groups?" + urlencode({"search": name, "limit": 200}))
        if page.get("nextCursor") or page.get("coverage", {}).get("partial") is not False:
            raise ValueError("群资料不完整，无法唯一匹配")
        ids = {g["id"] for g in page["items"] if valid_id(g.get("id")) and g["id"].endswith("@chatroom")
               and name in (g["id"], g.get("displayName"), g.get("name"))}
        if len(ids) != 1 or not number(page.get("asOfEventCursor")):
            raise ValueError("群名未唯一匹配或缺少事件位置")
        return ids.pop(), page["asOfEventCursor"]

    def next_events(self, after):
        page = self.get(self.base + "/events?" + urlencode({"after": str(after), "limit": 1}))
        if not isinstance(page.get("items"), list):
            raise ValueError("上游事件分页无效")
        return page["items"]


def link(db, client, name, secret, after=None):
    if not valid_id(name):
        raise ValueError("需要完整群名")
    account = client.identity()
    group, current = client.resolve(name)
    server = client.get("/v1/status").get("serverId")
    if not valid_id(server) or not client.member(group, account):
        raise ValueError("未确认服务身份或当前账号的群成员关系")
    if after is not None and (not number(after) or int(after) > int(current)):
        raise ValueError("指定的起始事件位置无效")
    existing = db.execute("SELECT * FROM agent_wechat_links WHERE account=? OR slot=?", (account, client.slot)).fetchall()
    if any((r["account"],r["grp"],r["server_id"],r["slot"]) != (account,group,server,client.slot) for r in existing):
        raise ValueError("该账号或槽位已绑定其他群或服务")
    bound = db.execute("SELECT account FROM groups WHERE id=?", (group,)).fetchone()
    if bound and bound[0] != account:
        raise ValueError("群已绑定其他账号")
    bridge.enroll(db, account, group, secret, listen_only=True)
    db.execute("INSERT OR IGNORE INTO agent_wechat_links VALUES(?,?,?,?,?)",
               (client.slot, account, group, server, after or current))


class Listener:
    def __init__(self, db, client, secret, private=None, *, group=None):
        self.db, self.client, self.secret = db, client, secret
        self.private = private
        if group is None and db.execute("SELECT 1 FROM agent_wechat_links WHERE slot=? LIMIT 1 OFFSET 1",
                                        (client.slot,)).fetchone():
            raise ValueError("多群账号请使用服务器群路由")
        row = db.execute("SELECT * FROM agent_wechat_links WHERE slot=? AND (? IS NULL OR grp=?)", (client.slot,group,group)).fetchone()
        if not row:
            raise ValueError("请先登记目标群")
        self.account, self.group, self.server, self.cursor = (row[k] for k in ("account","grp","server_id","cursor"))

    def linked(self):
        return self.db.execute("""SELECT 1 FROM agent_wechat_links WHERE slot=? AND grp=? AND account=? AND server_id=?""",
                               (self.client.slot,self.group,self.account,self.server)).fetchone() is not None

    def heartbeat(self, state):
        reply = bridge.endpoint(self.db, "heartbeat", self.secret, {
            "state": state, "actual_account": self.account if state == "LISTENING" else "",
            "groups": [self.group] if state == "LISTENING" else [], "adapter_version": VERSION,
            "capabilities": {"receive": True, "send": False, "stable_ids": True},
        })
        if reply["state"] != state:
            raise ValueError("本机节点未通过身份验证")

    def verify(self):
        if not self.linked():
            raise LinkRemoved()
        if (self.client.get("/v1/status").get("serverId") != self.server or self.client.identity() != self.account
                or not self.client.member(self.group, self.account)):
            raise ValueError("服务、账号或群成员身份已改变")
        self.heartbeat("LISTENING")

    def consume(self, event, message=None):
        cursor = event.get("cursor")
        if not number(cursor) or event.get("accountId", self.client.slot) != self.client.slot:
            raise ValueError("事件账号或游标错误")
        if int(cursor) <= int(self.cursor):
            return
        sequence = None
        data = event.get("data") or {}
        if event.get("kind") == "message.committed" and not isinstance(data, dict):
            raise ValueError("消息事件缺少结构化信息")
        if (event.get("kind") == "message.committed" and data.get("threadId") == self.group
                and data.get("origin") == "live" and data.get("direction") in (None, "incoming")):
            mid = data.get("messageId")
            if not isinstance(mid, str) or not 0 < len(mid) <= 8192:
                raise ValueError("缺少上游消息标识")
            if not self.linked():
                raise LinkRemoved()
            if message is None:
                message = self.client.get(self.client.base + "/messages/" + quote(mid, safe=""))
            if (message.get("threadId"), message.get("accountId"), message.get("id")) != (self.group, self.client.slot, mid):
                raise ValueError("事件与消息详情身份不符")
            sender, source = message.get("senderId"), message.get("serverId")
            payload = {"text": message.get("body")}
            mentions = message.get("mentions") or {}
            if mentions_account(message,self.account):
                payload["mention_account"]=self.account
            try:
                stamp=datetime.fromisoformat(message["createdAt"])
                if stamp.tzinfo:
                    payload["source_time"]=stamp.timestamp()
            except (ValueError,TypeError,KeyError,OverflowError):
                pass
            if message.get("type")==34:
                from .native_voice import capture
                capture(self,message,payload.get("source_time"))
            from .engine import addressed_command, group_prefix
            prefix = group_prefix(self.db, self.group)
            if (message.get("direction") == "incoming" and message.get("type") == 1 and not message.get("recall")
                    and valid_id(sender) and sender != self.account and number(source) and int(source) > 0
                    and isinstance(payload["text"], str)
                    and (payload["text"].startswith((prefix,"二狗")) or "mention_account" in payload)
                    and len(dump(payload).encode()) <= 8192):
                cmd=addressed_command(payload["text"],prefix,payload.get("mention_account")==self.account,native=True)
                from . import roles,wechat_roles,models
                if payload.get("mention_account") and models.api_first(self.db,self.group):
                    cmd=None
                if cmd and roles.owner(self.db,self.account) and (roles.parse(cmd) or roles.GAME_CONTROL.fullmatch(cmd)):
                    wechat_roles.refresh_owner(self.db,self.client,self.account,self.group)
                    target=wechat_roles.target_member(self.db,self.client,self.account,self.group,message)
                    if target:
                        payload["role_target"]=target
                    ids=mentions.get("userIds",[]) if isinstance(mentions,dict) else []
                    if isinstance(ids,list) and any(uid!=self.account for uid in ids) and not target:
                        payload["invalid_role_target"]=True
                from . import jianghu
                if (cmd in jianghu.SWITCHES or (cmd and cmd.startswith("赐金条"))) and roles.owner(self.db,self.account):
                    wechat_roles.refresh_owner(self.db,self.client,self.account,self.group)
                if cmd and (jianghu.DUEL.fullmatch(cmd) or jianghu.jianghu_world.society.TARGET.fullmatch(cmd)) and jianghu.enabled(self.db,self.group):
                    payload["duel_target"]=wechat_roles.target_member(self.db,self.client,self.account,self.group,message)
                if cmd and cmd.startswith(("赞美","送礼")):
                    try:
                        target=wechat_roles.target_member(self.db,self.client,self.account,self.group,message)
                    except (OSError,ValueError,RuntimeError,http.client.HTTPException):
                        target=None
                        payload["social_lookup_failed"]=True
                    if target:
                        payload.update(social_target=target,social_group=self.group)
                from .pond_raids import TARGET
                if (cmd and (TARGET.fullmatch(cmd.strip()) or cmd == "偷鱼")
                        and isinstance(mentions,dict) and mentions.get("state")=="known"
                        and mentions.get("all") is not True and isinstance(mentions.get("userIds"),list)):
                    targets=[uid for uid in mentions["userIds"] if uid!=self.account]
                    if len(targets)==1 and valid_id(targets[0]):
                        payload["pond_target"]=targets[0]
                        from .display_names import refresh
                        refresh(self.db,self.client,self.group,targets)
                from .intents import command_alias
                cmd=command_alias(cmd) if cmd else cmd
                if cmd in ("图鉴榜","资产榜","资产排行榜","重量榜","重量排行榜","总榜","周榜","月榜","抽签 报名"):
                    from .display_names import refresh
                    from .engine import ranking_rows
                    from .rod import ASSET_RANKS
                    members=[sender]
                    if cmd in ("资产榜","资产排行榜"):
                        members.extend(r["member"] for r in self.db.execute(ASSET_RANKS+" LIMIT 10",(self.group,self.group)))
                    elif cmd == "图鉴榜":
                        from .exhibit_board import ranked
                        members.extend(r["member"] for r in ranked(self.db,self.group).fetchmany(10))
                    elif cmd in ("重量榜","重量排行榜"):
                        members.extend(r[0] for r in self.db.execute("SELECT member FROM fishing_records WHERE grp=? ORDER BY best_grams DESC,member LIMIT 10",(self.group,)))
                    elif cmd in ("总榜","周榜","月榜"):
                        members.extend(r["member"] for r in ranking_rows(self.db,self.group,cmd,time.time()))
                    refresh(self.db,self.client,self.group,members)
                elif cmd and cmd.startswith(("放入图鉴","点亮图鉴","批量点亮图鉴","收入图鉴")):
                    from .display_names import refresh
                    refresh(self.db,self.client,self.group,[sender])
                receipt = bridge.endpoint(self.db, "event", self.secret, {"group_id": self.group, "sender_id": sender,
                                          "source_message_id": source, "payload": payload})
                sequence = receipt["ingest_sequence"]
        # A crash after event commit can replay it. The inbox unique key absorbs the duplicate.
        updated = self.db.execute("UPDATE agent_wechat_links SET cursor=? WHERE slot=? AND grp=? AND cursor=?",
                                  (cursor, self.client.slot, self.group, self.cursor)).rowcount
        if not updated:
            if not self.linked():
                raise LinkRemoved()
            raise RuntimeError("游标已由另一监听实例更新")
        self.cursor = cursor
        return sequence

    def recover_expired(self):
        # v2.7.1 accepts after >= oldest retained sequence - 1. Probe only
        # one event header at a time; unrelated message details are never fetched.
        group, latest = self.client.resolve(self.group)
        if group != self.group or int(latest) <= int(self.cursor):
            raise ValueError("无法确认上游保留区间")
        low, high = int(self.cursor), int(latest)
        while low + 1 < high:
            mid = (low + high) // 2
            try:
                self.client.next_events(mid)
            except CursorExpired:
                low = mid
            else:
                high = mid
        first = self.client.next_events(high)
        if not first or not isinstance(first[0], dict) or first[0].get("cursor") != str(high + 1):
            raise ValueError("上游保留区间已变化，稍后重新核对")
        self.verify()
        with transaction(self.db):
            changed = self.db.execute("UPDATE agent_wechat_links SET cursor=? WHERE slot=? AND grp=? AND cursor=?",
                                      (str(high), self.client.slot, self.group, self.cursor)).rowcount
            if not changed:
                raise RuntimeError("游标已由另一监听实例更新")
            audit(self.db, "agent-wechat", self.group, "事件采集缺口",
                  f"账号事件游标 {int(self.cursor)+1} 至 {high} 已超出上游保留范围，本群受影响条数未知")
        self.cursor = str(high)

    def run(self):
        with listener_lock(self.db, self.client.slot):
            # Reload after acquiring ownership. Another process may have advanced
            # the checkpoint between object construction and lock acquisition.
            checkpoint = self.db.execute("SELECT cursor FROM agent_wechat_links WHERE slot=? AND grp=?",
                                         (self.client.slot, self.group)).fetchone()
            if not checkpoint:
                return
            self.cursor=checkpoint[0]
            self._listen()

    def roster_monitor(self):
        from .native_roster import Monitor
        roster=Monitor(self)
        roster.thread.start()
        return roster

    def _listen(self):
        roster=self.roster_monitor()
        from .native_voice import Monitor as VoiceMonitor
        voice=VoiceMonitor(self,self.private) if self.private is not None else None
        if voice:
            voice.thread.start()
        try:
            while True:
                try:
                    self.verify()
                    refreshed = time.monotonic()
                    try:
                        for event in self.client.events(self.cursor):
                            if time.monotonic() - refreshed >= 8:
                                self.verify()
                                refreshed = time.monotonic()
                            roster.online()
                            if event is not None:
                                previous_cursor=self.cursor
                                self.consume(event)
                                if self.cursor!=previous_cursor:
                                    roster.signal_event(event)
                    except CursorExpired:
                        roster.offline()
                        self.recover_expired()
                    finally:
                        roster.offline()
                except (OSError, http.client.HTTPException, ValueError, sqlite3.OperationalError) as exc:
                    if not self.linked():
                        return
                    self.heartbeat("RECONNECTING" if isinstance(exc, (OSError,http.client.HTTPException)) else "NEED_USER_ACTION")
                    LOG.warning("接收中断，将从已提交的游标重连 (%s)", type(exc).__name__)
                    time.sleep(3)
        except LinkRemoved:
            return
        finally:
            if voice:
                voice.stop.set()
                voice.thread.join(timeout=2)
            roster.close()
            if self.linked():
                self.heartbeat("STOPPED")


def reply_mentions(task):
    sender = task.get("mention_sender")
    if not sender:
        return []
    invitee = task.get("mention_invitee")
    return [sender, invitee] if invitee and invitee != sender else [sender]


def inspect_text_send(client, token, task, timeout=8):
    """Read the durable send and its saved outgoing message. Never submit a message."""
    sender=Client(client.port,client.slot,token)
    path=sender.base+"/sends/by-idempotency-key?"+urlencode({"key":"ergou-"+task["biz"]})
    deadline=time.monotonic()+timeout
    accepted=False
    while True:
        try:
            intent=sender.get(path)
            if intent.get("accountId")!=client.slot or intent.get("destination")!=task["grp"]:
                return "UNKNOWN","发送回执的账号或群不符，待核对"
            state=intent.get("state")
            if state=="accepted":
                accepted=True
                mid,sid=intent.get("localMessageId"),intent.get("serverId")
                if isinstance(mid,str) and 0<len(mid)<=4096 and number(sid) and 0<int(sid)<2**64:
                    message=client.get(client.base+"/messages/"+quote(mid,safe=""))
                    identity=(message.get("id"),message.get("accountId"),message.get("threadId"),
                              message.get("direction"),message.get("serverId"))
                    card=task.get("share")
                    if card:
                        link=message.get("link") or {}
                        is_music=card.get("kind")=="music"
                        matches=(message.get("type")==49 and message.get("appMessageType")== (3 if is_music else 5)
                                 and (not is_music or link.get("description")==card["author"])
                                 and link.get("url")==card["url"] and link.get("title")==card["title"])
                    elif task.get("mention_sender"):
                        mentions=message.get("mentions") or {}
                        body=message.get("body")
                        suffix="\u2005"+task["body"]
                        matches=(type(message.get("type")) is int and message["type"]==1
                                 and isinstance(body,str) and body.startswith("@") and body.endswith(suffix)
                                 and len(body)>len(suffix)+1 and isinstance(mentions,dict)
                                 and mentions.get("state")=="known" and mentions.get("all") is not True
                                 and isinstance(mentions.get("userIds"),list)
                                 and all(isinstance(uid,str) for uid in mentions["userIds"])
                                 and sorted(mentions["userIds"])==sorted(reply_mentions(task)))
                    else:
                        matches=type(message.get("type")) is int and message["type"]==1 and message.get("body")==task["body"]
                    if (identity!=(mid,client.slot,task["grp"],"outgoing",sid)
                            or not matches):
                        return "UNKNOWN","微信已受理，发件记录与任务不符，待核对"
                    return "ACKNOWLEDGED","微信已受理，已回读核对本群发件记录"
            elif state in ("cancelled","failed"):
                return "FAILED","微信未受理消息"
            elif state not in ("queued","submitting"):
                break
        except (OSError,http.client.HTTPException,ValueError):
            # The local message projection can lag the upstream acceptance.
            pass
        remaining=deadline-time.monotonic()
        if remaining<=0:
            break
        time.sleep(min(.4,remaining))
    if accepted:
        return "ACKNOWLEDGED","微信已受理，发件记录暂未核验"
    return "UNKNOWN","发送结果待核对"


def send_direct(client, token, task):
    conn=http.client.HTTPConnection("127.0.0.1",client.port,timeout=5)
    try:
        payload={"threadId":task["grp"],**(task.get("share") or {"text":task["body"]})}
        if not task.get("share") and task.get("mention_sender"):
            payload["mentions"]={"userIds":reply_mentions(task)}
        conn.request("POST",client.base+"/sends",body=dump(payload).encode(),
                     headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","Idempotency-Key":"ergou-"+task["biz"]})
        response=conn.getresponse()
        if response.status in (400,401,403,404,422):
            return "FAILED",f"本机插件拒绝发送 HTTP {response.status}"
    except (OSError,http.client.HTTPException):
        pass  # The submission might have reached the daemon. Inspect the same key once more.
    finally:
        conn.close()
    return inspect_text_send(client,token,task)


def recovery_plan(db,slot,group=None):
    """Describe workers that can resume without granting a new permission."""
    row=db.execute("""SELECT l.grp, (p.grp IS NOT NULL OR EXISTS(SELECT 1 FROM active_native_member_notices c
        WHERE c.grp=g.id AND c.account=g.account AND c.binding=g.binding) OR EXISTS(SELECT 1 FROM active_native_voice v
        WHERE v.grp=g.id AND v.account=g.account AND v.binding=g.binding)
        OR coalesce(json_extract(g.config,'$.exhibit_board_push'),0)=1) AS replies FROM agent_wechat_links l
        JOIN groups g ON g.id=l.grp AND g.account=l.account
        JOIN account a ON a.id=l.account
        JOIN node_grants n ON n.grp=l.grp AND n.account=l.account
        LEFT JOIN group_profile cfg ON cfg.grp=l.grp
        LEFT JOIN directed_groups p ON p.grp=g.id AND p.account=g.account AND p.binding=g.binding
        WHERE l.slot=? AND (? IS NULL OR l.grp=?) AND NOT g.paused AND json_extract(g.config,'$.enabled')=1
        AND a.state!='SUSPENDED' AND NOT COALESCE(cfg.detached,0)""",
        (slot,group,group)).fetchone()
    return dict(listen=bool(row),replies=bool(row and row["replies"]))


def replies(db,client,node_secret,token,name=None,*,group=None,once=False):
    listener=Listener(db,client,node_secret,group=group)
    if name is not None and client.resolve(name)[0]!=listener.group:
        raise ValueError("申请回复的群与已绑定群不一致")
    def directed_authorized(task):
        return db.execute("""SELECT 1 FROM directed_events d JOIN inbox i ON i.event_id=d.biz
            JOIN directed_groups p ON p.grp=i.grp AND p.account=i.account AND p.binding=i.binding
            WHERE d.biz=? AND i.grp=? AND i.account=? AND i.binding=? AND d.source_time>=p.since""",
            (task["biz"],listener.group,listener.account,task["binding"])).fetchone()

    def verify_identity():
        if (client.get("/v1/status").get("serverId")!=listener.server or client.identity()!=listener.account
                or not client.member(listener.group,listener.account)):
            raise ValueError("当前微信身份或成员关系已改变")
    with listener_lock(db,client.slot+"-directed-replies"):
        if name is not None:
            verify_identity()
            with transaction(db):
                if not listener.linked() or not recovery_plan(db,client.slot,listener.group)["listen"]:
                    raise ValueError("群绑定已改变")
                group=db.execute("SELECT binding FROM groups WHERE id=?",(listener.group,)).fetchone()
                db.execute("""INSERT INTO directed_groups VALUES(?,?,?,?) ON CONFLICT(grp) DO UPDATE
                            SET account=excluded.account,binding=excluded.binding,since=excluded.since
                            WHERE directed_groups.account!=excluded.account OR directed_groups.binding!=excluded.binding""",
                           (listener.group,listener.account,group["binding"],time.time()))
        elif not recovery_plan(db,client.slot,listener.group)["replies"]:
            if once:
                return False
            raise ValueError("当前群绑定没有可恢复的回复授权")
        while listener.linked() and recovery_plan(db,client.slot,listener.group)["replies"]:
            task=jobs.claim(db,listener.account,directed_group=listener.group)
            if isinstance(task,dict):
                try:
                    verify_identity()
                    from .models import reply_authorized as model_reply_authorized
                    from .jianghu import reply_valid
                    stale=not model_reply_authorized(db,task["biz"]) or not reply_valid(db,task["id"])
                    from .live_notice import matches
                    unconfirmed=task["biz"].startswith("schedule/") and not matches(db,listener.group,task["biz"],task["body"])
                    if task.get("voice_seq") is not None:
                        from .native_voice import reply_authorized
                        unconfirmed=not reply_authorized(db,task)
                    elif task["biz"].startswith("member/"):
                        from .member_notices import matches as member_matches
                        unconfirmed=not member_matches(db,task)
                    elif task["biz"].startswith("quiz/"):
                        unconfirmed=not db.execute("SELECT 1 FROM valid_quiz_notices WHERE id=?",(task["id"],)).fetchone()
                    elif task["biz"].startswith("exhibit-board/"):
                        from .exhibit_announcements import matches as board_matches
                        unconfirmed=not board_matches(db,task)
                    elif not task["biz"].startswith("schedule/"):
                        unconfirmed=not directed_authorized(task)
                    if not listener.linked() or not recovery_plan(db,client.slot,listener.group)["replies"] or stale or unconfirmed:
                        state,detail="FAILED","群绑定、通知授权或智能对话状态已变化"
                    elif time.time()>=task["expires"]:
                        state,detail="FAILED","点名消息已过期"
                    elif task.get("voice_seq") is not None:
                        from .native_voice_send import send_voice
                        from .voice_policy import verified_credentials
                        def authorized():
                            if not reply_authorized(db,task):
                                return False
                            verify_identity()
                            return reply_authorized(db,task)
                        with transaction(db):
                            auth=verified_credentials(db,task["grp"]) if reply_authorized(db,task) else None
                        if auth is None:
                            state,detail="FAILED","本群语音配置已变化"
                        else:
                            state,detail=send_voice(client,token,task,authorized,auth=auth)
                    else:
                        if model_reply_authorized(db,task["biz"]):
                            card=db.execute("SELECT title,url FROM music_search_cards WHERE task=?",(task["id"],)).fetchone()
                            if card and os.getenv("ERGOU_QQ_MUSIC")=="1":
                                from . import qq_music
                                task["share"]=asyncio.run(qq_music.resolve(card["title"],card["url"]))
                                verify_identity()
                                if (not listener.linked() or not directed_authorized(task)
                                        or not recovery_plan(db,client.slot,listener.group)["replies"]
                                        or time.time()>=min(task["expires"],task["lease"])):
                                    jobs.finish(db,listener.account,task["id"],task["attempt"],"FAILED","点歌已过期或群授权已变化")
                                    if once:
                                        return True
                                    continue
                            elif card:
                                task["share"]=dict(kind="share",title=card["title"],url=card["url"],
                                                   description="在 Apple Music 查看搜索结果")
                            def current_reply():
                                return (listener.linked() and directed_authorized(task)
                                        and time.time()<min(task["expires"],task["lease"])
                                        and model_reply_authorized(db,task["biz"]))
                            picture=db.execute("""SELECT c.snapshot FROM fishing_reply_cards c
                                JOIN outbox o ON o.id=c.task JOIN groups g ON g.id=o.grp
                                WHERE c.task=? AND json_extract(g.config,'$.fishing_cards')=1
                                AND json_extract(g.config,'$.enabled')=1 AND g.paused=0
                                AND g.account=o.account AND g.binding=o.binding""",(task["id"],)).fetchone()
                            trial=db.execute("""SELECT c.snapshot FROM game_card_trials t JOIN game_card_snapshots c
                                               ON c.task=t.task WHERE t.task=? AND t.grp=? AND t.account=? AND t.binding=?""",
                                             (task["id"],task["grp"],listener.account,task["binding"])).fetchone()
                            if trial:
                                from .game_card_send import send_image
                                def image_authorized():
                                    verify_identity()
                                    return (listener.linked() and directed_authorized(task)
                                            and time.time()<min(task["lease"],task["expires"])
                                            and db.execute("SELECT 1 FROM game_card_trials WHERE task=? AND until>?",
                                                           (task["id"],time.time())).fetchone() is not None)
                                state,detail=send_image(client,token,task,trial[0],image_authorized)
                            elif picture:
                                from .fishing_cards import render
                                from .native_voice_send import send_media
                                def image_authorized():
                                    verify_identity()
                                    return current_reply() and db.execute("""SELECT 1 FROM groups
                                        WHERE id=? AND account=? AND binding=? AND NOT paused
                                        AND json_extract(config,'$.enabled')=1 AND json_extract(config,'$.fishing_cards')=1""",
                                        (task["grp"],task["account"],task["binding"])).fetchone()
                                jpeg=render(json.loads(picture[0]))
                                if jpeg:
                                    state,detail=send_media(client,token,task,image_authorized,jpeg,"image")
                                elif image_authorized():
                                    state,detail=send_direct(client,token,task)
                                else:
                                    state,detail="FAILED","钓鱼回复已过期或群授权已变化"
                            else:
                                state,detail=send_direct(client,token,task)
                        else:
                            state,detail="FAILED","本群智能对话或语音上下文授权已变化"
                except (ValueError,OSError,http.client.HTTPException):
                    state,detail="UNKNOWN","插件状态待核对"
                jobs.finish(db,listener.account,task["id"],task["attempt"],state,detail)
            if once:
                return bool(task)
            if not task:
                time.sleep(.5)


def main():
    parser = argparse.ArgumentParser(description="Agent WeChat 单群只读事件插件")
    parser.add_argument("--db", default="data/ergou.sqlite")
    parser.add_argument("--port", type=int, default=6174)
    parser.add_argument("--slot", default="ergou-listener")
    parser.add_argument("--private-dir", type=Path, required=True, help="当前用户私有凭据目录")
    subs = parser.add_subparsers(dest="action", required=True)
    binding = subs.add_parser("link")
    binding.add_argument("--group-name", required=True)
    binding.add_argument("--after", help="已核实的起始游标，默认从当前事件位置开始")
    subs.add_parser("listen")
    media=subs.add_parser("prepare-voice-media",help="为已确认的语音开关准备本机媒体下载权限")
    media.add_argument("--wx",type=Path,required=True)
    subs.add_parser("recovery-plan",help="读取当前槽位可恢复的进程，不联系微信")
    subs.add_parser("resume-replies",help="仅恢复当前群绑定已经授予的回复权限")
    reply_cmd=subs.add_parser("replies")
    reply_cmd.add_argument("--group-name",required=True)
    subs.add_parser("status")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        if args.action=="recovery-plan":
            if not Path(args.db).is_file():
                raise ValueError("未找到业务数据库")
            with closing_db(args.db) as db:
                print(json.dumps(recovery_plan(db,args.slot)))
            return
        if args.action == "status":
            if not Path(args.db).is_file():
                raise ValueError("未找到已绑定的业务数据库")
            with closing_db(args.db) as db:
                row = db.execute("""SELECT a.state,n.last_seen,l.cursor,COUNT(i.seq) AS received,MAX(i.arrived) AS latest
                    FROM agent_wechat_links l JOIN account a ON a.id=l.account JOIN nodes n ON n.account=l.account
                    LEFT JOIN inbox i ON i.account=l.account AND i.grp=l.grp AND i.adapter_version=?
                    WHERE l.slot=? GROUP BY l.slot,l.grp""", (VERSION,args.slot)).fetchone()
                if not row:
                    raise ValueError("未登记该槽位")
                age = int(time.time()-row["last_seen"]) if row["last_seen"] is not None else None
                state = "心跳已过期" if row["state"] == "LISTENING" and (age is None or age >= 30) else row["state"]
                print(dump({"状态":state,"距上次心跳秒数":age,"事件游标":row["cursor"],"已收文本":row["received"],
                            "最近接收时间":datetime.fromtimestamp(row["latest"]).astimezone().isoformat() if row["latest"] else None}))
            return
        token = (args.private_dir / "ergou-read-token").read_text(encoding="utf-8").strip()
        node = args.private_dir / "ergou-node-secret"
        if args.action == "link" and not node.exists():
            with os.fdopen(os.open(node, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
                out.write(secrets.token_urlsafe(48))
        secret = node.read_text(encoding="utf-8").strip()
        client = Client(args.port, args.slot, token)
        initialize(args.db)
        with closing_db(args.db) as db:
            if args.action == "prepare-voice-media":
                from .native_voice import prepare_media
                prepare_media(db,client,args.private_dir,args.wx)
            elif args.action == "link":
                link(db, client, args.group_name, secret, args.after)
                print("已绑定授权群，节点权限为只收。")
            elif args.action in ("replies","resume-replies"):
                sender=(args.private_dir/"ergou-send-token").read_text(encoding="utf-8").strip()
                if not sender:
                    raise ValueError("缺少本机回复凭据")
                replies(db,client,secret,sender,getattr(args,"group_name",None))
            else:
                Listener(db, client, secret,args.private_dir).run()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, sqlite3.Error, http.client.HTTPException, RuntimeError) as exc:
        parser.exit(1, f"接入失败：{exc}\n")


if __name__ == "__main__":
    main()
