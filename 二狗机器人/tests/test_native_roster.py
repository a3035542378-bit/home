from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

from ergou import agent_wechat as aw, member_policy, native_roster as nr
from ergou.db import closing_db,initialize
from tests.test_agent_wechat import Fixture


class RosterContract(unittest.TestCase):
    def setUp(self):
        self.client=Mock(slot="slot",base="/v1/accounts/slot")
        self.op=dict(id="op",accountId="slot",kind="metadata",state="succeeded",
                     result=dict(completeRoster=True,memberCount=2))
        self.page=dict(coverage={"partial":False},sourceGeneration="generation",asOfEventCursor="52",nextCursor=None,
                       items=[dict(id="me",username="me",nickname="甲"),
                              dict(id="other",username="other",nickname="乙",roomDisplayName="小乙",displayName="私密备注")])

    def fetch(self):
        return nr.fetch_snapshot(self.client,"group@chatroom","me",lambda:None,
                                 start=lambda c,g:self.op,wait=lambda seconds:None)

    def test_operation_and_full_stable_pagination(self):
        complete=deepcopy(self.op)
        self.op["state"]="queued"
        page_one=self.page|{"items":self.page["items"][:1],"nextCursor":"after/++"}
        page_two=self.page|{"items":self.page["items"][1:]}
        self.client.get.side_effect=[complete,page_one,page_two]
        self.assertEqual(self.fetch(),("op",{"me":"甲","other":"小乙"}))
        urls=[call.args[0] for call in self.client.get.call_args_list]
        self.assertTrue(urls[0].endswith("/operations/op"))
        self.assertIn("/groups/group%40chatroom/members?",urls[1])
        self.assertIn("cursor=after%2F%2B%2B",urls[2])

    def test_reject_partial_or_inconsistent_evidence(self):
        for bad in ({"coverage":{"partial":True}},{"sourceGeneration":None},{"items":self.page["items"][1:]},
                    {"items":[self.page["items"][0],self.page["items"][0]]},{"items":[{},{}]}):
            with self.subTest(bad=bad),self.assertRaises(nr.RosterError):
                self.client.get.return_value=self.page|bad
                self.fetch()
        self.client.get.side_effect=[self.page|{"nextCursor":"c","items":self.page["items"][:1]},
                                    self.page|{"sourceGeneration":"changed","items":self.page["items"][1:]}]
        with self.assertRaisesRegex(nr.RosterError,"版本发生变化"):
            self.fetch()
        self.op["result"]["completeRoster"]=False
        with self.assertRaisesRegex(nr.RosterError,"完整成员名册"):
            self.fetch()

    def test_only_live_member_updates_request_refresh(self):
        data=dict(groupId="g",source="remote_sync_refresh",membersRefreshed=True,origin="live")
        def relevant(**kwargs):
            return nr.is_member_event(dict(kind="group.updated",data=data|kwargs),"g")
        self.assertTrue(relevant())
        for update in (dict(source="metadata_refresh"),dict(groupId="other"),dict(origin="history"),dict(membersRefreshed=False)):
            self.assertFalse(relevant(**update))


