import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ergou import agent_wechat as aw, db, engine
from tests.test_agent_wechat import Fixture


class PondRaids(unittest.TestCase):
    def setUp(self):
        self.path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"game.sqlite"
        db.initialize(self.path)
        db.demo(self.path,("one","two"))
        self.db=self.enterContext(db.closing_db(self.path))
        self.db.executemany("INSERT INTO fishing_wallets(grp,member) VALUES(?,?)",
                            [("one","victim"),("one","player"),("two","victim")])
        self.db.executemany("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
                               VALUES(?,'victim','鲫鱼',205,4,?)""",[("one","pond"),("one","bag"),("two","pond")])
        self.db.execute("INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price) VALUES('one','victim','白条',90,30,5)")
        self.db.execute("""INSERT INTO asset_display_names SELECT id,binding,'victim','穿过暮光的帷幕',0
                           FROM groups WHERE id='one'""")
        self.db.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        self.counter=0

    def say(self,text,now,*,member="player",target=None,source=None):
        self.counter+=1
        payload={"text":text}
        if target:
            payload["pond_target"]=target
        seq=engine.receive(self.db,"sim-account","one",member,source or str(self.counter),payload,now=now)
        engine.step(self.db)
        row=self.db.execute("SELECT body FROM outbox JOIN inbox ON biz=event_id WHERE seq=?",(seq,)).fetchone()
        return row[0] if row else None

    def test_exact_command_transfers_only_pond_fish(self):
        cmd="偷鱼@穿过暮光的帷幕\u2005"
        for text in (cmd,"聊天里说"+cmd):
            self.assertIsNone(self.say(text,98))
        self.assertIn("选一位",self.say("二狗"+cmd,99))
        self.assertIn("自己的",self.say(cmd,99,target="player"))
        with patch("ergou.pond_raids.random.Random") as create_rng:
            create_rng.return_value.randrange.side_effect=[39,0]
            result=self.say(cmd,100,target="victim",source="hit")
            self.assertIn("穿过暮光的帷幕",result)
            self.assertIn("#1 鲫鱼",result)
            self.assertEqual(result,self.say(cmd,101,target="victim",source="hit"))
            self.assertIn("穿过暮光的帷幕的鱼塘空空如也",self.say(cmd,101,target="victim"))
            self.assertIn("空空如也",self.say(cmd,400,target="victim"))
            self.assertEqual(self.db.execute("SELECT last_attempt FROM fishing_raids WHERE member='player'").fetchone()[0],100)
        rows=list(map(tuple,self.db.execute("SELECT member,storage FROM fishing_pond ORDER BY id")))
        self.assertEqual(rows,[("player","bag"),("victim","bag"),("victim","pond")])
        self.assertEqual(self.db.execute("SELECT member FROM fishing_exhibits").fetchone()[0],"victim")
        db.initialize(self.path)
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_species WHERE member='player'").fetchone())
        self.assertFalse(self.db.execute("SELECT 1 FROM chat_requests").fetchone())

    def test_guard_cost_expiry_and_caught_fine(self):
        cmd="偷鱼 @穿过暮光的帷幕"
        self.assertIn("需要 30 积分",self.say("二狗购买保护 4小时",99,member="victim"))
        self.db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                           VALUES('one','victim',0,'奖励',30,'test','award',99,'测试')""")
        bought=self.say("二狗购买保护 4小时",100,member="victim",source="buy")
        self.assertIn("护塘成功",bought)
        self.assertEqual(bought,self.say("二狗购买保护 4小时",101,member="victim",source="buy"))
        self.assertIn("已受保护",self.say("二狗鱼塘加固12小时",101,member="victim"))
        self.assertIn("守护至",self.say("二狗鱼塘保护",102,member="victim"))
        end=100+4*3600
        self.assertIn("有人守着",self.say(cmd,end-1,target="victim"))
        self.assertEqual(self.db.execute("SELECT sum(points) FROM ledger").fetchone()[0],0)
        self.db.execute("UPDATE fishing_wallets SET coins=1 WHERE grp='one' AND member='player'")
        with patch("ergou.pond_raids.random.Random") as create_rng:
            create_rng.return_value.randrange.side_effect=[40,65]
            create_rng.return_value.randint.return_value=5
            caught=self.say(cmd,end,target="victim",source="caught")
            self.assertIn("赔给穿过暮光的帷幕 1 鱼币",caught)
            self.assertEqual(caught,self.say(cmd,end+1,target="victim",source="caught"))
            self.assertIn("1 秒",self.say(cmd,end+299,target="victim"))
            self.assertIn("空网",self.say(cmd,end+300,target="victim"))
        self.assertEqual(list(map(tuple,self.db.execute("SELECT member,coins FROM fishing_wallets WHERE grp='one' ORDER BY member"))),
                         [("player",0),("victim",31)])
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_pond").fetchone()[0],3)

    def test_full_bag_and_disabled_game(self):
        self.db.executemany("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
            VALUES('one','player','白条',30,5,'bag')""",[()]*5)
        self.assertIn("鱼包已满",self.say("偷鱼@塘主",100,target="victim"))
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_raids").fetchone())
        self.db.execute("DELETE FROM fishing_pond WHERE grp='one' AND member='victim' AND storage='pond'")
        self.db.execute("INSERT INTO fishing_raids(grp,member,protected_until) VALUES('one','victim',999)")
        self.assertIn("空空如也",self.say("偷鱼@塘主",101,target="victim"))
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_raids WHERE member='player'").fetchone())
        self.db.execute("UPDATE groups SET config=json_set(config,'$.games',0) WHERE id='one'")
        self.assertIn("关闭",self.say("偷鱼@塘主",110,target="victim"))

    def test_wechat_selected_mention_without_robot_prefix(self):
        api=Fixture()
        secret="x"*40
        aw.link(self.db,api,"测试群",secret)
        listener=aw.Listener(self.db,api,secret)
        listener.verify()
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups WHERE id=?",
                        (time.time()-2,api.room))
        self.db.execute("INSERT INTO fishing_wallets(grp,member) VALUES(?,'real-id')",(api.room,))
        self.db.execute("INSERT INTO fishing_pond(grp,member,fish,grams,price) VALUES(?,'real-id','鲫鱼',205,4)",(api.room,))
        def emit(n,mentions,body="偷鱼@穿过暮光的帷幕\u2005"):
            api.details.update(body=body,serverId=str(n),mentions=mentions,
                               createdAt=datetime.now(timezone.utc).isoformat())
            seq=listener.consume(dict(cursor=str(n),kind="message.committed",data=dict(
                threadId=api.room,messageId=api.details["id"],origin="live",direction="incoming")))
            engine.step(self.db)
            return self.db.execute("SELECT body FROM inbox JOIN outbox ON event_id=biz WHERE seq=?",(seq,)).fetchone()
        for i,metadata in enumerate([{},{"state":"unknown","userIds":["real-id"]},
                                     {"state":"known","all":True,"userIds":["real-id"]},
                                     {"state":"known","userIds":["real-id","another"]}]):
            self.assertIsNone(emit(13+i,metadata))
        with patch("ergou.pond_raids.random.Random") as rng:
            rng.return_value.randrange.side_effect=[0,0]
            reply=emit(17,{"state":"known","self":False,"all":False,"userIds":["real-id"]})
            self.assertIn("已收入你的鱼包",reply[0])
        self.assertEqual(self.db.execute("SELECT member FROM fishing_pond WHERE grp=?",(api.room,)).fetchone()[0],"member")
        for n,prefix in enumerate(("","二狗"),18):
            reply=emit(n,{"state":"known","self":False,"all":False,"userIds":["real-id"]},
                       prefix+"偷鱼\u2005@穿过暮光的帷幕")
            self.assertIn("鱼塘空空如也",reply[0])
