"""Moderation outcomes for local simulations and capability-limited connectors."""
import time

from .db import audit

SCHEMA="""
CREATE TABLE IF NOT EXISTS moderation_actions (
 seq INTEGER PRIMARY KEY REFERENCES inbox, grp TEXT NOT NULL REFERENCES groups, action TEXT NOT NULL,
 outcome TEXT NOT NULL, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS simulation_exclusions (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, PRIMARY KEY(grp,member)
);
"""


def excluded(db,event):
    key=(event["grp"],event["member"])
    if event["kind"]=="join":
        db.execute("DELETE FROM simulation_exclusions WHERE grp=? AND member=?",key)
        return False
    return event["kind"]=="message" and db.execute(
        "SELECT 1 FROM simulation_exclusions WHERE grp=? AND member=?",key).fetchone() is not None


def apply_action(db,group,event,action):
    mode=db.execute("SELECT mode FROM account WHERE id=?",(event["account"],)).fetchone()[0]
    outcome="待单项授权及适配器支持"
    if mode=="simulation":
        outcome="模拟执行完成"
        if action=="移出群聊":
            key=(group["id"],event["member"])
            db.execute("INSERT OR IGNORE INTO simulation_exclusions VALUES(?,?)",key)
            for table in ("known_members","managers","candidates","welcomes"):
                db.execute(f"DELETE FROM {table} WHERE grp=? AND member=?",key)
        else:
            db.execute("INSERT OR IGNORE INTO recalls VALUES(?,?,?,?)",
                       (event["seq"],group["id"],event["source"],event["arrived"]))
    db.execute("INSERT INTO moderation_actions VALUES(?,?,?,?,?)",(event["seq"],group["id"],action,outcome,time.time()))
    audit(db,"二狗",group["id"],action,outcome+" · 事件 "+str(event["seq"]))
    return None
