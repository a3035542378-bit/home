import json
import tempfile
import time
import unittest
from pathlib import Path

from ergou import agent_wechat,member_policy
from ergou.db import backup,closing_db,demo,initialize
from tests.test_agent_wechat import Fixture


class MemberPolicy(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path=self.root/"robot.sqlite"
        initialize(self.path)
        demo(self.path,("sim","sibling"))
        self.db=self.enterContext(closing_db(self.path))
        self.api=Fixture()
        agent_wechat.link(self.db,self.api,"测试群","n"*40)
        self.admin=dict(name="system",role="系统管理员",scopes="[]")

    def items(self,group):
        return {item["kind"]:item for item in member_policy.settings(self.db,self.admin,group)["items"]}

    def change(self,group,kind,value):
        version=self.items(group)[kind]["version"]
        return member_policy.configure(self.db,self.admin,group,dict(kind=kind,enabled=value,version=version))

    def test_two_independent_real_approvals(self):
        group=self.api.room
        self.assertFalse(any(item["requested"] for item in self.items(group).values()))
        self.change(group,"join",True)
        join=member_policy.preview(self.db,group,"join")
        self.change(group,"leave",True)
        self.assertFalse(self.items(group)["join"]["enabled"])
        member_policy.approve(self.db,join)
        active=self.items(group)
        self.assertTrue(active["join"]["enabled"])
        self.assertFalse(active["leave"]["enabled"])
        member_policy.approve(self.db,member_policy.preview(self.db,group,"leave"))
        self.change(group,"join",False)
        self.change(group,"join",True)
        self.assertTrue(self.items(group)["leave"]["enabled"])
        self.assertFalse(self.items(group)["join"]["enabled"])
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            member_policy.approve(self.db,join)
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            member_policy.configure(self.db,self.admin,group,dict(kind="join",enabled=False,version=1))

    def test_rebind_and_backup_invalidate(self):
        group=self.api.room
        self.change(group,"leave",True)
        member_policy.approve(self.db,member_policy.preview(self.db,group,"leave"))
        backup(self.path,self.root/"archive.sqlite")
        with closing_db(self.root/"archive.sqlite") as db:
            self.assertFalse(db.execute("SELECT 1 FROM member_notice_approvals").fetchone())
        self.db.execute("UPDATE groups SET binding=binding+1 WHERE id=?",(group,))
        self.assertFalse(self.items(group)["leave"]["enabled"])
        snapshot=member_policy.preview(self.db,group,"leave")
        self.db.execute("UPDATE agent_wechat_links SET server_id='changed' WHERE grp=?",(group,))
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            member_policy.approve(self.db,snapshot)

    def test_roster_status_is_generation_scoped(self):
        group=self.api.room
        for kind in ("join","leave"):
            self.change(group,kind,True)
            member_policy.approve(self.db,member_policy.preview(self.db,group,kind))
        state=self.items(group)
        observed=time.time()
        self.db.execute("INSERT INTO native_rosters VALUES(?,?,?,?,?,?,?,?,?)",
                        (group,self.api.slot,self.api.account,1,"daemon-id","connection",
                         json.dumps({"join":state["join"]["version"]}),'{"private-id":"private-name"}',observed))
        result=member_policy.settings(self.db,self.admin,group)
        self.assertEqual(result["observed"],observed)
        self.assertTrue(self.items(group)["join"]["baseline_ready"])
        self.assertFalse(self.items(group)["leave"]["baseline_ready"])
        self.assertNotIn("private-",str(result))

    def test_simulation_and_role_scope(self):
        self.assertTrue(self.items("sim")["join"]["enabled"])
        self.assertFalse(self.items("sim")["leave"]["enabled"])
        self.change("sim","leave",True)
        self.assertTrue(self.items("sim")["leave"]["enabled"])
        self.assertFalse(self.items("sibling")["leave"]["enabled"])
        fields=dict(kind="join",enabled=False,version=0)
        with self.assertRaises(PermissionError):
            member_policy.configure(self.db,dict(role="群管理员",scopes='["sim"]'),"sim",fields)
        with self.assertRaises(PermissionError):
            member_policy.configure(self.db,dict(role="运营管理员",scopes='["sibling"]'),"sim",fields)
        with self.assertRaises(ValueError):
            member_policy.preview(self.db,"sim","leave")
