import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from unittest.mock import patch

from ergou import admin,agent_wechat,native_voice,voice_policy,web
from ergou.db import backup,closing_db,demo,initialize,restore
from ergou.engine import receive
from tests.test_agent_wechat import Fixture
from tests.voice_credentials import preview_credential,verify_credential


class VoicePolicy(unittest.TestCase):
    def setUp(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path=root/"bot.sqlite"
        initialize(self.path)
        demo(self.path,("sim","other"))
        self.db=self.enterContext(closing_db(self.path))
        self.api=Fixture()
        self.room=self.api.room
        agent_wechat.link(self.db,self.api,"测试群","n"*40)
        self.actor={"name":"ops","role":"运营管理员","scopes":json.dumps(["sim",self.room])}
        self.enterContext(patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_KEY":"","ERGOU_BAIDU_SPEECH_TOKEN":""}))
        # Credential lifecycle is exercised here; Windows DPAPI itself is covered by test_chat_model.
        self.enterContext(patch("ergou.models.protect",side_effect=lambda value,decrypt=False:value[::-1]))

    def configure(self,group,action,**fields):
        version=voice_policy.settings(self.db,self.actor,group)["version"]
        return voice_policy.configure(self.db,self.actor,group,dict(version=version,action=action,**fields))

    def active(self):
        return voice_policy.active(self.db,self.room,self.api.account,1)

    def test_grant_requires_exact_snapshot_and_credential(self):
        self.assertFalse(self.active())
        with self.assertRaises(ValueError):voice_policy.preview(self.db,self.room)
        self.configure(self.room,"switch",enabled=True)
        preview=voice_policy.preview(self.db,self.room)
        voice_policy.approve(self.db,preview)
        self.assertFalse(self.active())
        state=verify_credential(self.db,self.actor,self.room,kind="key",secret="private-test")
        self.assertTrue(state["approved"])
        self.assertEqual(self.active(),state["version"])
        self.assertEqual(voice_policy.credentials(self.db,self.room),("private-test",""))
        self.assertNotIn("private-test",str(state))
        self.assertNotIn("private-test",str(list(map(tuple,self.db.execute("SELECT * FROM audit")))))
        self.assertNotIn(b"private-test",self.db.execute("SELECT sealed FROM voice_credentials").fetchone()[0])
        old=self.active()
        verify_credential(self.db,self.actor,self.room,kind="token",secret="second-private")
        self.assertNotEqual(self.active(),old)
        self.assertEqual(voice_policy.credentials(self.db,self.room),("","second-private"))
        self.configure(self.room,"switch",enabled=False)
        self.configure(self.room,"switch",enabled=True)
        with self.assertRaisesRegex(ValueError,"CONFLICT"):voice_policy.approve(self.db,preview)
        self.assertFalse(self.active())
        self.assertFalse(self.db.execute("SELECT 1 FROM active_native_voice").fetchone())

    def test_scopes_env_and_invalid_inputs(self):
        for role,group in (("只读人员","sim"),("群管理员","sim"),("运营管理员","other")):
            with self.assertRaises(PermissionError):
                voice_policy.configure(self.db,dict(self.actor,role=role),group,
                                       dict(action="credential",kind="key",secret="x",version=0))
        with self.assertRaises(ValueError):self.configure("sim","switch",enabled=True)
        for key in ("","secret key","secret\r\nheader","x"*4097):
            with self.assertRaises(ValueError):preview_credential(self.db,self.actor,"sim",kind="key",secret=key)
        with patch.dict(os.environ,{"ERGOU_BAIDU_SPEECH_TOKEN":"local-token"}):
            self.assertEqual(voice_policy.credentials(self.db,"sim"),("","local-token"))
            verify_credential(self.db,self.actor,"sim",kind="key",secret="override")
            self.assertEqual(voice_policy.credentials(self.db,"sim"),("override",""))
            self.assertEqual(voice_policy.credentials(self.db,self.room),("","local-token"))
            state=self.configure("sim","clear")
            self.assertEqual(state["credential_source"],"environment")
            self.assertEqual(voice_policy.credentials(self.db,"sim"),("","local-token"))

    def test_console_discloses_scope_and_requires_explicit_confirmation(self):
        verify_credential(self.db,self.actor,self.room,kind="key",secret="local-test")
        self.configure(self.room,"switch",enabled=True)
        for confirmation,expected in (("取消",False),("确认启用",True)):
            output=io.StringIO()
            with patch("builtins.input",side_effect=["1",confirmation]),redirect_stdout(output):
                voice_policy.confirm_one(self.db)
            self.assertIn(self.room,output.getvalue())
            self.assertIn("百度识别",output.getvalue())
            self.assertIn("二狗二狗",output.getvalue())
            self.assertEqual(bool(self.active()),expected)

    def test_configuration_changes_scrub_only_unfinished_voice_work(self):
        self.db.execute("INSERT INTO membership VALUES(?,?)",(self.api.account,self.room))
        verify_credential(self.db,self.actor,self.room,kind="key",secret="before")
        for turn,(action,fields) in enumerate((("switch",{"enabled":False}),("activate",{"kind":"key","secret":"replacement"}),("clear",{}))):
            with self.subTest(action=action):
                self.configure(self.room,"switch",enabled=True)
                voice_policy.approve(self.db,voice_policy.preview(self.db,self.room))
                grant=self.db.execute("SELECT * FROM active_native_voice").fetchone()
                for kind in ("voice","text","context"):
                    src=f"source-{turn}-{kind}"
                    seq=receive(self.db,self.api.account,self.room,"speaker",src,{"text":"保密测试"},
                                message_type="voice" if kind=="voice" else "text",
                                adapter_version=native_voice.VERSION if kind=="voice" else agent_wechat.VERSION)
                    self.db.execute("INSERT INTO queries(id,kind,argument,state) VALUES(?,'天气','北京','RUNNING')",(seq,))
                    self.db.execute("INSERT INTO chat_requests VALUES(?,1,'模型提问','PENDING',NULL)",(seq,))
                    self.db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
                                    SELECT event_id,account,grp,binding,'回复正文','RETRY_WAIT',0,1,0 FROM inbox WHERE seq=?""",(seq,))
                    if kind=="voice":
                        voice_seq=seq
                        self.db.execute("""INSERT INTO native_voice_events(grp,account,binding,generation,slot,server_id,
                            message_id,source,member,source_time,state,seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (self.room,self.api.account,grant["binding"],grant["generation"],grant["slot"],grant["server_id"],
                             src,src,"speaker",time.time(),"AWAKE",seq))
                    elif kind=="text":
                        text_seq=seq
                    else:
                        context_seq=seq
                        self.db.execute("UPDATE chat_requests SET state='DONE',prompt=NULL WHERE seq=?",(seq,))
                        self.db.execute("INSERT INTO chat_voice_context VALUES(?,?)",(seq,grant["generation"]))
                if action=="activate":
                    verify_credential(self.db,self.actor,self.room,**fields)
                else:
                    self.configure(self.room,action,**fields)
                def record(seq):
                    return tuple(self.db.execute("""SELECT i.state,i.payload,q.state,q.argument,c.state,c.prompt,o.state,o.body FROM inbox i
                        JOIN queries q ON i.seq=q.id JOIN chat_requests c ON i.seq=c.seq JOIN outbox o ON i.event_id=o.biz
                        WHERE i.seq=?""",(seq,)).fetchone())
                self.assertEqual(record(voice_seq),("IGNORED",None,"CANCELLED",None,"CANCELLED",None,"CANCELLED",""))
                self.assertEqual(record(context_seq),("IGNORED",None,"CANCELLED",None,"DONE",None,"CANCELLED",""))
                self.assertEqual(record(text_seq),("PENDING",'{"text":"保密测试"}',"RUNNING","北京","PENDING","模型提问","RETRY_WAIT","回复正文"))
                self.assertEqual(self.db.execute("SELECT state FROM native_voice_events WHERE seq=?",(voice_seq,)).fetchone()[0],"CANCELLED")

    def test_binding_backup_and_concurrent_changes(self):
        verify_credential(self.db,self.actor,self.room,kind="key",secret="test-key")
        self.configure(self.room,"switch",enabled=True)
        voice_policy.approve(self.db,voice_policy.preview(self.db,self.room))
        grant=self.db.execute("SELECT * FROM active_native_voice").fetchone()
        self.db.execute("INSERT INTO membership VALUES(?,?)",(self.api.account,self.room))
        seq=receive(self.db,self.api.account,self.room,"tester","123",{"text":"二狗 私密测试"},
                    message_type="voice",adapter_version=native_voice.VERSION)
        self.db.execute("""INSERT INTO native_voice_events(grp,account,binding,generation,slot,server_id,
                         message_id,source,member,source_time,state,seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (self.room,self.api.account,grant["binding"],grant["generation"],grant["slot"],
                         grant["server_id"],"msg-123","123","tester",time.time(),"AWAKE",seq))
        self.db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
                        SELECT event_id,account,grp,binding,'私密回复','PENDING',0,1,0 FROM inbox WHERE seq=?""",(seq,))
        context_seq=receive(self.db,self.api.account,self.room,"tester","456",{"text":"此前说了什么"},adapter_version=agent_wechat.VERSION)
        self.db.execute("INSERT INTO chat_requests VALUES(?,1,NULL,'DONE',NULL)",(context_seq,))
        self.db.execute("INSERT INTO chat_voice_context VALUES(?,?)",(context_seq,grant["generation"]))
        self.db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
                        SELECT event_id,account,grp,binding,'包含此前的语音','SENDING',0,1,0 FROM inbox WHERE seq=?""",(context_seq,))
        target=self.path.with_name("restore.sqlite")
        preview_credential(self.db,self.actor,self.room,kind="token",secret="unused-candidate")
        backup(self.path,target)
        restored=self.path.with_name("restored.sqlite")
        restore(target,restored)
        for path in (target,restored):
            with closing_db(path) as db:
                for table in ("voice_approvals","voice_credentials","voice_verifications","voice_test_tickets",
                              "active_native_voice","native_voice_events","chat_voice_context"):
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0],0)
                self.assertEqual(tuple(db.execute("SELECT state,payload FROM inbox WHERE seq=?",(seq,)).fetchone()),("IGNORED",None))
                self.assertEqual(list(map(tuple,db.execute("SELECT state,body FROM outbox ORDER BY id"))),[("CANCELLED",""),("UNKNOWN","")])
        self.db.execute("UPDATE groups SET binding=binding+1 WHERE id=?",(self.room,))
        self.assertFalse(voice_policy.active(self.db,self.room,self.api.account,2))
        preview=voice_policy.preview(self.db,self.room)
        self.db.execute("UPDATE agent_wechat_links SET server_id='different' WHERE grp=?",(self.room,))
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            voice_policy.approve(self.db,preview)
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            voice_policy.configure(self.db,self.actor,self.room,dict(action="clear",version=0))

    def test_http_switch_requests_do_not_grant_access(self):
        server=web.server(self.path,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join,2)
        self.addCleanup(server.shutdown)
        admin.user(self.db,"http-ops","ui-test-password","运营管理员",[self.room])
        client=build_opener(ProxyHandler({}),HTTPCookieProcessor(CookieJar()))
        def call(path,payload=None):
            req=Request(f"http://127.0.0.1:{server.server_port}"+path,
                        data=json.dumps(payload).encode() if payload is not None else None,
                        headers={"Content-Type":"application/json"})
            with client.open(req,timeout=4) as response:
                return json.load(response)
        path="/api/voice-policy"
        with self.assertRaises(HTTPError) as error:
            call(path+"?"+urlencode({"group":self.room}))
        self.assertEqual(error.exception.code,401)
        call("/api/login",dict(name="http-ops",password="ui-test-password"))
        with self.assertRaises(HTTPError) as error:call(path+"?group=other")
        self.assertEqual(error.exception.code,403)
        query=path+"?"+urlencode({"group":self.room})
        state=call(query)
        self.assertTrue(state["native"])
        with self.assertRaises(HTTPError) as error:
            call(path,dict(group=self.room,action="credential",kind="key",secret="sample-key",version=state["version"]))
        self.assertEqual(error.exception.code,400)
        self.assertEqual(state,call(query))
        state=call(path,dict(group=self.room,action="switch",enabled=True,version=state["version"]))
        self.assertEqual(state["status"],"等待本机确认")
        self.assertFalse(self.active())
        with self.assertRaises(HTTPError) as error:
            call(path,dict(group=self.room,action="clear",version=0))
        self.assertEqual(error.exception.code,409)
        self.assertEqual(state,call(query))
        for asset in ("/","/app.js","/voice.js"):
            with client.open(f"http://127.0.0.1:{server.server_port}"+asset,timeout=4) as response:
                self.assertIn(b"voice",response.read())
