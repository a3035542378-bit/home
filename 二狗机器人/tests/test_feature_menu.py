import tempfile
import time
import unittest
import unicodedata
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
        full=self.say("二狗全菜单")
        for command in ("天气帮助","生活帮助","点歌帮助","积分帮助","群服务帮助",
                        "游戏帮助","互动帮助","聊天帮助","鱼包帮助","强化帮助"):
            with self.subTest(command=command):
                self.assertIn(command,full)
        self.assertEqual(self.say("二狗 帮助"),menu)
        reply_rules.configure(self.db,self.admin,"room",dict(version=0,rules=[
            rule("菜单","自定义关键词内容",mode="contains"),rule("帮助","本群的帮助信息")
        ]))
        for command in ("二狗 菜单","二狗功能菜单","二狗全部功能"):
            self.assertIn("游戏",self.say(command))
        self.assertEqual(self.say("二狗帮助"),menu)
        self.assertIsNone(self.say("今晚聚餐的菜单"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],7)
        for table in ("games","ledger","queries","chat_requests"):
            self.assertFalse(self.db.execute("SELECT 1 FROM "+table).fetchone())
        self.model.assert_not_called()

    def test_commands_follow_group_settings_and_member_permissions(self):
        models.configure_controls(self.db,self.admin,"room",dict(version=0,admins=["model-manager"]))
        self.db.execute("INSERT INTO chat_models VALUES('room',1,'glm','fixture',?,100)",(b"test",))
        member=self.say("二狗管理帮助")
        game_admin=self.say("二狗管理帮助",member="operator")
        model_admin=self.say("二狗管理帮助",member="model-manager")
        for command in ("投票 创建","抽签 重抽"):
            self.assertIn(command,game_admin)
            self.assertNotIn(command,member)
            self.assertNotIn(command,model_admin)
        for command in ("开启智能对话","关闭智能对话"):
            self.assertIn(command,model_admin)
            self.assertNotIn(command,member)
            self.assertNotIn(command,game_admin)
        admin.configure(self.db,self.admin,"other",1,dict(games=False,polls=False,draws=False,prefix="团团"))
        other=self.say("团团全菜单",group="other",member="operator")
        self.assertIn("团团",other)
        for command in ("游戏列表","投票 V","投票 创建","抽签 报名","抽签 重抽"):
            self.assertNotIn(command,other)
        self.assertEqual(self.say("二狗管理帮助"),member)

    def test_first_screen_and_api_mode_explanation(self):
        self.db.execute("INSERT INTO chat_models VALUES('room',1,'openai','model',?,?)",(b"key",time.time()))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('room',1,1)")
        menu=self.say("二狗菜单")
        first=menu
        self.assertLessEqual(len(first.splitlines()),24)
        for line in menu.splitlines():
            width=sum(2 if unicodedata.east_asian_width(c) in ("W","F") else 1 for c in line)
            self.assertLessEqual(width,40,line)
        for command in ("积分帮助","天气帮助","点歌帮助","游戏帮助","群服务帮助","互动帮助"):
            self.assertIn(command,first)
        self.assertIn("二狗全菜单",first)
        self.assertNotIn("@ 我",menu)
        self.assertNotIn("G01",menu)
        self.assertIn("【游戏帮助】",self.say("二狗全菜单"))

    def test_fishing_discovery_walkthrough(self):
        for group,prefix in (("room","二狗"),("other","团团")):
            if group=="other":
                admin.configure(self.db,self.admin,group,1,dict(prefix=prefix))
                self.db.execute("INSERT INTO chat_models VALUES('other',1,'glm','test',?,100)",(b"test",))
                self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('other',1,1)")
            def ask(cmd):
                return self.say(prefix+cmd,group=group)
            self.assertIn("【钓鱼帮助】",ask("菜单"))
            self.assertIn("【抛竿】",ask("游戏列表"))
            guide=ask("钓鱼玩法")
            self.assertEqual(guide,ask("怎么钓鱼？"))
            for cmd in ("抛竿","鱼包帮助","钓场帮助","护塘帮助","图鉴帮助","装备帮助"):
                self.assertIn(f"【{cmd}】",guide)
            self.assertIn("升级鱼线",ask("钓鱼进阶"))
            self.assertIsNone(self.db.execute("SELECT 1 FROM fishing_wallets WHERE grp=?",(group,)).fetchone())
            self.assertEqual(prefix+"查看鱼包",ask("抛竿").splitlines()[-1])
            self.assertIn("1/5",ask("查看鱼包"))
        self.db.execute("UPDATE groups SET config=json_set(config,'$.disabled_games',json_array('钓鱼')) WHERE id='room'")
        self.assertNotIn("钓鱼玩法",self.say("二狗菜单"))
        self.assertNotIn("钓鱼玩法",self.say("二狗游戏列表"))
        self.assertIn("未开启",self.say("二狗钓鱼帮助"))
        self.model.assert_not_called()

    def test_menu_reflects_model_readiness_without_invoking_it(self):
        unconfigured=self.say("二狗全菜单")
        self.db.execute("INSERT INTO chat_models VALUES('room',1,'openai','private-model',?,?)",(b"fixture-key",time.time()))
        enabled=self.say("二狗全菜单")
        self.db.execute("INSERT INTO smart_controls(grp,enabled) VALUES('room',0)")
        disabled=self.say("二狗全菜单")
        self.assertNotEqual(unconfigured,enabled)
        self.assertNotEqual(disabled,enabled)
        self.assertIn("积分",disabled)
        self.model.assert_not_called()

    def test_reward_list_shows_a_command_for_this_group(self):
        admin.configure(self.db,self.admin,"other",1,dict(prefix="团团"))
        self.db.execute("INSERT INTO reward_offers VALUES('other','选片权',5)")
        self.assertIn("团团积分",self.say("团团兑换列表",group="other"))
        self.db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                           VALUES('other','reader',0,'奖励',5,'fixture','credit',1,'测试')""")
        reply=self.say("团团兑换列表",group="other")
        self.assertEqual(reply.splitlines()[-1],"团团兑换 选片权")
        self.assertFalse(self.db.execute("SELECT 1 FROM redemptions").fetchone())
        self.assertIn("剩余 0 分",self.say(reply.splitlines()[-1],group="other"))

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
            self.assertEqual(step(self.db),seq is not None)
            listener.consume(event)
            self.assertFalse(step(self.db))
            return self.body(seq) if seq is not None else None
        self.assertIsNone(emit(13,dict(state="known",self=False,all=False,userIds=["other"])))
        posted=emit(14,dict(state="known",self=True,all=False,userIds=[api.account]))
        self.assertIn("二狗",posted)
        self.assertIn("团团全菜单",posted)
        self.assertIn("游戏帮助",posted)
        self.assertEqual(self.db.execute("SELECT count(*) FROM outbox WHERE grp=?",(api.room,)).fetchone()[0],1)
