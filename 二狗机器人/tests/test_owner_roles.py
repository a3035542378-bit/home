import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import unquote

from deploy import group_stream
from ergou import agent_wechat, db, engine, roles
from tests.test_agent_wechat import Fixture


class OwnerRoles(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"roles.sqlite"
        db.initialize(path)
        self.db=self.enterContext(db.closing_db(path))
        self.api=Fixture()
        self.group=self.api.room
        self.bot=self.api.account
        self.secret="fixture"*8
        self.chief="chief"
        get=self.api.get

        def plugin(path):
            if path.endswith("/groups/test%40chatroom"):
                return {"id":self.group,"ownerId":self.chief,"isInGroup":True,"name":"测试群"}
            if "/members/" in path:
                uid=unquote(path.rsplit("/",1)[1])
                return {"groupId":self.group,"state":"present","username":uid,"member":{"username":uid,"nickname":uid+"昵称"}}
            return get(path)

        self.api.get=plugin
        agent_wechat.link(self.db,self.api,"测试群",self.secret)
        self.db.execute("INSERT INTO directed_groups VALUES(?,?,1,?)",(self.group,self.bot,time.time()-60))
        self.db.execute("INSERT INTO bot_owner(bot_id,owner_user_id,bound_at) VALUES(?,'parent',?)",(self.bot,time.time()))
        self.db.execute("INSERT INTO binding_streams SELECT slot,account,server_id,cursor FROM agent_wechat_links")
        stream=self.db.execute("SELECT * FROM binding_streams").fetchone()
        self.worker=group_stream.Stream(self.db,self.api,self.secret,None,stream)
        self.worker.rosters=Mock()
        self.worker.verify()
        self.cursor=13

    def say(self,sender,cmd,target=None,private=False):
        self.cursor+=1
        room=sender if private else self.group
        self.api.details.update(threadId=room,body="二狗"+cmd+(" @某人" if target else ""),
            senderId=sender,serverId=str(self.cursor),mentions=dict(state="known",self=False,userIds=[target] if target else []),
            createdAt=datetime.now(timezone.utc).isoformat())
        event=dict(cursor=str(self.cursor),kind="message.committed",data=dict(threadId=room,messageId=self.api.details["id"],origin="live",direction="incoming"))
        self.worker.consume(event)
        if private:
            return self.db.execute("SELECT body FROM role_notices WHERE source=?",(str(self.cursor),)).fetchone()[0]
        self.assertTrue(engine.step(self.db))
        return self.db.execute("SELECT body FROM outbox JOIN inbox ON inbox.event_id=outbox.biz WHERE source=?",(str(self.cursor),)).fetchone()[0]

    def test_pending_owner_cannot_grant_admin(self):
        self.assertIn("尚未获得主人授权",self.say("chief","授权管理员","member"))

    def test_authorized_owner_can_grant_admin(self):
        self.assertIn("已授权群主",self.say("parent","授权群主"))
        self.assertIn("已授权管理员",self.say("chief","授权管理员","member"))
        self.assertEqual(roles.role(self.db,self.bot,self.group,"member"),"admin")
        self.assertIn("权限不足",self.say("member","授权群主"))
        self.assertIn("权限不足",self.say("member","取消管理员","other"))

    def test_revoke_blocks_game_reset_even_for_game_initiator(self):
        self.say("parent","授权群主")
        self.say("chief","开始 成语接龙")
        self.say("parent","取消群主授权")
        self.assertIn("尚未获得主人授权",self.say("chief","G01重置"))
        self.assertIn("尚未获得主人授权",self.say("chief","结束G01"))

    def test_owner_change_invalidates_old_and_new(self):
        self.say("parent","授权群主")
        self.chief="successor"
        self.assertIn("尚未获得主人授权",self.say("successor","本群设置"))
        self.assertIn("权限不足",self.say("chief","本群设置"))
        self.assertIn("当前群主",self.say("parent","授权群主","chief"))

    def test_member_cannot_appoint(self):
        self.assertIn("权限不足",self.say("member","授权管理员","other"))
        self.assertFalse(self.db.execute("SELECT 1 FROM group_member_role").fetchone())

    def test_revoke_audit_once(self):
        self.say("parent","授权群主")
        self.assertIn("待授权",self.say("parent","取消群主授权"))
        self.say("parent","取消群主授权")
        self.assertEqual(tuple(self.db.execute("""SELECT count(*),actor_id,target_id FROM permission_audit_log
            WHERE action='revoke_group_owner'""").fetchone()),(1,"parent","chief"))

    def test_transfer_preserves_grants_and_private_management(self):
        self.say("parent","授权群主")
        self.assertIn("主人已转移",self.say("parent","主人转移","next"))
        self.assertEqual(roles.role(self.db,self.bot,self.group,"chief"),"group_owner_granted")
        self.assertIn("权限不足",self.say("parent","群主授权列表"))
        self.assertIn("测试群",self.say("next","群主授权列表",private=True))
        self.assertIn("待授权",self.say("next","管理群 #1 取消群主授权",private=True))
