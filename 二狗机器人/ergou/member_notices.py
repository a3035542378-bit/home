"""Queue one notification per observed membership change in the roster transaction."""
import hashlib
import json
import re

from .greetings import welcome

SCHEMA="""
CREATE TABLE IF NOT EXISTS native_member_deliveries(
 task INTEGER PRIMARY KEY REFERENCES outbox, kind TEXT NOT NULL CHECK(kind IN ('join','leave')),
 generation INTEGER NOT NULL, server_id TEXT NOT NULL, body_digest TEXT NOT NULL
);
CREATE VIEW IF NOT EXISTS valid_member_deliveries AS
 SELECT o.id,o.grp,o.account,o.binding,o.biz,d.body_digest FROM native_member_deliveries d
 JOIN outbox o ON o.id=d.task JOIN active_native_member_notices p
 ON p.grp=o.grp AND p.account=o.account AND p.binding=o.binding AND p.kind=d.kind
 AND p.generation=d.generation AND p.server_id=d.server_id;
"""


def departure(name):
    return f"{name} 已离开本群。"


def enqueue(db, group, kind, member_id, name, business_key, now):
    if not db.in_transaction:
        raise RuntimeError("成员通知必须与名册更新共同提交")
    policy=db.execute("""SELECT generation,server_id FROM active_native_member_notices
                      WHERE grp=? AND account=? AND binding=? AND kind=?""",
                      (group["id"],group["account"],group["binding"],kind)).fetchone()
    cfg=json.loads(group["config"])
    if not policy or group["paused"] or not cfg["enabled"] or member_id in (group["account"],*cfg["bots"]):
        return
    label=" ".join((name or "").split())[:80] or "一位群成员"
    alias=db.execute("SELECT alias FROM group_profile WHERE grp=?",(group["id"],)).fetchone()
    body=welcome(cfg,label,alias[0] if alias and alias[0] else "本群",now) if kind=="join" else departure(label)
    if not re.fullmatch(r"member/"+kind+r"/[a-f0-9]{64}",business_key):
        raise ValueError("成员变更事件键无效")
    key=business_key
    cur=db.execute("""INSERT OR IGNORE INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
                   VALUES(?,?,?,?,?,'PENDING',?,?,?)""",(key,group["account"],group["id"],group["binding"],body,now,now+120,now))
    if cur.rowcount:
        db.execute("INSERT INTO native_member_deliveries VALUES(?,?,?,?,?)",
                   (cur.lastrowid,kind,policy["generation"],policy["server_id"],hashlib.sha256(body.encode()).hexdigest()))
    return key


def matches(db,task):
    row=db.execute("""SELECT body_digest FROM valid_member_deliveries
                   WHERE id=? AND biz=? AND grp=? AND account=? AND binding=?""",
                   (task["id"],task["biz"],task["grp"],task["account"],task["binding"])).fetchone()
    return bool(row and row[0]==hashlib.sha256(task["body"].encode()).hexdigest())


def confirm_one(db):
    from . import member_policy
    candidates=db.execute("""SELECT s.grp,s.kind,p.alias FROM member_notice_settings s
        JOIN agent_wechat_links l ON l.grp=s.grp LEFT JOIN group_profile p ON p.grp=s.grp
        WHERE s.enabled AND NOT EXISTS(SELECT 1 FROM active_native_member_notices a
        WHERE a.grp=s.grp AND a.kind=s.kind) ORDER BY s.grp,s.kind""").fetchall()
    choices=[]
    for group,kind,alias in candidates:
        try:
            snapshot=member_policy.preview(db,group,kind)
        except ValueError:
            continue
        choices.append(snapshot)
        print(f"{len(choices)}. {alias or group}（{group}） · {snapshot['label']}")
    if not choices:
        print("目前没有等待确认的成员通知。请先在运营后台选择群并打开对应开关。")
        return
    choice=input("输入要确认的一项编号，或直接回车退出：").strip()
    if not choice:
        return
    if not choice.isascii() or not choice.isdecimal() or len(choice)>6 or not 1<=int(choice)<=len(choices):
        raise ValueError("请选择列表中的编号")
    snapshot=choices[int(choice)-1]
    print(f"微信群：{snapshot['group']}\n功能：{snapshot['label']}\n此后将按成员名册变化自动向该群发送文字。")
    if input("如同意启用，请输入「确认启用」：").strip()=="确认启用":
        member_policy.approve(db,snapshot)
        print("已确认。首次同步仅建立名册基线。")
    else:
        print("已取消。")
