"""Receive text from one authorized WeFlow group over its local ChatLab API."""
import argparse
import getpass
import http.client
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote, urlencode

from . import bridge
from .db import closing_db, dump

LOG = logging.getLogger("ergou.weflow")
VERSION = "weflow-chatlab/1"
PAGE = 100


class SourceError(ValueError):
    pass


def stable(value):
    return isinstance(value, str) and 0 < len(value) <= 160 and value == value.strip()


class Source:
    def __init__(self, port, token):
        self.port = port
        self.token = token

    def get(self, path, **params):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("GET", path + ("?" + urlencode(params) if params else ""),
                               headers={"Authorization": "Bearer " + self.token} if self.token else {})
            response = connection.getresponse()
            if response.status != 200:
                raise SourceError(f"WeFlow HTTP {response.status}，请核对本机 API 端口、授权及版本")
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise SourceError("WeFlow 响应超过读取上限")
            try:
                data = json.loads(raw)
            except (UnicodeError, ValueError):
                raise SourceError("WeFlow 未返回有效 JSON") from None
            if not isinstance(data, dict):
                raise SourceError("WeFlow 响应格式无效")
            return data
        finally:
            connection.close()

    def find_group(self, name):
        if not stable(name):
            raise SourceError("需要完整的目标群名称")
        data = self.get("/api/v1/sessions", keyword=name, limit=100)
        rows = data.get("sessions")
        if data.get("success") is not True or not isinstance(rows, list) or len(rows) >= 100:
            raise SourceError("无法完整核对群名，请改用已确认的稳定群 ID")
        matches = {r["username"] for r in rows if isinstance(r, dict) and r.get("displayName") == name
                   and stable(r.get("username")) and r["username"].endswith("@chatroom")}
        if len(matches) != 1:
            raise SourceError("群名未唯一匹配，请核对目标群的稳定 ID")
        return matches.pop()

    def members(self, group):
        data = self.get("/api/v1/group-members", chatroomId=group, forceRefresh=1)
        if data.get("success") is not True or data.get("chatroomId") != group or not isinstance(data.get("members"), list):
            raise SourceError("未取得目标群成员关系")
        return {m["wxid"] for m in data["members"] if isinstance(m, dict) and stable(m.get("wxid"))}

    def page(self, group, start, end, offset, limit=PAGE):
        data = self.get("/api/v1/sessions/" + quote(group, safe="") + "/messages",
                        since=start, end=end, offset=offset, limit=limit)
        meta = data.get("meta")
        if (not isinstance(meta, dict) or meta.get("type") != "group" or meta.get("groupId") != group
                or not stable(meta.get("ownerId"))):
            raise SourceError("群或数据源账号身份无法核实")
        if not isinstance(data.get("messages"), list) or not isinstance(data.get("sync"), dict):
            raise SourceError("WeFlow 群消息分页格式无效")
        return meta["ownerId"], data["messages"], data["sync"]


