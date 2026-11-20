"""一个账号使用一条微信事件流，按群校验并交给既有业务入口。"""
import hashlib
import time
from urllib.parse import quote

from ergou import agent_wechat as wx, bridge, group_binding, roles, wechat_roles
from ergou.db import audit, transaction
from ergou.native_roster import Monitor

ACTIVE = """SELECT l.grp,g.binding FROM agent_wechat_links l
 JOIN groups g ON g.id=l.grp AND g.account=l.account AND g.paused=0
 JOIN account a ON a.id=g.account AND a.state!='SUSPENDED'
 JOIN node_grants n ON n.account=l.account AND n.grp=l.grp
 JOIN directed_groups p ON p.account=g.account AND p.grp=g.id AND p.binding=g.binding
 LEFT JOIN group_profile f ON f.grp=g.id
 WHERE l.slot=? AND l.account=? AND l.server_id=? AND json_extract(g.config,'$.enabled')=1
 AND NOT coalesce(f.detached,0)"""


def groups(db, stream):
    return dict(db.execute(ACTIVE,tuple(stream[k] for k in ("slot","account","server_id"))))


class Rosters:
    def __init__(self):
        self.rooms={}

    def sync(self, listener, rooms):
        for group in self.rooms.keys()-rooms:
            self.rooms.pop(group).close()
        for group in rooms-self.rooms.keys():
            child=wx.Listener(listener.db,listener.client,listener.secret,group=group)
            roster=Monitor(child)
            roster.thread.start()
            self.rooms[group]=roster

    def online(self):
        for roster in self.rooms.values():
            roster.online()

    def offline(self):
        for roster in self.rooms.values():
            roster.offline()

    def signal_event(self,event):
        for roster in self.rooms.values():
            roster.signal_event(event)

    def close(self):
        for roster in self.rooms.values():
            roster.close()


class Stream(wx.Listener):
    def __init__(self, db, client, secret, private, row):
        self.db,self.client,self.secret,self.private=db,client,secret,private
        self.stream=row
        self.account,self.server,self.cursor=(row[k] for k in ("account","server_id","cursor"))
        self.rooms={}
        self.rosters=Rosters()

    def roster_monitor(self):
        return self.rosters

    def linked(self):
        return self.db.execute("""SELECT 1 FROM binding_streams s JOIN account a ON a.id=s.account
            WHERE slot=? AND account=? AND server_id=? AND a.state!='SUSPENDED'""",
            (self.client.slot,self.account,self.server)).fetchone() is not None

    def heartbeat(self,state):
        if not self.linked():
            raise wx.LinkRemoved()
        if state=="LISTENING" and not self.rooms:
            state="WAITING_LOGIN"
        result=bridge.endpoint(self.db,"heartbeat",self.secret,dict(state=state,actual_account=self.account,
            groups=list(self.rooms) if state=="LISTENING" else [],adapter_version=wx.VERSION,
            capabilities=dict(receive=True,send=False,stable_ids=True)))
        if result["state"]!=state:
            raise ValueError("账号心跳未通过")

    def verify(self):
        if self.client.identity()!=self.account or self.client.get("/v1/status").get("serverId")!=self.server:
            raise ValueError("微信账号或服务身份变化")
        rooms={}
        for group,version in groups(self.db,self.stream).items():
            try:
                if self.client.member(group,self.account):
                    if roles.owner(self.db,self.account):
                        wechat_roles.refresh_owner(self.db,self.client,self.account,group)
                    rooms[group]=version
            except (ConnectionError,ValueError) as exc:
                if str(exc) not in ("Agent WeChat HTTP 403","Agent WeChat HTTP 404"):
                    raise
        self.rooms=rooms
        self.rosters.sync(self,set(self.rooms))
        self.heartbeat("LISTENING")

    def advance(self,cursor):
        if not self.db.execute("UPDATE binding_streams SET cursor=? WHERE slot=? AND account=? AND server_id=? AND cursor=?",
                (cursor,self.client.slot,self.account,self.server,self.cursor)).rowcount:
            raise RuntimeError("账号游标已改变")
        self.cursor=cursor

    def consume(self,event):
        cursor=event.get("cursor")
        if not wx.number(cursor) or event.get("accountId",self.client.slot)!=self.client.slot:
            raise ValueError("微信账号事件无效")
        if int(cursor)<=int(self.cursor):
            return
        data=event.get("data") or {}
        if event.get("kind")=="message.committed" and isinstance(data,dict):
            group=data.get("threadId")
            top=roles.owner(self.db,self.account)
            private=bool(top and group==top["owner_user_id"])
            if (wx.valid_id(group) and (group.endswith("@chatroom") or private) and data.get("origin")=="live"
                    and data.get("direction") in (None,"incoming")):
                self.route(event,data,group)
        self.advance(cursor)

    def route(self,event,data,group):
        registered=group in self.rooms and groups(self.db,self.stream).get(group)==self.rooms[group]
        if not registered:
            sender=data.get("senderId")
            if sender and not group_binding.administrator(self.db,self.account,sender):
                return
            if not roles.owner(self.db,self.account) and not self.db.execute("SELECT 1 FROM binding_admins WHERE account=? LIMIT 1",(self.account,)).fetchone():
                return
        mid=data.get("messageId")
        if not isinstance(mid,str) or not 0<len(mid)<=8192:
            return
        try:
            msg=self.client.get(self.client.base+"/messages/"+quote(mid,safe=""))
        except ConnectionError as exc:
            if str(exc)=="Agent WeChat HTTP 404":
                return
            raise
        if (msg.get("accountId"),msg.get("threadId"),msg.get("id"))!=(self.client.slot,group,mid):
            raise ValueError("微信消息与事件身份不符")
        top=roles.owner(self.db,self.account)
        private=not group.endswith("@chatroom")
        if top and msg.get("senderId")==top["owner_user_id"] and (private or registered):
            text=msg.get("body")
            if isinstance(text,str) and text.startswith("二狗") and wechat_roles.remote(
                    self.db,self.client,self.account,group,msg,text[2:].strip()):
                return
        if private:
            return
        action=group_binding.command(msg,self.account)
        if action:
            group_binding.handle(self.db,self.client,self.stream,group,event["cursor"],msg,action,self.secret)
            if group_binding.administrator(self.db,self.account,msg.get("senderId")):
                self.verify()
        elif registered:
            wx.Listener(self.db,self.client,self.secret,self.private,group=group).consume(event,msg)

    def run(self):
        with wx.listener_lock(self.db,self.client.slot):
            self.cursor=self.db.execute("SELECT cursor FROM binding_streams WHERE slot=?",(self.client.slot,)).fetchone()[0]
            self._listen()

    def recover_expired(self):
        latest=self.client.get(self.client.base+"/groups?limit=1").get("asOfEventCursor")
        if not wx.number(latest) or int(latest)<=int(self.cursor):
            raise ValueError("微信事件保留范围未知")
        low,high=int(self.cursor),int(latest)
        while high-low>1:
            mid=(low+high)//2
            try:
                self.client.next_events(mid)
                high=mid
            except wx.CursorExpired:
                low=mid
        self.verify()
        with transaction(self.db):
            audit(self.db,"agent-wechat",None,"账号事件采集缺口",f"{int(self.cursor)+1} 至 {high}")
            self.advance(str(high))


