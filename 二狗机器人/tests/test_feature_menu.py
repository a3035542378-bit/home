import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ergou import admin, agent_wechat, models, reply_rules
from ergou.db import closing_db, demo, initialize
from ergou.engine import receive, step
from tests.test_agent_wechat import Fixture
from tests.test_reply_rules import rule


class FeatureMenuTests(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"menu.sqlite"
        initialize(path)
        demo(path,("room","other"))
        self.db=self.enterContext(closing_db(path))
        self.admin=dict(role="系统管理员",name="operator",scopes="[]")
        self.source=0
        self.model=self.enterContext(patch("ergou.models.submit",side_effect=AssertionError("菜单不应进入模型队列")))

    def say(self,text,member="reader",group="room"):
        self.source+=1
        seq=receive(self.db,"sim-account",group,member,str(self.source),{"text":text})
        self.assertTrue(step(self.db))
        return self.body(seq)

    def body(self,seq):
        row=self.db.execute("SELECT o.body FROM inbox i JOIN outbox o ON o.biz=i.event_id WHERE i.seq=?",(seq,)).fetchone()
        return row["body"] if row else None

    def test_addressed_menu_and_help_with_existing_rules(self):
        admin.configure(self.db,self.admin,"room",1,{"aliases":{"菜单":"帮助"}})
        menu=self.say("二狗菜单")
        for command in ("天气","快递","百科","菜谱","点歌","运势","星座","积分","周榜","月榜",
                        "总榜","兑换","群规","游戏列表","加入","投票","抽签","故事","笑话"):
            with self.subTest(command=command):
                self.assertIn(command,menu)
        self.assertEqual(self.say("二狗 帮助"),menu)
        reply_rules.configure(self.db,self.admin,"room",dict(version=0,rules=[
            rule("菜单","自定义关键词内容",mode="contains"),rule("帮助","本群的帮助信息")
        ]))
        for command in ("二狗 菜单","二狗功能菜单","二狗全部功能"):
            self.assertIn("游戏列表",self.say(command))
        self.assertEqual(self.say("二狗帮助"),"本群的帮助信息")
        self.assertIsNone(self.say("今晚聚餐的菜单"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],6)
        for table in ("games","ledger","queries","chat_requests"):
            self.assertFalse(self.db.execute("SELECT 1 FROM "+table).fetchone())
        self.model.assert_not_called()

    def test_commands_follow_group_settings_and_member_permissions(self):
        models.configure_controls(self.db,self.admin,"room",dict(version=0,admins=["model-manager"]))
        member=self.say("二狗菜单")
        game_admin=self.say("二狗菜单",member="operator")
        model_admin=self.say("二狗菜单",member="model-manager")
        for command in ("投票 创建","抽签 重抽"):
            self.assertIn(command,game_admin)
            self.assertNotIn(command,member)
            self.assertNotIn(command,model_admin)
        for command in ("开启智能对话","关闭智能对话"):
            self.assertIn(command,model_admin)
            self.assertNotIn(command,member)
            self.assertNotIn(command,game_admin)
        admin.configure(self.db,self.admin,"other",1,dict(games=False,polls=False,draws=False,prefix="团团"))
        other=self.say("团团菜单",group="other",member="operator")
        self.assertIn("团团",other)
        for command in ("游戏列表","投票 V","投票 创建","抽签 报名","抽签 重抽"):
            self.assertNotIn(command,other)
        self.assertEqual(self.say("二狗菜单"),member)

    def test_menu_reflects_model_readiness_without_invoking_it(self):
        unconfigured=self.say("二狗菜单")
        self.db.execute("INSERT INTO chat_models VALUES('room',1,'openai','private-model',?,?)",(b"fixture-key",time.time()))
        enabled=self.say("二狗菜单")
        self.db.execute("INSERT INTO smart_controls(grp,enabled) VALUES('room',0)")
        disabled=self.say("二狗菜单")
        self.assertNotEqual(unconfigured,enabled)
        self.assertNotEqual(disabled,enabled)
        self.assertIn("积分",disabled)
        self.model.assert_not_called()

    def test_native_mention_requires_verified_mention_and_sends_once(self):
        api=Fixture()
        secret="k"*40
        agent_wechat.link(self.db,api,"测试群",secret)
        listener=agent_wechat.Listener(self.db,api,secret)
        listener.verify()
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups WHERE id=?",(time.time()-2,api.room))
        admin.configure(self.db,self.admin,api.room,1,dict(prefix="团团"))
        def emit(number,mentions):
            api.details.update(body="@群里昵称\u2005菜单",serverId=str(number),mentions=mentions,
                               createdAt=datetime.now(timezone.utc).isoformat())
            event=dict(cursor=str(number),kind="message.committed",data=dict(
                       threadId=api.room,messageId=api.details["id"],origin="live",direction="incoming"))
            seq=listener.consume(event)
            self.assertTrue(step(self.db))
            listener.consume(event)
            self.assertFalse(step(self.db))
            return self.body(seq)
        self.assertIsNone(emit(13,dict(state="known",self=False,all=False,userIds=["other"])))
        posted=emit(14,dict(state="known",self=True,all=False,userIds=[api.account]))
        self.assertIn("二狗",posted)
        self.assertNotIn("团团",posted)
        self.assertIn("游戏列表",posted)
        self.assertEqual(self.db.execute("SELECT count(*) FROM outbox WHERE grp=?",(api.room,)).fetchone()[0],1)
