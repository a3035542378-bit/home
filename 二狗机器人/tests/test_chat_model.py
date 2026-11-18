import json
import os
import tempfile
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from ergou import admin, agent_wechat, jobs, models, web
from ergou.db import backup, closing_db, demo, initialize
from ergou.engine import receive, step
from tests.test_agent_wechat import Fixture


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"bot.sqlite"
        initialize(self.path)
        demo(self.path,("room","other"))
        self.db=self.enterContext(closing_db(self.path))
        self.user=dict(role="运营管理员",name="ops",scopes='["room"]')
        self.fields=dict(action="verify",version=0,provider="deepseek",model="deepseek-flash",key="private-test-credential")
        self.transport=self.enterContext(patch("ergou.models.complete",return_value="模型回答"))
        if sys.platform.startswith("linux"):
            self.enterContext(patch.dict(os.environ, {"ERGOU_CREDENTIAL_DIR": str(self.path.parent/"keys")}))
        elif os.name!="nt":
            self.enterContext(patch("ergou.models.protect",side_effect=lambda value,decrypt=False:value[::-1]))

    def save(self,**fields):
        return models.configure(self.db,self.user,"room",self.fields|fields)

    def test_verify_rotate_scope_backup(self):
        for user,group in ((self.user,"other"),(self.user|{"role":"群管理员"},"room"),(self.user|{"role":"只读人员"},"room")):
            with self.assertRaises(PermissionError):
                models.configure(self.db,user,group,self.fields)
        self.assertFalse(self.transport.called)
        state=self.save()
        self.assertNotIn("private-test",json.dumps(state))
        self.assertEqual(self.transport.call_args.args[-1],[{"role":"user","content":"连接测试，请回复 OK。"}])
        sealed=self.db.execute("SELECT credential FROM chat_models").fetchone()[0]
        self.assertNotIn(b"private-test",sealed)
        with self.assertRaises(ValueError):
            self.save(version=1,provider="qwen",key="")
        self.transport.side_effect=ValueError("供应商返回 HTTP 401")
        with self.assertRaises(ValueError):
            self.save(version=1,model="invalid",key="different")
        self.assertEqual(models.settings(self.db,self.user,"room"),state)
        self.transport.side_effect=None
        self.save(version=1,key="",model="deepseek-v4-pro")
        self.assertEqual(self.transport.call_args.args[2],self.fields["key"])
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            self.save(version=1)
        target=self.path.with_name("backup.sqlite")
        backup(self.path,target)
        with closing_db(target) as archived:
            self.assertEqual(archived.execute("SELECT COUNT(*) FROM chat_models").fetchone()[0],0)
        self.assertNotIn("private-test",str(list(map(tuple,self.db.execute("SELECT * FROM audit")))))
        self.save(action="disable",version=2)
        self.assertIsNone(self.db.execute("SELECT credential FROM chat_models").fetchone()[0])

    def test_addressing_history_and_dispatch(self):
        self.save()
        self.transport.reset_mock()
        worker=models.ChatWorker()
        def say(source,member,body,**extra):
            seq=receive(self.db,"sim-account","room",member,source,dict(text=body,**extra))
            step(self.db)
            worker.work(self.db)
            return self.db.execute("SELECT o.body FROM outbox o JOIN inbox i ON i.event_id=o.biz WHERE i.seq=?",(seq,)).fetchone()
        self.assertIsNone(say("1","a","大家在聊二狗"))
        self.assertIn("本群积分",say("2","a","二狗积分")[0])
        self.assertFalse(self.transport.called)
        say("3","a","二狗今天天气真好呀")
        say("4","b","二狗+下班啦")
        self.assertEqual(len(self.transport.call_args.args[-1]),2)
        say("5","a","@群昵称\u2005接着聊",mention_account="sim-account")
        messages=self.transport.call_args.args[-1]
        self.assertEqual([item["content"] for item in messages[1:]],["今天天气真好呀","模型回答","接着聊"])
        for i in range(20):
            say(str(i+10),"a","二狗继续")
        self.assertEqual(len(self.transport.call_args.args[-1]),34)
        with patch("ergou.models.time.time",return_value=time.time()+1801):
            say("40","a","二狗过会儿再聊")
            self.assertEqual(len(self.transport.call_args.args[-1]),2)
        self.assertFalse(self.db.execute("SELECT 1 FROM chat_requests WHERE prompt IS NOT NULL").fetchone())

    def test_native_directed_only(self):
        api=Fixture()
        secret="x"*40
        agent_wechat.link(self.db,api,"测试群",secret)
        listener=agent_wechat.Listener(self.db,api,secret)
        listener.verify()
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups WHERE id=?",
                        (time.time()-10,api.room))
        def message(n,body,at=None,**extra):
            api.details.update(body=body,serverId=str(n),createdAt=datetime.fromtimestamp(at or time.time(),timezone.utc).isoformat(),**extra)
            listener.consume(dict(cursor=str(12+n),kind="message.committed",
                                  data=dict(threadId=api.room,messageId=api.details["id"],origin="live")))
            step(self.db)
            return jobs.claim(self.db,api.account,directed_group=api.room)
        self.assertFalse(message(1,"有人提过二狗"))
        self.assertFalse(message(2,"二狗积分",at=time.time()-300))
        self.assertFalse(message(3,"@所有人 帮助",mentions=dict(state="known",self=True,all=True,userIds=[])))
        task=message(4,"@昵称\u2005积分",mentions=dict(state="known",self=True,all=False,userIds=[api.account]))
        self.assertEqual(task["body"],"本群积分 0")
        self.assertEqual(task["grp"],api.room)
        self.assertEqual(message(5,"二狗你好")["body"],"汪，在呢！想玩一局成语接龙，还是看看今天的运势？")

    def http_client(self,role="运营管理员",groups=("room",)):
        admin.user(self.db,"ops","fixture-password",role,list(groups))
        httpd=web.server(self.path,0)
        thread=threading.Thread(target=httpd.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join,2)
        self.addCleanup(httpd.shutdown)
        cookie=""
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def call(path,body=None):
            req=urllib.request.Request(f"http://127.0.0.1:{httpd.server_port}"+path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={"Content-Type":"application/json","Cookie":cookie})
            with opener.open(req,timeout=4) as r:
                return json.load(r),r.headers.get("Set-Cookie","").split(";")[0]
        _,cookie=call("/api/login",dict(name="ops",password="fixture-password"))
        return call

    def test_admin_http_and_provider_protocol(self):
        call=self.http_client()
        state,_=call("/api/chat-model?group=room")
        providers={p["id"]:p for p in state["providers"]}
        self.assertEqual(set(providers),{"deepseek","glm","qwen","openai"})
        self.assertEqual(providers["openai"]["name"],"ChatGPT（OpenAI API）")
        self.assertEqual(providers["openai"]["models"],[])
        with self.assertRaises(urllib.error.HTTPError) as forbidden:
            call("/api/chat-model?group=other")
        self.assertEqual(forbidden.exception.code,403)
        with patch("ergou.models.http.client.HTTPSConnection") as tls:
            # setUp mocks completion for the unit tests; route through the real HTTPS adapter here.
            self.transport.side_effect=OFFICIAL_COMPLETE
            response=Mock(status=401)
            tls.return_value.getresponse.return_value=response
            with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                call("/api/chat-model",dict(self.fields,group="room"))
            self.assertNotIn(self.fields["key"],unauthorized.exception.read().decode())
            self.assertIsNone(call("/api/chat-model?group=room")[0]["active"]["verified"])
            response.status=200
            response.read.return_value=b'{"choices":[{"message":{"content":"ok"}}]}'
            state,_=call("/api/chat-model",dict(self.fields,group="room"))
            self.assertTrue(state["active"]["verified"])
            call("/api/simulate",dict(group="room",text="二狗一起聊天",key="from-http"))
            step(self.db)
            models.ChatWorker().work(self.db)
            result,_=call("/api/simulation-result?seq=1&group=room")
            self.assertEqual(result["body"],"ok")
            tls.assert_called_with("api.deepseek.com",timeout=18)
            req=tls.return_value.request.call_args
            self.assertEqual(req.args,("POST","/chat/completions"))
            self.assertEqual(req.kwargs["headers"]["Authorization"],"Bearer "+self.fields["key"])
            payload=json.loads(req.kwargs["body"])
            self.assertEqual(payload["messages"][-1]["content"],"一起聊天")
            self.assertEqual(payload["max_tokens"],1024)

    def test_openai_models_then_verify_and_reply(self):
        call=self.http_client(groups=("room","other"))
        key="openai-fixture-key"
        list_fields=dict(group="room",provider="openai",key=key)
        listing="/api/chat-model/models"
        with patch("ergou.models.http.client.HTTPSConnection") as tls:
            self.transport.side_effect=OFFICIAL_COMPLETE
            conn=tls.return_value
            response=Mock(status=200)
            conn.getresponse.return_value=response
            catalog=["gpt-fixture-b","gpt-fixture-a","gpt-fixture-b"]
            response.read.return_value=json.dumps({"object":"list","data":[{"id":m,"object":"model"} for m in catalog]}).encode()
            listed,_=call(listing,list_fields)
            self.assertEqual(listed["models"],["gpt-fixture-a","gpt-fixture-b"])
            self.assertNotIn(key,json.dumps(listed))
            self.assertFalse(self.db.execute("SELECT 1 FROM chat_models").fetchone())
            self.assertEqual(tls.call_args.args,("api.openai.com",))
            request=conn.request.call_args
            self.assertEqual(request.args[:2],("GET","/v1/models"))
            self.assertEqual(request.kwargs["headers"]["Authorization"],"Bearer "+key)
            response.read.return_value=b'{"choices":[{"message":{"role":"assistant","content":"fixture reply"}}]}'
            selected=listed["models"][1]
            active,_=call("/api/chat-model",dict(list_fields,model=selected,action="verify",version=0))
            self.assertEqual((active["active"]["provider"],active["active"]["model"]),("openai",selected))
            self.assertTrue(active["active"]["verified"])
            call("/api/simulate",dict(group="room",text="二狗一起聊天",key="openai-http"))
            step(self.db)
            models.ChatWorker().work(self.db)
            reply,_=call("/api/simulation-result?seq=1&group=room")
            self.assertEqual(reply["body"],"fixture reply")
            request=conn.request.call_args
            self.assertEqual(tls.call_args.args,("api.openai.com",))
            self.assertEqual(request.args[:2],("POST","/v1/chat/completions"))
            self.assertEqual(request.kwargs["headers"]["Authorization"],"Bearer "+key)
            payload=json.loads(request.kwargs["body"])
            self.assertEqual(payload["model"],selected)
            self.assertEqual(payload["messages"][-1],{"role":"user","content":"一起聊天"})
            self.assertGreater(payload["max_completion_tokens"],0)
            self.assertNotIn("max_tokens",payload)
            response.read.return_value=b'{"object":"list","data":[]}'
            self.assertEqual(call(listing,dict(list_fields,key=""))[0]["models"],[])
            self.assertEqual(conn.request.call_args.kwargs["headers"]["Authorization"],"Bearer "+key)
            conn.request.reset_mock()
            with self.assertRaises(urllib.error.HTTPError) as no_saved_key:
                call(listing,dict(list_fields,key="",group="other"))
            self.assertEqual(no_saved_key.exception.code,400)
            conn.request.assert_not_called()
            response.status=401
            response.read.return_value=json.dumps({"error":{"message":"invalid "+key}}).encode()
            with self.assertRaises(urllib.error.HTTPError) as denied:
                call(listing,dict(list_fields,key="wrong-fixture-key"))
            self.assertNotIn(key,denied.exception.read().decode())
            self.assertEqual(call("/api/chat-model?group=room")[0]["active"],active["active"])

    def test_model_listing_enforces_operator_group_and_provider_scope(self):
        self.save()
        call=self.http_client()
        listing="/api/chat-model/models"
        with patch("ergou.models.http.client.HTTPSConnection") as tls:
            with self.assertRaises(urllib.error.HTTPError) as no_saved_key:
                call(listing,dict(group="room",provider="openai",key=""))
            self.assertEqual(no_saved_key.exception.code,400)
            with self.assertRaises(urllib.error.HTTPError) as forbidden:
                call(listing,dict(group="other",provider="openai",key="new-fixture-key"))
            self.assertEqual(forbidden.exception.code,403)
            self.db.execute("UPDATE users SET role='群管理员' WHERE name='ops'")
            with self.assertRaises(urllib.error.HTTPError) as forbidden_role:
                call(listing,dict(group="room",provider="openai",key="new-fixture-key"))
            self.assertEqual(forbidden_role.exception.code,403)
            tls.assert_not_called()


OFFICIAL_COMPLETE=models.complete
