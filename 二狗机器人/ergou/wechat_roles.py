"""微信身份适配。授权目标只信任平台的群资料与结构化提及。"""
from datetime import datetime
import time
from urllib.parse import quote
from . import roles
from .agent_wechat import valid_id,number
from .db import transaction
from .display_names import refresh


def refresh_owner(db,client,bot,group,*,notify=True):
    room=client.get(client.base+"/groups/"+quote(group,safe=""))
    if room.get("id")!=group or room.get("isInGroup") is False:
        raise ValueError("无法核实群身份")
    uid=room.get("ownerId")
    old=db.execute("SELECT owner_user_id FROM group_binding WHERE group_id=?",(group,)).fetchone()
    known=valid_id(uid)
    if known and (not old or old[0]!=uid):
        refresh(db,client,group,[uid])
    name=next((s for s in (room.get("name"),room.get("displayName")) if isinstance(s,str) and s and s!=group),"微信群")
    with transaction(db):
        roles.sync(db,bot,group,uid if known else None,name,notify=notify)


def target_member(db,client,bot,group,msg):
    mentions=msg.get("mentions") or {}
    if (not isinstance(mentions,dict) or mentions.get("state")!="known" or mentions.get("all") is True
            or not isinstance(mentions.get("userIds"),list)):
        return None
    users=[u for u in mentions["userIds"] if u!=bot]
    if len(users)!=1 or not valid_id(users[0]):
        return None
    uid=users[0]
    data=client.get(client.base+"/groups/"+quote(group,safe="")+"/members/"+quote(uid,safe=""))
    if (data.get("groupId"),data.get("username"),data.get("state"))!=(group,uid,"present"):
        return None
    refresh(db,client,group,[uid])
    return uid


def remote(db,client,bot,group,msg,command):
    import re
    actor=msg.get("senderId")
    top=roles.owner(db,bot)
    private=group==actor
    if not top or actor!=top["owner_user_id"] or not (private or roles.active(db,bot,group)):
        return False
    if private and command.startswith("群主授权列表"):
        room=group
        cmd=command
    else:
        match=re.fullmatch(r"管理群\s*#?([1-9][0-9]{0,12})\s+(授权群主|取消群主授权|查看群主状态|本群设置(?: .+)?)",command)
        if not match:
            return False
        row=db.execute("SELECT group_id FROM group_binding WHERE rowid=? AND bot_id=?",(int(match[1]),bot)).fetchone()
        if not row:
            return True
        room,cmd=row[0],match[2]
        if not roles.active(db,bot,room) or not client.member(room,bot):
            return True
        refresh_owner(db,client,bot,room)
    source=msg.get("serverId")
    if not number(source) or msg.get("direction")!="incoming" or msg.get("type")!=1 or msg.get("recall"):
        return True
    try:
        stamp=datetime.fromisoformat(msg["createdAt"])
        if not stamp.tzinfo or not time.time()-120<stamp.timestamp()<=time.time()+5:
            return True
    except (KeyError,TypeError,ValueError,OverflowError):
        return True
    with transaction(db):
        if db.execute("SELECT 1 FROM role_notices WHERE bot_id=? AND source=?",(bot,source)).fetchone():
            return True
        if roles.owner(db,bot)["owner_user_id"]!=actor:
            return True
        try:
            body=roles.handle(db,bot,room,actor,cmd)
        except ValueError as exc:
            body=str(exc)
        binding=None if private else roles.active(db,bot,group)[0]
        db.execute("INSERT INTO role_notices(bot_id,destination,binding,body,expires,source) VALUES(?,?,?,?,?,?)",
                   (bot,group,binding,body,stamp.timestamp()+120,source))
    return True
