import json
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ergou import admin, agent_wechat, group_tools, jobs, models, queries, web
from ergou.db import closing_db, demo, initialize
from ergou.engine import receive, step
from tests.test_agent_wechat import Fixture


class SmartSwitchTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"bot.sqlite"
        initialize(self.path)
        demo(self.path,("room","other"))
        self.db=self.enterContext(closing_db(self.path))
        self.operator=dict(name="ops",role="运营管理员",scopes='["room"]')
        self.seq=0
        self.configure()

    def configure(self):
        return models.configure_controls(self.db,self.operator,"room",dict(version=0,admins=["wxid_a"]))

    def verified(self):
        self.db.execute("INSERT INTO chat_models VALUES('room',1,'glm','test',?,?)",(b"fixture",time.time()))

    def say(self,cmd,member="wxid_a",group="room",mentioned=True,at=None):
        self.seq+=1
        data={"text":"@群昵称\u2005"+cmd if mentioned else cmd}
        if mentioned:
            data["mention_account"]="sim-account"
        seq=receive(self.db,"sim-account",group,member,str(self.seq),data,now=at)
        step(self.db)
        row=self.db.execute("SELECT o.body FROM inbox i LEFT JOIN outbox o ON o.biz=i.event_id WHERE i.seq=?",(seq,)).fetchone()
        return row["body"]

    def test_authorization_and_verified_credentials_survive(self):
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            self.configure()
        with self.assertRaises(PermissionError):
            models.configure_controls(self.db,self.operator,"other",dict(version=0,admins=["wxid_a"]))
        self.assertIn("先在本群后台",self.say("开启智能对话"))
        self.verified()
        before=self.db.execute("SELECT * FROM chat_models").fetchone()
        self.assertIsNone(self.say("@二狗 关闭智能对话",mentioned=False))
        self.assertIn("点名",self.say("二狗关闭智能对话",mentioned=False))
        self.assertIn("管理员",self.say("关闭智能对话","other-member"))
        self.assertIn("管理员",self.say("关闭智能对话",group="other"))
        self.assertTrue(models.control_settings(self.db,self.operator,"room")["enabled"])
        self.assertIn("已关闭",self.say("关闭智能对话"))
        self.assertIn("积分",self.say("积分"))
        self.assertFalse(models.control_settings(self.db,self.operator,"room")["enabled"])
        self.assertEqual(tuple(before),tuple(self.db.execute("SELECT * FROM chat_models").fetchone()))
        self.assertIn("已开启",self.say("开启智能对话"))
        self.assertTrue(models.control_settings(self.db,self.operator,"room")["enabled"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM audit WHERE action='群内切换智能对话'").fetchone()[0],2)

    def test_off_cancels_ready_and_running_answers_and_context(self):
        self.verified()
        worker=models.ChatWorker()
        with patch("ergou.models.protect",return_value=b"fake-key"),patch("ergou.models.complete",return_value="第一次") as send:
            self.say("聊一聊电影")
            worker.work(self.db)
            self.say("聊一聊音乐")
            send.side_effect=lambda *args:self.say("关闭智能对话") or "第二次"
            worker.work(self.db)
            self.assertEqual(self.db.execute("SELECT count(*) FROM outbox WHERE state='PENDING' AND body='第一次'").fetchone()[0],0)
            self.assertEqual(self.db.execute("SELECT count(*) FROM chat_requests WHERE state='CANCELLED'").fetchone()[0],2)
            self.say("开启智能对话")
            self.say("重新认识下")
            send.side_effect=None
            worker.work(self.db)
            self.assertEqual(len(send.call_args.args[-1]),2)

    def test_local_followups_expire_and_isolate(self):
        self.verified()
        self.say("关闭智能对话")
        with patch("ergou.models.complete",side_effect=AssertionError("本地闲聊不调用供应商")):
            first=self.say("讲个故事")
            self.assertIn("花盆",first)
            self.assertIn("小青蛙",self.say("然后呢"))
            self.assertNotIn("小青蛙",self.say("然后呢","other-member"))
            self.assertNotIn("小青蛙",self.say("然后呢",group="other"))
            future=time.time()+1805
            self.assertNotIn("小伞",self.say("然后呢",at=future))
            for n in range(20):
                self.say("讲个笑话",at=future+(n+1)*5)
            count=self.db.execute("SELECT count(*) FROM local_turns WHERE grp='room' AND member='wxid_a'").fetchone()[0]
            self.assertEqual(count,16)

    def test_native_expired_control_and_unlinked_events(self):
        api=Fixture()
        secret="x"*40
        agent_wechat.link(self.db,api,"测试群",secret)
        listener=agent_wechat.Listener(self.db,api,secret)
        listener.verify()
        self.db.execute("INSERT INTO smart_controls(grp,admins) VALUES(?,?)",(api.room,'["member"]'))
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups WHERE id=?",(time.time()-3600,api.room))
        event=dict(cursor="13",kind="message.committed",data=dict(threadId=api.room,messageId=api.details["id"],origin="live"))
        api.details.update(body="@群昵称\u2005关闭智能对话",createdAt="2020-01-01T00:00:00Z",
                           mentions=dict(state="known",self=True,all=False,userIds=[api.account]))
        listener.consume(event)
        step(self.db)
        self.assertEqual(self.db.execute("SELECT enabled FROM smart_controls WHERE grp=?",(api.room,)).fetchone()[0],1)
        self.db.execute("DELETE FROM agent_wechat_links")
        api.reads.clear()
        with self.assertRaises(agent_wechat.LinkRemoved):
            listener.consume(event|dict(cursor="14"))
        self.assertFalse(api.reads)

    def test_http_operators_to_native_mentions_and_replies(self):
        api=Fixture()
        secret="k"*40
        agent_wechat.link(self.db,api,"测试群",secret)
        listener=agent_wechat.Listener(self.db,api,secret)
        listener.verify()
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups WHERE id=?",(time.time()-2,api.room))
        admin.user(self.db,"operator","fixture-password","运营管理员",[api.room])
        srv=web.server(self.path,0)
        thread=threading.Thread(target=srv.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor())
        def post(path,**fields):
            request=urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/api/"+path,
                        data=json.dumps(fields).encode(),headers={"Content-Type":"application/json"})
            with client.open(request,timeout=4) as response:
                return json.load(response)
        post("login",name="operator",password="fixture-password")
        post("dialog-controls",group=api.room,admins=["member"],version=0)
        with patch("ergou.models.protect",return_value=b"test"),patch("ergou.models.complete",return_value="OK"):
            post("chat-model",group=api.room,provider="glm",model="glm-test",key="fake",version=0,action="verify")
        def emit(n,body,mentions):
            api.details.update(body=body,serverId=str(n),mentions=mentions,createdAt=datetime.now(timezone.utc).isoformat())
            seq=listener.consume(dict(cursor=str(n),kind="message.committed",
                        data=dict(threadId=api.room,messageId=api.details["id"],origin="live")))
            step(self.db)
            return self.db.execute("SELECT o.body FROM inbox i LEFT JOIN outbox o ON o.biz=i.event_id WHERE i.seq=?",(seq,)).fetchone()[0]
        own=dict(state="known",self=True,all=False,userIds=[api.account])
        self.assertIn("已关闭",emit(13,"＠二 狗\u2005关闭智能对话",own))
        self.assertIsNone(emit(14,"@所有人\u2005开启智能对话",dict(own,all=True,userIds=[])))
        self.assertIsNone(emit(15,"@二狗 开启智能对话",dict(own,state="unknown",self=None,userIds=[])))
        scoped=dict(self.operator,scopes=json.dumps([api.room]))
        self.assertFalse(models.control_settings(self.db,scoped,api.room)["enabled"])
        self.assertIn("已开启",emit(16,"开启智能对话@二 狗\u2005",own))
        self.assertTrue(models.control_settings(self.db,scoped,api.room)["enabled"])
        self.assertIn("已关闭",emit(17,"@甲\u2005关闭智能对话 @二 狗\u2005",dict(own,userIds=["another",api.account])))
        task=jobs.claim(self.db,api.account,directed_group=api.room)
        self.assertEqual(task["grp"],api.room)
        self.assertIn("已关闭",task["body"])

    def test_safe_failure_categories_in_operator_log(self):
        self.verified()
        self.say("今天聊点什么")
        with patch("ergou.models.protect",return_value=b"secret"),patch("ergou.models.complete",side_effect=models.ModelError("密钥验证失败","raw secret should stay private")):
            models.ChatWorker().work(self.db)
        self.say("天气 北京")
        def unavailable(*args):
            raise queries.ProviderError("供应商鉴权失败")
        queries.work(self.db,unavailable)
        self.db.execute("INSERT INTO reply_rule_sets VALUES('room',1,'invalid-rule-contents')")
        self.assertIn("运营人员",self.say("部分私密文字"))
        logs=group_tools.settings(self.db,self.operator,"room")["errors"]
        self.assertEqual({(r["kind"],r["detail"]) for r in logs},
                         {("模型请求","密钥验证失败"),("天气","供应商鉴权失败"),("回复规则","规则格式异常")})
        for text in ("secret","北京","部分私密","invalid-rule"):
            self.assertNotIn(text,str(logs))