class Listener:
    def __init__(self, db, source, account, group, secret, start):
        grant = db.execute("""SELECT 1 FROM node_grants g JOIN listener_nodes l ON l.account=g.account
              JOIN nodes n ON n.account=g.account JOIN groups b ON b.id=g.grp AND b.account=g.account
              WHERE g.account=? AND g.grp=? AND n.secret_hash=?""", (account, group, bridge.digest(secret))).fetchone()
        if not grant:
            raise SourceError("请先按账号和群登记只收节点，并核对节点密钥")
        self.db, self.source, self.account, self.group, self.secret = db, source, account, group, secret
        self.start = self.through = start
        self.members = set()
        self.members_until = 0

    def heartbeat(self, state):
        return bridge.endpoint(self.db, "heartbeat", self.secret, {
            "adapter_version": VERSION, "actual_account": self.account if state == "LISTENING" else "",
            "state": state, "groups": [self.group] if state == "LISTENING" else [],
            "capabilities": {"receive": True, "send": False, "stable_ids": True},
        })["state"]

    def poll(self, now):
        # Overlap tolerates late indexing. Fix both ends while following offsets.
        # After long disconnection resume live monitoring without executing old commands.
        start = max(self.start, self.through - 10, now - 60)
        if now < start:
            raise SourceError("本机时间早于监听起点")
        offset, events = 0, []
        while True:
            actual, rows, sync = self.source.page(self.group, start, now, offset)
            if actual != self.account:
                raise SourceError("WeFlow 当前账号与登记账号不符")
            if time.monotonic() >= self.members_until:
                self.members = self.source.members(self.group)
                self.members_until = time.monotonic() + 10
            if actual not in self.members:
                raise SourceError("当前账号未出现在目标群成员列表")
            for msg in rows:
                if not isinstance(msg, dict):
                    raise SourceError("群消息条目格式无效")
                sender, source, at = msg.get("sender"), msg.get("platformMessageId"), msg.get("timestamp")
                if (type(msg.get("type")) is not int or msg["type"] != 0 or not stable(sender)
                        or sender == actual or sender.startswith("unknown_sender_") or sender not in self.members
                        or not stable(source) or not source.isascii() or not source.isdecimal() or int(source) == 0
                        or type(at) is not int or not start <= at <= now):
                    continue
                payload = {"text": msg.get("content")}
                if isinstance(payload["text"], str) and len(dump(payload).encode()) <= 8192:
                    events.append((at, sender, source, payload))
            if sync.get("hasMore") is False:
                break
            following = sync.get("nextOffset")
            if (sync.get("hasMore") is not True or not rows or type(following) is not int
                    or following != offset + len(rows) or following > 10000):
                raise SourceError("WeFlow 分页游标无效或单次窗口过大")
            offset = following
        if self.heartbeat("LISTENING") != "LISTENING":
            raise SourceError("二狗未确认只收节点和群授权")
        for _, sender, source, payload in sorted(events, key=lambda event: event[0]):
            bridge.endpoint(self.db, "event", self.secret, {
                "group_id": self.group, "sender_id": sender, "source_message_id": source, "payload": payload,
            })
        self.through = now

    def run(self):
        try:
            while True:
                try:
                    self.poll(int(time.time()))
                except (OSError, http.client.HTTPException, sqlite3.OperationalError, ValueError) as exc:
                    self.members_until = 0
                    state = "RECONNECTING" if isinstance(exc, (OSError, http.client.HTTPException, sqlite3.OperationalError)) else "NEED_USER_ACTION"
                    self.heartbeat(state)
                    LOG.warning("监听中断，3 秒后复核：%s", exc)
                time.sleep(3)
        finally:
            self.heartbeat("STOPPED")


def main():
    parser = argparse.ArgumentParser(description="通过 WeFlow 本机 API 监听一个授权微信群")
    parser.add_argument("--port", type=int, default=5031)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("health")
    check = subs.add_parser("check")
    target = check.add_mutually_exclusive_group(required=True)
    target.add_argument("--group-name")
    target.add_argument("--group-id")
    listen = subs.add_parser("listen")
    listen.add_argument("--account", required=True)
    listen.add_argument("--group-id", required=True)
    listen.add_argument("--db", default="data/ergou.sqlite")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口无效")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        source = Source(args.port, "")
        if source.get("/health").get("status") != "ok":
            raise SourceError("WeFlow 健康检查未通过")
        if args.command == "health":
            print("本机 HTTP 健康检查通过")
            return
        source.token = os.getenv("ERGOU_WEFLOW_TOKEN") or getpass.getpass("WeFlow 本机 API Token：")
        if not source.token:
            raise SourceError("缺少 WeFlow API Token")
        group = args.group_id if args.group_id is not None else source.find_group(args.group_name)
        if not stable(group) or not group.endswith("@chatroom"):
            raise SourceError("需要有效的微信群 ID")
        now = int(time.time())
        if args.command == "check":
            account, _, _ = source.page(group, now, now, 0, limit=1)
            if account not in source.members(group):
                raise SourceError("无法确认数据源账号是目标群成员")
            print("数据源账号 ID", account)
            print("目标群 ID", group)
            return
        if not Path(args.db).is_file():
            raise SourceError("请先初始化二狗数据库并登记只收节点")
        secret = os.getenv("ERGOU_NODE_SECRET") or getpass.getpass("二狗节点密钥：")
        with closing_db(args.db) as db:
            Listener(db, source, args.account, group, secret, now).run()
    except KeyboardInterrupt:
        pass
    except (OSError, http.client.HTTPException, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"WeFlow 接入失败：{exc}\n")


if __name__ == "__main__":
    main()