class RosterUpdates(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"db.sqlite"
        initialize(path)
        self.db=self.enterContext(closing_db(path))
        self.api=Fixture()
        self.secret="r"*40
        aw.link(self.db,self.api,"测试群",self.secret)
        self.listener=aw.Listener(self.db,self.api,self.secret)
        self.listener.verify()
        self.user=dict(name="ops",role="系统管理员",scopes="[]")
        self.now=time.time()

    def policy(self):
        return member_policy.active(self.db,self.api.room,self.api.account,1)

    def enable(self,kind):
        member_policy.configure(self.db,self.user,self.api.room,dict(kind=kind,version=0,enabled=True))
        member_policy.approve(self.db,member_policy.preview(self.db,self.api.room,kind))

    def apply(self,op,people,continuity="first",extra_time=0):
        return nr.apply_snapshot(self.db,self.api.room,self.api.account,1,"daemon-id",continuity,self.policy(),op,
                                 {"account":"我"}|people,self.now+extra_time)

    def count(self):
        return self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def test_independent_generations_and_reconnect(self):
        self.assertFalse(self.apply("zero",{"p":"原有"}))
        self.enable("join")
        self.apply("op1",{"p":"原有"})
        self.assertEqual(self.count(),0)
        self.enable("leave")
        self.apply("op2",{"q":"新成员"})
        self.assertEqual(self.count(),1)
        self.apply("op3",{"q":"改昵称"})
        self.assertEqual(self.count(),1)
        self.apply("op4",{})
        self.apply("op4",{})
        self.assertEqual(self.count(),2)
        self.assertIn("改昵称",self.db.execute("SELECT body FROM outbox ORDER BY id DESC").fetchone()[0])
        self.apply("op5",{"r":"离线期间加入"},"reconnected")
        self.apply("op6",{},"reconnected",extra_time=nr.POLL_INTERVAL*3)
        self.assertEqual(self.count(),2)

    def test_failed_batch_rolls_back_snapshot_and_notifications(self):
        self.enable("join")
        self.apply("op1",{})
        from ergou import member_notices
        original=member_notices.enqueue
        def interrupted(*args):
            original(*args)
            raise ValueError("注入的测试故障")
        with patch.object(member_notices,"enqueue",side_effect=interrupted),self.assertRaises(ValueError):
            self.apply("op2",{"x":"乙"})
        self.assertEqual(self.count(),0)
        self.apply("op2",{"x":"乙"})
        self.assertEqual(self.count(),1)

    def test_disabled_monitor_never_reads_member_list(self):
        monitor=nr.Monitor(self.listener)
        inspected=threading.Event()
        real_policy=monitor.policy
        def observed_policy(db):
            result=real_policy(db)
            inspected.set()
            return result
        with patch.object(nr,"fetch_snapshot") as reader,patch.object(monitor,"policy",side_effect=observed_policy):
            monitor.thread.start()
            try:
                monitor.online()
                monitor.signal_event(dict(kind="group.updated",data=dict(groupId=self.api.room,source="remote_sync_refresh",
                                         origin="live",membersRefreshed=True)))
                self.assertTrue(inspected.wait(3))
            finally:
                monitor.close()
            reader.assert_not_called()

    def test_background_refresh_and_disconnected_inflight_discard(self):
        self.enable("join")
        monitor=nr.Monitor(self.listener)
        applied=threading.Event()
        fetching=threading.Event()
        proceed=threading.Event()
        calls=[]
        real_apply=nr.apply_snapshot
        def record(*args):
            result=real_apply(*args)
            applied.set()
            return result
        def read(client,group,account,check):
            calls.append(group)
            if len(calls)==2:
                fetching.set()
                self.assertTrue(proceed.wait(3))
            check()
            return f"op{len(calls)}",{account:"自己","x":"甲"} if len(calls)==1 else {account:"自己","y":"乙"}
        event=dict(kind="group.updated",data=dict(groupId=self.api.room,source="remote_sync_refresh",origin="live",
                                                  membersRefreshed=True))
        with patch.object(nr,"fetch_snapshot",side_effect=read),patch.object(nr,"apply_snapshot",side_effect=record),patch.object(nr,"MIN_REFRESH",0):
            monitor.thread.start()
            try:
                monitor.online()
                self.assertTrue(applied.wait(4))
                applied.clear()
                monitor.signal_event(event)
                self.assertTrue(fetching.wait(4))
                monitor.offline()
                monitor.online()
                proceed.set()
                self.assertTrue(applied.wait(6))
                self.assertEqual(calls,[self.api.room]*3)
                self.assertEqual(self.count(),0)
            finally:
                proceed.set()
                monitor.close()

    def test_asset_refresh_without_notice_policy(self):
        from ergou import asset_roster,operations
        group=self.listener.group
        monitor=nr.Monitor(self.listener)
        grant=dict(action="发放货币",target="silent",points=2,currency="积分",reason="fixture",key="one")
        for _ in range(3):
            self.assertIsNone(asset_roster.candidates(self.db,group,False))
        with patch.object(nr,"fetch_snapshot",return_value=("complete",{self.listener.account:"自己","silent":"静默成员"})) as reader:
            monitor.thread.start()
            try:
                monitor.online()
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and not self.db.execute("SELECT 1 FROM asset_rosters").fetchone():
                    time.sleep(.02)
                reader.assert_called_once()
                result=operations.act(self.db,self.user,group,grant)
                for col,value in (("session","old"),("binding",2),("account","old"),("observed",time.time()-nr.MIN_REFRESH)):
                    self.db.execute("SAVEPOINT probe")
                    self.db.execute(f"UPDATE asset_rosters SET {col}=?",(value,))
                    with self.assertRaisesRegex(ValueError,"名册无效"):
                        asset_roster.require_member(self.db,group,"silent")
                    self.db.execute("ROLLBACK TO probe")
                    self.db.execute("RELEASE probe")
                monitor.offline()
                self.assertEqual(operations.act(self.db,self.user,group,grant),result)
                with self.assertRaisesRegex(ValueError,"名册无效"):
                    operations.act(self.db,self.user,group,grant|dict(key="two"))
                monitor.online()
                self.assertIsNone(asset_roster.verified(self.db,group))
                self.assertEqual(self.count(),0)
            finally:
                monitor.close()

    def test_membership_change_then_failed_refresh_never_reuses_snapshot(self):
        from ergou import asset_roster
        group=self.listener.group
        monitor=nr.Monitor(self.listener)
        failed=threading.Event()
        def second_read(*args):
            failed.set()
            raise nr.RosterError("隔离刷新失败")
        with patch.object(nr,"MIN_REFRESH",0),patch.object(nr,"fetch_snapshot",
                return_value=("v1",{self.listener.account:"自己","p":"甲"})) as reader:
            asset_roster.candidates(self.db,group,False)
            monitor.thread.start()
            try:
                monitor.online()
                end=time.monotonic()+5
                while not self.db.execute("SELECT 1 FROM asset_rosters").fetchone() and time.monotonic()<end:
                    time.sleep(.02)
                self.assertIn("p",asset_roster.verified(self.db,group))
                reader.side_effect=second_read
                monitor.signal_event(dict(kind="group.updated",data=dict(groupId=group,source="remote_sync_refresh",
                                          membersRefreshed=True,origin="live")))
                self.assertIsNone(asset_roster.candidates(self.db,group,False))
                self.assertTrue(failed.wait(5))
                self.assertIsNone(asset_roster.verified(self.db,group))
            finally:
                monitor.close()
