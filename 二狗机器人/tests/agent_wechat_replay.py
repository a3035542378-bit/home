"""Replay a recorded group event twice via fresh SSE connections into memory only."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import secrets
import sqlite3
import time

from ergou import agent_wechat as aw, bridge
from ergou.db import SCHEMA, closing_db


def replay(db, api, secret, expected, end):
    listener = aw.Listener(db, api, secret)
    listener.verify()
    deadline = time.monotonic() + 45
    with closing(api.events(listener.cursor)) as events:
        for event in events:
            if time.monotonic() >= deadline:
                break
            if event is None:
                continue
            if not aw.number(event.get("cursor")) or int(event["cursor"]) > int(end):
                break
            previous = listener.cursor
            seq = listener.consume(event)
            if seq is not None and db.execute(
                "SELECT 1 FROM inbox WHERE seq=? AND account=? AND grp=? AND source=? AND member=?", (seq, *expected)
            ).fetchone():
                return previous, listener.cursor, event["data"]["messageId"]
            if listener.cursor == end:
                break
    raise ValueError("指定区间未重放目标记录")


def verify(path, api, seq, after):
    if not aw.number(after):
        raise ValueError("起始游标无效")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as production:
        row = production.execute("""SELECT l.account,l.grp,l.server_id,l.cursor,i.source,i.member
            FROM agent_wechat_links l JOIN inbox i ON i.grp=l.grp AND i.account=l.account
            WHERE l.slot=? AND i.seq=? AND i.adapter_version=? AND i.kind='message' AND i.message_type='text'""",
            (api.slot, seq, aw.VERSION)).fetchone()
    if not row:
        raise ValueError("未找到该绑定群的已接收文本")
    account, group, server, end, source, member = row
    if int(after) >= int(end):
        raise ValueError("起始游标必须早于已提交的进度")
    expected = account, group, source, member
    secret = secrets.token_urlsafe(48)
    with closing_db(":memory:") as db:
        db.executescript(SCHEMA.read_text(encoding="utf-8"))
        bridge.enroll(db, account, group, secret, listen_only=True)
        db.execute("INSERT INTO agent_wechat_links VALUES(?,?,?,?,?)", (api.slot, account, group, server, after))
        first = replay(db, api, secret, expected, end)
        original = db.execute("SELECT seq,event_id FROM inbox WHERE account=? AND source=?", (account,source)).fetchone()
        total = db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0]
        # Reproduce a process exit after the inbox commit but before the checkpoint.
        db.execute("UPDATE agent_wechat_links SET cursor=?", (first[0],))
        second = replay(db, api, secret, expected, first[1])
        found = db.execute("SELECT seq,event_id FROM inbox WHERE account=? AND grp=? AND source=? AND member=?", expected).fetchall()
        if first != second or found != [original] or db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] != total:
            raise ValueError("两次重订阅的事件身份或入库结果不一致")
        return {"生产入站序号": seq, "事件游标": first[1], "独立订阅次数": 2,
                "同一消息入库条数": len(found), "隔离库发送任务": db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--slot", default="ergou-listener")
    parser.add_argument("--port", type=int, default=6174)
    parser.add_argument("--seq", type=int, required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    token = (args.private_dir / "ergou-read-token").read_text(encoding="utf-8").strip()
    api = aw.Client(args.port, args.slot, token)
    print(json.dumps(verify(args.db, api, args.seq, args.after), ensure_ascii=False))
