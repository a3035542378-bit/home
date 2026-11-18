import csv
import io
import json
import logging
import os
import re
import sqlite3
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from . import admin, bridge, jobs, models, operations, retention
from .db import closing_db, dump
from .engine import receive
from .monitor import overview
from . import group_tools, reply_rules

STATIC=Path(__file__).with_name("ui")
ASSETS={"/":("index.html","text/html"),"/app.js":("app.js","text/javascript"),"/style.css":("style.css","text/css")}
ASSETS["/voice-sample.wav"]=("voice-sample.wav","audio/wav")
for script in ("rules.js","group-tools.js","member-notices.js","voice.js","accounts.js","wechat-login.js"):
    ASSETS["/"+script]=(script,"text/javascript")


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        pass

    def respond(self,code,body,mime="application/json",cookie=None):
        if not isinstance(body,bytes):
            body=dump(body).encode()
        self.send_response(code)
        self.send_header("Content-Type",mime if mime.startswith(("audio/","image/")) else mime+"; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; img-src 'self' https:; media-src 'self' blob:; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        if cookie:
            self.send_header("Set-Cookie",cookie)
        self.end_headers()
        self.wfile.write(body)

    def token(self):
        cookie=SimpleCookie()
        cookie.load(self.headers.get("Cookie",""))
        name=self.server.session_cookie
        return cookie[name].value if name in cookie else ""

    def route(self,db):
        url=urlsplit(self.path)
        path=url.path
        post=self.command=="POST"
        if not post and path in ASSETS:
            file,mime=ASSETS[path]
            return self.respond(200,(STATIC/file).read_bytes(),mime)
        data={}
        if post:
            if self.headers.get("Content-Type","").split(";")[0]!="application/json":
                raise ValueError("仅接受 JSON")
            size=int(self.headers.get("Content-Length","0"))
            audio_upload=path in ("/api/speech/detect","/api/voice-policy/test")
            if audio_upload and not admin.identity(db,self.token()):
                return self.respond(401,{"error":"请登录"})
            limit=2600000 if audio_upload else 600000 if path=="/api/reply-rules" else 20000
            if not 0<size<=limit:
                raise ValueError("请求长度无效")
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise ValueError("请求格式错误")
        if post and path.startswith("/bridge/"):
            auth=self.headers.get("Authorization","")
            if not auth.startswith("Bearer "):raise PermissionError("FORBIDDEN 缺少节点认证")
            return self.respond(200,bridge.endpoint(db,path.split("/")[-1],auth[7:],data))
        if path=="/api/login" and post:
            token=admin.login(db,str(data["name"]),str(data["password"]),self.client_address[0])
            return self.respond(200,{"ok":True},cookie=f"{self.server.session_cookie}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
        u=admin.identity(db,self.token())
        if not u:
            return self.respond(401,{"error":"请登录"})
        if path=="/api/admin-accounts":
            from . import admin_accounts
            result=admin_accounts.create(db,u,data) if post else admin_accounts.view(db,u)
            return self.respond(201 if post else 200,result)
        if path=="/api/wechat-login":
            from . import wechat_login
            return self.respond(200,wechat_login.action(u,data) if post else wechat_login.status(u))
        if path=="/api/wechat-login/qr" and not post:
            from . import wechat_login
            params=parse_qs(url.query)
            return self.respond(200,wechat_login.qr(u,params.get("attempt",[""])[0],params.get("generation",[""])[0]),"image/png")
        if path=="/api/logout" and post:
            db.execute("DELETE FROM tokens WHERE digest=?",(admin.token_hash(self.token()),))
            return self.respond(200,{"ok":True},cookie=f"{self.server.session_cookie}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        if path=="/api/overview" and not post:
            return self.respond(200,overview(db,u))
        if path=="/api/my-groups" and not post:
            rows=db.execute("""SELECT g.id,COALESCE(NULLIF(p.alias,''),g.id) name,g.account,a.state,
                             COALESCE(p.detached,0) detached,g.paused,
                             EXISTS(SELECT 1 FROM membership m WHERE m.grp=g.id AND m.account=g.account) joined
                             FROM groups g JOIN account a ON a.id=g.account LEFT JOIN group_profile p ON p.grp=g.id
                             WHERE ?='系统管理员' OR g.id IN (SELECT value FROM json_each(?)) ORDER BY name,g.id""",
                            (u["role"],u["scopes"]))
            return self.respond(200,[dict(r) for r in rows])
        if path=="/api/me" and not post:
            groups=[r[0] for r in db.execute("SELECT id FROM groups ORDER BY id") if u["role"]=="系统管理员" or r[0] in json.loads(u["scopes"])]
            return self.respond(200,dict(name=u["name"],role=u["role"],groups=groups,group_aliases=group_tools.aliases(db,groups)))
        params=parse_qs(url.query)
        group=data.get("group") if post else params.get("group",[""])[0]
        admin.permitted(u,group,post)
        g=db.execute("SELECT g.*,a.mode,a.state FROM groups g JOIN account a ON a.id=g.account WHERE g.id=?",(group,)).fetchone()
        if not g:
            return self.respond(404,{"error":"群不存在"})
        if post and path in ("/api/speech/detect","/api/speech/reply"):
            from . import speech
            result=speech.detect(db,u,group,data) if path.endswith("/detect") else speech.audio_reply(db,u,group,data)
            return self.respond(200,result)
        if path=="/api/dialog-controls":
            result=models.configure_controls(db,u,group,data) if post else models.control_settings(db,u,group)
            members=db.execute("""SELECT member FROM inbox WHERE grp=? AND kind='message' AND member!=?
                                  GROUP BY member ORDER BY max(seq) DESC LIMIT 100""",(group,g["account"]))
            return self.respond(200,dict(result,members=[row[0] for row in members]))
        if path=="/api/reply-rules":
            return self.respond(200,reply_rules.configure(db,u,group,data) if post else reply_rules.settings(db,u,group))
        if path=="/api/member-notices":
            from . import member_policy
            return self.respond(200,member_policy.configure(db,u,group,data) if post else member_policy.settings(db,u,group))
        if path=="/api/voice-policy":
            from . import voice_policy
            return self.respond(200,voice_policy.configure(db,u,group,data) if post else voice_policy.settings(db,u,group))
        if post and path=="/api/voice-policy/test":
            from . import voice_policy
            return self.respond(200,voice_policy.test_credential(db,u,group,data))
        if path=="/api/group-tools":
            return self.respond(200,group_tools.configure(db,u,group,data) if post else group_tools.settings(db,u,group))
        if path=="/api/chat-model":
            result=models.configure(db,u,group,data) if post else models.settings(db,u,group)
            return self.respond(200,result)
        if path=="/api/chat-model/models" and post:
            return self.respond(200,models.list_models(db,u,group,data))
        if not post and path=="/api/status":
            counts={r[0]:r[1] for r in db.execute("SELECT state,COUNT(*) FROM outbox WHERE grp=? GROUP BY state",(group,))}
            return self.respond(200,dict(group=group,mode=g["mode"],account=g["account"],state=g["state"],binding=g["binding"],paused=g["paused"],
                version=g["version"],config=json.loads(g["config"]),received=db.execute("SELECT COUNT(*) FROM inbox WHERE grp=?",(group,)).fetchone()[0],outbox=counts))
        if not post and path in ("/api/view","/api/export"):
            rows=admin.view(db,u,group,params.get("name",["会话"])[0])
            if path.endswith("/export"):
                buf=io.StringIO()
                if rows:
                    writer=csv.writer(buf)
                    writer.writerow(rows[0].keys())
                    for row in rows:
                        writer.writerow(["'"+str(v) if str(v).lstrip().startswith(("=","+","-","@")) else v for v in row.values()])
                return self.respond(200,buf.getvalue().encode("utf-8-sig"),"text/csv")
            return self.respond(200,rows)
        if post and path=="/api/config":
            return self.respond(200,dict(version=admin.configure(db,u,group,data["version"],data["patch"])))
        if post and path=="/api/retention":
            retention.configure(db,u,group,data["notice"])
            return self.respond(200,{"ok":True})
        if post and path=="/api/recall":
            return self.respond(200,retention.read(db,u,group,int(data["seq"])))
        if post and path=="/api/schedule":
            return self.respond(201,dict(id=admin.schedule(db,u,group,data)))
        if post and path=="/api/operation":
            return self.respond(200,{"result":operations.act(db,u,group,data)})
        if post and path=="/api/switch":
            if u["role"]!="系统管理员":raise PermissionError("FORBIDDEN 仅系统管理员")
            if not isinstance(data.get("key"),str) or not 1<=len(data["key"])<=120:raise ValueError("需要幂等键")
            return self.respond(200,{"result":jobs.switch(db,group,data["target"],u["name"],data["key"])})
        if post and path=="/api/simulate":
            if g["mode"]!="simulation":
                raise ValueError("仅模拟群支持此入口")
            payload={"text":data["text"]}
            if data.get("mention") is True:
                payload["mention_account"]=g["account"]
            seq=receive(db,g["account"],group,"operator" if u["role"]=="系统管理员" else "ui-"+u["name"],data["key"],payload)
            return self.respond(202,{"seq":seq})
        if not post and path=="/api/simulation-result" and g["mode"]=="simulation":
            row=db.execute("""SELECT i.state,o.body FROM inbox i LEFT JOIN outbox o ON o.biz=i.event_id
                            WHERE i.seq=? AND i.grp=?""",(params.get("seq",["0"])[0],group)).fetchone()
            result=dict(row) if row else {}
            if result.get("body"):
                result["media"]=reply_rules.simulation_media(db,group,params.get("seq",["0"])[0])
            return self.respond(200,result)
        return self.respond(404,{"error":"接口不存在"})

    def handle_request(self):
        try:
            with closing_db(self.server.database) as db:
                self.route(db)
        except PermissionError as exc:
            self.respond(403,{"error":str(exc)})
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            msg=str(exc)
            self.respond(409 if msg.startswith("CONFLICT") else 429 if msg.startswith("RATE_LIMITED") else 400,{"error":msg[:200]})
        except sqlite3.Error:
            self.respond(503,{"error":"STORAGE_UNAVAILABLE"})
    do_GET=handle_request
    do_POST=handle_request


def server(path,port):
    name=os.environ.get("ERGOU_SESSION_COOKIE","session")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}",name):
        raise ValueError("后台会话 Cookie 名称无效")
    httpd=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    httpd.database=path
    httpd.session_cookie=name
    return httpd

