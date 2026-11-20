"""微信绑定指令。账号级授权独立于各群的玩法、模型与运营权限。"""
from datetime import datetime
import time

from . import bridge
from .agent_wechat import number, valid_id
from .db import audit, transaction
from .engine import addressed_command

COMMANDS = {"激活本群": "activate", "停用本群": "pause", "绑定状态": "status"}


def administrator(db, account, member):
    return db.execute("SELECT 1 FROM binding_admins WHERE account=? AND member=?", (account,member)).fetchone()


def command(message, account):
    mentions = message.get("mentions")
    body = message.get("body")
    if (message.get("direction") != "incoming" or message.get("type") != 1 or message.get("recall")
            or not isinstance(body,str) or len(body)>512 or not isinstance(mentions,dict)
            or mentions.get("state")!="known" or mentions.get("self") is not True
            or mentions.get("all") is True or mentions.get("userIds") != [account]):
        return None
    return COMMANDS.get(addressed_command(body,"二狗",True))


def change(db, stream, group, cursor, action, secret, now):
    account = stream["account"]
    row = db.execute("""SELECT g.*,json_extract(g.config,'$.enabled') enabled,l.server_id,l.slot,p.since,d.detached,b.binding stopped
        FROM groups g LEFT JOIN agent_wechat_links l ON l.grp=g.id AND l.account=g.account
        LEFT JOIN directed_groups p ON p.grp=g.id AND p.binding=g.binding AND p.account=g.account
        LEFT JOIN group_profile d ON d.grp=g.id LEFT JOIN binding_pauses b ON b.grp=g.id
        WHERE g.id=?""",(group,)).fetchone()
    if row and (row["account"]!=account or row["server_id"]!=stream["server_id"] or row["slot"]!=stream["slot"]
                or row["detached"] or not row["enabled"] or not db.execute("SELECT 1 FROM node_grants WHERE account=? AND grp=?",(account,group)).fetchone()):
        return "本群已有独立的接入配置，请在运营后台核对。"
    active = row and not row["paused"] and row["since"] is not None
    if action=="status":
        return "✅ 本群已激活" if active else "本群尚未激活。"
    if action=="pause":
        if not active:
            return "本群当前未启用。"
        db.execute("UPDATE groups SET paused=1,binding=binding+1 WHERE id=?", (group,))
        db.execute("DELETE FROM directed_groups WHERE grp=?", (group,))
        db.execute("INSERT OR REPLACE INTO binding_pauses VALUES(?,?)",(group,row["binding"]+1))
        db.execute("DELETE FROM membership WHERE grp=? AND account=?", (group,account))
        db.execute("UPDATE outbox SET state='CANCELLED' WHERE grp=? AND state IN ('PENDING','RETRY_WAIT')",(group,))
        return "⏸ 本群已停用，群内数据已保留。"
    if active:
        return "✅ 本群已激活"
    if row and (not row["paused"] or row["stopped"]!=row["binding"]):
        return "本群已由后台暂停或撤销授权，请在后台核对。"
    if not row:
        bridge.enroll_in_transaction(db,account,group,secret,listen_only=True)
        db.execute("INSERT INTO agent_wechat_links VALUES(?,?,?,?,?)",
                   (stream["slot"],account,group,stream["server_id"],cursor))
    db.execute("UPDATE groups SET paused=0 WHERE id=?", (group,))
    db.execute("DELETE FROM binding_pauses WHERE grp=?", (group,))
    db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups WHERE id=?", (now,group))
    db.execute("INSERT OR IGNORE INTO membership VALUES(?,?)", (account,group))
    return "✅ 本群已激活。发「二狗菜单」开始使用。"


def handle(db, client, stream, group, cursor, message, action, secret):
    now=time.time()
    account, sender, source=stream["account"], message.get("senderId"), message.get("serverId")
    if not valid_id(sender) or sender==account or not number(source) or int(source)<=0 or not administrator(db,account,sender):
        return
    try:
        stamp=datetime.fromisoformat(message["createdAt"])
        fresh=stamp.tzinfo and now-120 < stamp.timestamp() <= now+5
    except (KeyError,ValueError,TypeError,OverflowError):
        return
    if not fresh or client.identity()!=account or client.get("/v1/status").get("serverId")!=stream["server_id"] or not client.member(group,account):
        return
    with transaction(db):
        if not administrator(db,account,sender) or db.execute("SELECT 1 FROM binding_receipts WHERE account=? AND source=?",(account,source)).fetchone():
            return
        if not db.execute("SELECT 1 FROM account WHERE id=? AND state!='SUSPENDED'",(account,)).fetchone():
            return
        body=change(db,stream,group,cursor,action,secret,now)
        db.execute("INSERT INTO binding_receipts(account,source,grp,member,body,expires) VALUES(?,?,?,?,?,?)",
                   (account,source,group,sender,body,stamp.timestamp()+120))
        audit(db,sender,group,"微信绑定管理",body)