def send_receipt(db,client,stream,token):
    account=stream["account"]
    row=db.execute("""SELECT * FROM binding_receipts WHERE account=? AND state='PENDING' AND expires>?
                      ORDER BY expires LIMIT 1""",(account,time.time())).fetchone()
    if not row:
        return False
    key=(account,row["source"])
    if (not group_binding.administrator(db,account,row["member"]) or client.identity()!=account
            or client.get("/v1/status").get("serverId")!=stream["server_id"] or not client.member(row["grp"],account)):
        db.execute("UPDATE binding_receipts SET state='CANCELLED' WHERE account=? AND source=?",key)
        return True
    biz="binding-"+hashlib.sha256((account+"/"+row["source"]).encode()).hexdigest()
    # 同一个上游幂等键可安全重试进程崩溃时尚未记录的回执。
    state,_=wx.send_direct(client,token,dict(grp=row["grp"],body=row["body"],biz=biz))
    db.execute("UPDATE binding_receipts SET state=? WHERE account=? AND source=?",(state,*key))
    return True


def send_notice(db,client,stream,token):
    bot=stream["account"]
    row=db.execute("SELECT * FROM role_notices WHERE bot_id=? AND expires>? ORDER BY id LIMIT 1",
                   (bot,time.time())).fetchone()
    if not row:
        return False
    dest=row["destination"]
    binding=roles.active(db,bot,dest)
    top=roles.owner(db,bot)
    permitted=(dest==top["owner_user_id"] if top and row["binding"] is None
               else binding and binding[0]==row["binding"] and client.member(dest,bot))
    if permitted and client.identity()==bot and client.get("/v1/status").get("serverId")==stream["server_id"]:
        wx.send_direct(client,token,dict(grp=dest,body=row["body"],biz="role-"+str(row["id"])))
    db.execute("UPDATE role_notices SET body='',expires=-abs(expires) WHERE id=?",(row["id"],))
    return True


def replies(db,client,secret,token,stream):
    with wx.listener_lock(db,client.slot+"-binding-router"):
        next_cleanup=0
        while db.execute("SELECT 1 FROM account WHERE id=? AND state!='SUSPENDED'",(stream["account"],)).fetchone():
            if time.monotonic()>=next_cleanup:
                db.execute("DELETE FROM binding_receipts WHERE account=? AND expires<?",(stream["account"],time.time()-86400))
                db.execute("DELETE FROM role_notices WHERE abs(expires)<?",(time.time()-86400,))
                next_cleanup=time.monotonic()+3600
            busy=send_notice(db,client,stream,token) or send_receipt(db,client,stream,token)
            pending=db.execute("""SELECT DISTINCT grp FROM outbox WHERE account=? AND state IN ('PENDING','RETRY_WAIT','SENDING')""",
                               (stream["account"],))
            for group in set(r[0] for r in pending) & groups(db,stream).keys():
                busy=wx.replies(db,client,secret,token,group=group,once=True) or busy
            if not busy:
                time.sleep(.5)
