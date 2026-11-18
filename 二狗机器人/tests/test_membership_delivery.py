import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from ergou import agent_wechat, jobs, member_notices, member_policy, native_roster
from ergou.db import closing_db, initialize
from tests.test_agent_wechat import Fixture


class MembershipDelivery(unittest.TestCase):
    """Exercise durable snapshot -> native receipt validation without using a WeChat account."""

    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"members.sqlite"
        initialize(path)
        self.db=self.enterContext(closing_db(path))
        self.admin={"name":"test-owner","role":"系统管理员","scopes":"[]"}
        self.one=self.add_room("one")
        self.two=self.add_room("two")

    def add_room(self,name):
        api=Fixture()
        api.slot=name
        api.base="/v1/accounts/"+name
        api.account="self-"+name
        api.room=name+"@chatroom"
        api.member=Mock(return_value=True)
        secret=(name+"-")*16
        agent_wechat.link(self.db,api,"测试群",secret)
        agent_wechat.Listener(self.db,api,secret).verify()
        return api

    def set_kind(self,api,kind,enabled,approve=False):
        settings=member_policy.settings(self.db,self.admin,api.room)
        item=next(x for x in settings["items"] if x["kind"]==kind)
        member_policy.configure(self.db,self.admin,api.room,dict(kind=kind,enabled=enabled,version=item["version"]))
        if approve:
            member_policy.approve(self.db,member_policy.preview(self.db,api.room,kind))

    def snapshot(self,api,op,people,stream="continuous"):
        binding=self.db.execute("SELECT binding FROM groups WHERE id=?",(api.room,)).fetchone()[0]
        policy=member_policy.active(self.db,api.room,api.account,binding)
        return native_roster.apply_snapshot(self.db,api.room,api.account,binding,"daemon-id",stream,policy,op,
                                            {api.account:"二狗",**people},time.time())

    def claim(self,api):
        return jobs.claim(self.db,api.account,directed_group=api.room)

    def test_two_native_rooms_and_independent_notifications(self):
        self.set_kind(self.one,"join",True)
        self.assertFalse(agent_wechat.recovery_plan(self.db,self.one.slot)["replies"])
        member_policy.approve(self.db,member_policy.preview(self.db,self.one.room,"join"))
        self.set_kind(self.two,"leave",True,approve=True)
        for api in (self.one,self.two):
            self.assertTrue(agent_wechat.recovery_plan(self.db,api.slot)["replies"])
            self.snapshot(api,"baseline",{"old":"老成员"})
            self.assertFalse(self.claim(api))
            self.snapshot(api,"change",{"new":"新成员"})
            self.snapshot(api,"change",{"new":"新成员"})
        for api,kind,name in ((self.one,"join","新成员"),(self.two,"leave","老成员")):
            task=self.claim(api)
            self.assertIsInstance(task,dict)
            self.assertEqual((task["account"],task["grp"]),(api.account,api.room))
            self.assertIn(name,task["body"])
            self.assertEqual(self.db.execute("SELECT kind FROM native_member_deliveries WHERE task=?",
                                             (task["id"],)).fetchone()[0],kind)
            self.assertTrue(member_notices.matches(self.db,task))
            self.assertFalse(member_notices.matches(self.db,dict(task,body="任意其他文字")))
            jobs.finish(self.db,api.account,task["id"],task["attempt"],"ACKNOWLEDGED","测试回执")
            self.assertFalse(self.claim(api))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],2)

    def test_stream_reset_and_withdrawal_before_post(self):
        api=self.one
        self.set_kind(api,"join",True,approve=True)
        self.set_kind(api,"leave",True,approve=True)
        self.snapshot(api,"baseline",{"old":"老成员"})
        self.snapshot(api,"after-reconnect",{"offline":"离线期间入群者"},"new-connection")
        self.assertFalse(self.claim(api))
        self.snapshot(api,"first-live",{"offline":"离线期间入群者","next":"新成员"},"new-connection")
        task=self.claim(api)
        self.assertTrue(member_notices.matches(self.db,task))
        self.set_kind(api,"join",False)
        self.assertFalse(member_notices.matches(self.db,task))
        jobs.finish(self.db,api.account,task["id"],task["attempt"],"FAILED","已撤销")
        self.set_kind(api,"join",True)
        self.assertFalse(member_notices.matches(self.db,task))
        member_policy.approve(self.db,member_policy.preview(self.db,api.room,"join"))
        self.assertFalse(member_notices.matches(self.db,task))
        self.snapshot(api,"post-approval",{"offline":"离线期间入群者","next":"新成员"},"new-connection")
        self.snapshot(api,"member-left",{"next":"新成员"},"new-connection")
        departure=self.claim(api)
        self.assertTrue(member_notices.matches(self.db,departure))
        self.assertIn("离线期间入群者",departure["body"])

    def test_disabling_one_kind_cancels_only_that_groups_unsent_jobs(self):
        for api in (self.one,self.two):
            self.set_kind(api,"join",True,approve=True)
            self.set_kind(api,"leave",True,approve=True)
            self.snapshot(api,"baseline",{"old":"老成员"})
            self.snapshot(api,"updated",{"new":"新成员"})
        self.set_kind(self.one,"join",False)
        rows=self.db.execute("""SELECT o.grp,d.kind,o.state,o.body FROM outbox o
                             JOIN native_member_deliveries d ON d.task=o.id""").fetchall()
        states={(r["grp"],r["kind"]):(r["state"],r["body"]) for r in rows}
        self.assertEqual(states.pop((self.one.room,"join")),("CANCELLED",""))
        self.assertEqual(len(states),3)
        self.assertTrue(all(state=="PENDING" and body for state,body in states.values()))
        first=self.claim(self.one)
        self.assertIn("老成员",first["body"])
        self.assertTrue(member_notices.matches(self.db,first))
