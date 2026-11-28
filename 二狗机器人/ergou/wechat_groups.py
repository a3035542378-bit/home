"""系统管理员按已登录微信身份选择运营群。"""
import os
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from . import agent_wechat as wx, group_binding, roles, wechat_login
from .db import audit, transaction


def service(user):
    plugin = wechat_login._plugin(user)
    return wx.Client(plugin.port, plugin.slot, plugin.token)


def identity(client):
    account = client.identity()
    server = client.get("/v1/status").get("serverId")
    if not wx.valid_id(server):
        raise ValueError("微信服务身份缺失，请刷新")
    return account, server


def directory(db, client, cursor="", expected=None):
    account, server = identity(client)
    if expected and expected != account:
        raise ValueError("微信登录账号已变化，请刷新")
    params = {"limit": 50}
    if cursor:
        params["cursor"] = cursor
    page = client.get(client.base + "/groups?" + urlencode(params))
    if identity(client) != (account, server):
        raise ValueError("读取期间微信账号已变化，请刷新")
    items = []
    for room in page["items"]:
        group = room.get("id")
        if not wx.valid_id(group) or not group.endswith("@chatroom") or room.get("isInGroup") is False:
            continue
        record = db.execute("SELECT account,paused FROM groups WHERE id=?", (group,)).fetchone()
        state = "未绑定"
        if record:
            state = ("其他账号已绑定" if record["account"] != account else
                     "已绑定" if roles.active(db, account, group) else "已暂停")
        items.append(dict(id=group, name=room.get("displayName") or group, state=state))
    return dict(account=account, server=server, items=items, next=page.get("nextCursor"),
                partial=page.get("coverage", {}).get("partial") is not False)


def bind(db, client, data, user):
    group = data.get("group")
    account, server = identity(client)
    if (not wx.valid_id(group) or not group.endswith("@chatroom")
            or (account, server) != (data.get("account"), data.get("server"))):
        raise ValueError("微信登录账号或所选群已变化，请刷新")
    if not client.member(group, account):
        raise ValueError("当前微信账号不在该群")
    path = client.base + "/groups/" + quote(group, safe="")
    room = client.get(path)
    cursor = client.get(path + "/members?limit=1").get("asOfEventCursor")
    if room.get("id") != group or not wx.number(cursor) or identity(client) != (account, server):
        raise ValueError("群身份或事件位置已变化，请刷新")
    credential = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "ergou-node-secret"
    secret = credential.read_text(encoding="ascii").strip()
    now = time.time()
    with transaction(db):
        stream = db.execute("SELECT * FROM binding_streams WHERE slot=?", (client.slot,)).fetchone()
        if stream and (stream["account"], stream["server_id"]) != (account, server):
            raise ValueError("该槽位仍绑定其他微信身份，请先办理账号迁移")
        if db.execute("SELECT 1 FROM account WHERE id=? AND state='SUSPENDED'", (account,)).fetchone():
            raise ValueError("该微信账号已暂停，请先核对账号状态")
        fresh = stream is None
        if fresh:
            if db.execute("SELECT 1 FROM agent_wechat_links WHERE slot=? OR account=?", (client.slot,account)).fetchone():
                raise ValueError("已有接入记录，请先恢复原监听")
            stream = dict(slot=client.slot, account=account, server_id=server)
        result = group_binding.change(db,stream,group,cursor,"activate",secret,now)
        if not result.startswith("✅"):
            raise ValueError(result)
        if fresh:
            db.execute("INSERT INTO binding_streams VALUES(?,?,?,?)",(client.slot, account, server, cursor))
        if roles.owner(db, account):
            db.execute("""INSERT OR IGNORE INTO group_binding(group_id,bot_id,bound_at,label,checked)
                          VALUES(?,?,?,'微信群',0)""", (group,account,now))
        db.execute("INSERT OR IGNORE INTO group_profile(grp,alias) VALUES(?,?)",
                   (group, (room.get("displayName") or group)[:100]))
        audit(db,user["name"],group,"后台绑定微信群","已核对登录账号和群成员关系")
    return {"group": group}
