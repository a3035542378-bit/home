import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ergou import agent_wechat, db, engine, models
from ergou.fishing_waters import FISH, WATERS
from tests.test_agent_wechat import Fixture


class MobileRouter(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"router.sqlite"
        db.initialize(path)
        self.db=self.enterContext(db.closing_db(path))
        self.api=Fixture()
        secret="fixture"*8
        agent_wechat.link(self.db,self.api,"测试群",secret)
        self.listener=agent_wechat.Listener(self.db,self.api,secret)
        self.listener.verify()
        group=self.api.room
        self.db.execute("INSERT INTO directed_groups VALUES(?,?,1,?)",(group,self.api.account,time.time()-60))
        self.db.execute("INSERT INTO chat_models VALUES(?,1,'glm','fixture',?,?)",(group,b'fixture',time.time()))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES(?,1,1)",(group,))
        self.seq=12

    def send(self,text,mention=False,all_members=False):
        self.seq+=1
        self.api.details.update(body=text,serverId=str(self.seq),createdAt=datetime.now(timezone.utc).isoformat(),
            mentions=dict(state='known',self=mention,all=all_members,userIds=[self.api.account] if mention else []))
        seq=self.listener.consume(dict(cursor=str(self.seq),kind="message.committed",
            data=dict(threadId=self.api.room,messageId=self.api.details["id"],origin="live",direction="incoming")))
        engine.step(self.db)
        row=self.db.execute("SELECT body FROM inbox JOIN outbox ON event_id=biz WHERE seq=?",(seq,)).fetchone()
        return row[0] if row else None

    def test_missing_water_and_switch(self):
        guide=self.send("二狗换图")
        self.assertEqual(guide,self.send("二狗 换地图"))
        self.assertEqual(guide,self.send("二狗去高级场"))
        self.assertEqual(guide,self.send("二狗我想换一个更高级的钓场"))
        for area in WATERS:
            self.assertIn(area,guide)
        self.assertIn("发送「二狗切换钓场 新手池塘」即可切换。",guide)
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_waters").fetchone())
        self.assertIn("荷花湿地",self.send("二狗换图 荷花湿地"))
        self.assertIn("当前　荷花湿地",self.send("二狗换钓场"))

    def test_fishing_aliases(self):
        menu=self.send("二狗钓鱼菜单")
        self.assertIn("二狗抛竿",menu)
        self.assertIn(f"{len(FISH)} 种",menu)
        self.assertEqual(menu,self.send("二狗怎么钓鱼"))
        self.assertEqual(self.send("二狗看鱼"),self.send("二狗背包"))
        self.assertEqual(self.send("二狗我背包里都有什么鱼呀"),self.send("二狗背包"))

    def test_unaddressed_chat_never_enters_inbox(self):
        self.assertIsNone(self.send("大家晚上好"))
        self.assertIsNone(self.send("@二狗 卖#17"))
        self.assertIsNone(self.send("@所有人 大家晚上好",True,True))
        for table in ("inbox","outbox","chat_requests","hits"):
            self.assertFalse(self.db.execute(f"SELECT 1 FROM {table}").fetchone(),table)
        self.assertEqual(int(self.listener.cursor),self.seq)

    def test_local_guidance_and_sale(self):
        self.assertEqual(self.send("二狗乱写一通"),engine.UNKNOWN_COMMAND.format(prefix="二狗"))
        self.assertIn("二狗天气 北京",self.send("二狗今天天气真好"))
        self.assertIn("编号",self.send("二狗卖"))
        self.assertFalse(self.db.execute("SELECT 1 FROM queries").fetchone())
        key=(self.api.room,self.api.details["senderId"])
        self.db.execute("INSERT OR IGNORE INTO fishing_wallets(grp,member) VALUES(?,?)",key)
        self.db.execute("INSERT INTO fishing_pond(id,grp,member,fish,grams,price,storage) VALUES(17,?,?,'鲫鱼',205,4,'bag')",key)
        for phrase in ("别卖17号鱼","卖#17？"):
            self.send("二狗"+phrase)
            self.assertTrue(self.db.execute("SELECT 1 FROM fishing_pond WHERE id=17").fetchone())
        self.assertIn("4",self.send("二狗卖17号鱼"))
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_pond WHERE id=17").fetchone())
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()[0],34)
        self.assertFalse(self.db.execute("SELECT 1 FROM chat_requests").fetchone())

    def test_fallback_and_real_mention(self):
        self.assertEqual(self.send("二狗瞎写的乱码"),engine.UNKNOWN_COMMAND.format(prefix="二狗"))
        self.assertIsNone(self.send("@二狗 瞎写的乱码"))
        self.assertIsNone(self.send("@所有人 瞎写的乱码",True,True))
        self.assertFalse(self.db.execute("SELECT 1 FROM chat_requests").fetchone())
        self.assertIsNone(self.send("@二狗\u2005聊聊周末吧",True))
        self.assertEqual(self.db.execute("SELECT prompt FROM chat_requests").fetchone()[0],"聊聊周末吧")
        for cmd in ("瞎写的乱码","积分","抛竿","菜单","有什么功能？","G01重置"):
            self.assertIsNone(self.send("@二狗\u2005"+cmd,True))
        prompts=[r[0] for r in self.db.execute("SELECT prompt FROM chat_requests ORDER BY seq")]
        self.assertEqual(prompts,["聊聊周末吧","瞎写的乱码","积分","抛竿","菜单","有什么功能？","G01重置"])
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_pond").fetchone())
        self.db.execute("UPDATE smart_controls SET enabled=0")
        self.assertEqual(self.send("@二狗\u2005积分",True),self.send("二狗积分"))
        self.assertEqual(self.send("@二狗\u2005切换钓场",True),self.send("二狗切换钓场"))
        self.assertEqual(self.send("@二狗\u2005瞎写的乱码",True),engine.UNKNOWN_COMMAND.format(prefix="二狗"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM chat_requests").fetchone()[0],len(prompts))
