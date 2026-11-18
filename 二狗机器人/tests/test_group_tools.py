import tempfile
import time
import unittest
from pathlib import Path

from ergou import bridge, group_tools
from ergou.db import closing_db, demo, initialize, transaction
from ergou.engine import receive


class GroupToolsTests(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"group.sqlite"
        initialize(path)
        demo(path,("a","b"))
        self.db=self.enterContext(closing_db(path))
        self.operator=dict(name="staff",role="运营管理员",scopes='["a"]')
        self.vers=0

    def update(self,action,**fields):
        result=group_tools.configure(self.db,self.operator,"a",dict(action=action,version=self.vers,**fields))
        self.vers=result["version"]
        return result

    def message(self,group,member,source):
        seq=receive(self.db,"sim-account",group,member,source,dict(text="二狗兑换"))
        return self.db.execute("SELECT * FROM inbox WHERE seq=?",(seq,)).fetchone()

    def credit(self,group,member,amount):
        self.db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                          VALUES(?,?,0,'调分',?,'manual','seed',?,'测试')""",(group,member,amount,time.time()))

    def test_statistics_alias_and_authority(self):
        for group,member,key,word in [("a","甲","1","你好"),("a","甲","2","你好"),("a","乙","3","游戏"),("b","丙","4","别群")]:
            event=self.message(group,member,key)
            self.db.execute("INSERT INTO reply_rule_hits(seq,keyword) VALUES(?,?)",(event["seq"],word))
            self.db.execute("UPDATE inbox SET state='DONE',payload=NULL WHERE seq=?",(event["seq"],))
        state=self.update("alias",alias=" 家庭群 ")
        self.assertEqual(group_tools.aliases(self.db,["a"]),{"a":"家庭群"})
        self.assertEqual(group_tools.aliases(self.db,["b"]),{})
        self.assertEqual(state["daily"][-1]["users"],2)
        self.assertEqual(state["daily"][-1]["processed"],3)
        self.assertEqual(state["keywords"],[dict(keyword="你好",hits=2),dict(keyword="游戏",hits=1)])
        with self.assertRaises(PermissionError):
            group_tools.settings(self.db,self.operator,"b")
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            group_tools.configure(self.db,self.operator,"a",dict(action="alias",version=0,alias="old"))
        with self.assertRaises(PermissionError):
            group_tools.configure(self.db,dict(self.operator,role="只读人员"),"a",dict(action="alias",version=1,alias=""))

    def test_redemption_once_with_snapshot_and_fulfillment(self):
        self.update("offer",name="选片权",price=10)
        event=self.message("a","叶子","兑换1")
        self.credit("b","叶子",100)
        with self.assertRaisesRegex(ValueError,"本群有 0 分"),transaction(self.db):
            group_tools.redeem(self.db,event,"选片权")
        self.credit("a","叶子",15)
        with transaction(self.db):
            group_tools.redeem(self.db,event,"选片权")
            group_tools.redeem(self.db,event,"选片权")
        self.assertEqual(self.db.execute("SELECT SUM(points) FROM ledger WHERE grp='a'").fetchone()[0],5)
        order=self.update("offer",name="选片权",price=20)["orders"][0]
        self.assertEqual(order["price"],10)
        self.assertTrue(self.update("fulfill",id=order["id"])["orders"][0]["fulfilled"])
        with self.assertRaisesRegex(ValueError,"CONFLICT"):
            self.update("fulfill",id=order["id"])

    def test_detach_requires_current_confirmation_and_stops_regrant(self):
        self.message("b","甲","b1")
        self.message("a","甲","a1")
        secret="t"*32
        bridge.enroll(self.db,"adapter","a",secret)
        bridge.enroll(self.db,"adapter","b",secret)
        heartbeat=dict(state="ONLINE",actual_account="adapter",groups=["a","b"],adapter_version="test",
                       capabilities=dict(receive=True,stable_ids=True,send=True))
        bridge.endpoint(self.db,"heartbeat",secret,heartbeat)
        with self.assertRaisesRegex(ValueError,"请确认"):
            self.update("detach",confirm="b",binding=1)
        self.assertTrue(self.update("detach",confirm="a",binding=1)["detached"])
        bridge.endpoint(self.db,"heartbeat",secret,heartbeat)
        self.assertEqual([r[0] for r in self.db.execute("SELECT grp FROM membership WHERE account='adapter'")],["b"])
        self.assertEqual(tuple(self.db.execute("SELECT paused,binding FROM groups WHERE id='a'").fetchone()),(1,2))
        self.assertEqual(self.db.execute("SELECT state FROM inbox WHERE grp='a'").fetchone()[0],"IGNORED")
        self.assertEqual(self.db.execute("SELECT state FROM inbox WHERE grp='b'").fetchone()[0],"PENDING")
