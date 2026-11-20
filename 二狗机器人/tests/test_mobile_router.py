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
        self.assertIn("二狗卖鱼#17", self.send("二狗卖鱼"))
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

    def follow(self,reply):
        command=next(line for line in reply.splitlines() if line.startswith("二狗"))
        return self.send(command)

    def test_from_empty_to_full_and_storing_the_suggested_fish(self):
        from unittest.mock import patch
        prompt=self.send("二狗卖鱼")
        with patch("ergou.angler.slip_percent",return_value=0), patch("ergou.giant_fish.encounter",return_value=None), patch("ergou.fishing.fight",return_value=None):
            start=time.time()
            for n in range(5):
                with patch("time.time",return_value=start+21*n):
                    self.listener.verify()
                    catch=self.follow(prompt) if n==0 else self.send("二狗抛竿")
                    self.assertIn("上钩",catch)
            self.assertIn("鱼包已满",catch)
            full=self.send("二狗抛竿")
            self.assertIn("腾出 1 格",full)
            bag=self.follow(full)
            self.assertIn("可把 #5",bag)
            self.assertIn("已将 #5",self.follow(bag))
            blocked=self.send("二狗放入鱼塘")
            self.assertIn("鱼塘已满（1/1 条）",blocked)
            self.assertIn("#5",self.follow(blocked))
            self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_pond WHERE storage='bag'").fetchone()[0],4)

    def test_broken_line_recovery_and_scoped_single_sale(self):
        key=(self.api.room,self.api.details["senderId"])
        self.db.execute("INSERT INTO fishing_wallets(grp,member,coins) VALUES(?,?,1)",key)
        self.db.execute("INSERT INTO fishing_tackle VALUES(?,?,1,0)",key)
        self.db.execute("INSERT INTO fishing_waters VALUES(?,?,'外海')",key)
        self.db.execute("INSERT INTO fishing_wallets(grp,member) VALUES(?,'neighbor')",(key[0],))
        self.db.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
                           VALUES(?,'neighbor','白条',40,3,'bag')""",(key[0],))
        repair=self.send("二狗买鱼线")
        self.assertIn("还差 2 币",repair)
        self.assertIn("新手池塘",self.follow(repair))
        starter=self.send("二狗买鱼线")
        self.assertEqual(starter.splitlines()[1],"二狗抛竿")
        self.db.execute("INSERT INTO fishing_pond(id,grp,member,fish,grams,price,storage) VALUES(42,?,?,'鲫鱼',205,4,'bag')",key)
        preview=self.follow(self.send("二狗买鱼线"))
        self.assertIn("#42 鲫鱼 · 4 鱼币，发送即卖出",preview)
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()[0],1)
        self.assertIn("到账 4",self.follow(preview))
        repair=self.send("二狗鱼线")
        self.assertIn("换线扣 3 鱼币",repair)
        self.assertIn("消耗 3 鱼币",self.follow(repair))
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()[0],2)

    def test_bulk_sale_preview_matches_entire_bag_and_leaves_pond(self):
        key=(self.api.room,self.api.details["senderId"])
        self.db.execute("INSERT INTO fishing_wallets(grp,member) VALUES(?,?)",key)
        for storage in ["bag"]*7+["pond"]:
            self.db.execute("INSERT INTO fishing_pond(grp,member,fish,grams,price,storage) VALUES(?,?,'鲫鱼',205,4,?)",(*key,storage))
        bag=self.send("二狗查看鱼包")
        self.assertIn("共 7 条，当前 28 鱼币",bag)
        lines=bag.splitlines()
        bulk=lines[next(i for i,l in enumerate(lines) if l.startswith("全部出售"))+1]
        self.assertIn("到账 28",self.send(bulk))
        self.assertEqual(tuple(self.db.execute("SELECT storage,count(*) FROM fishing_pond GROUP BY storage").fetchone()),("pond",1))

    def test_weather_points_unknown_and_disabled_followups(self):
        group=self.api.room
        self.db.execute("UPDATE groups SET config=json_set(config,'$.prefix','团团') WHERE id=?",(group,))
        self.db.execute("INSERT INTO weather_cache VALUES('北京',?,'北京：晴')",(time.time(),))
        self.assertIn("北京：晴",self.follow(self.send("二狗天气")))
        self.db.execute("UPDATE groups SET config=json_set(config,'$.city','北京') WHERE id=?",(group,))
        self.assertIn("北京：晴",self.send("二狗天气"))
        self.db.execute("INSERT INTO reward_offers VALUES(?,'选片权',5)",(group,))
        poor=self.send("二狗兑换 选片权")
        self.assertIn("还差 5 分",poor)
        self.assertIn("成语接龙",self.follow(poor))
        self.db.execute("UPDATE groups SET config=json_set(config,'$.games',json('false')) WHERE id=?",(group,))
        self.assertIn("本群积分 0",self.follow(self.send("二狗兑换 选片权")))
        self.assertIsNone(self.db.execute("SELECT 1 FROM redemptions").fetchone())
        for msg in ("二狗乱写一通","二狗抛竿"):
            menu=self.follow(self.send(msg))
            self.assertIn("二狗菜单",menu)
            self.assertNotIn("二狗抛竿",menu)
        self.assertIsNone(self.send("今晚去钓鱼吗"))
        self.assertIsNone(self.db.execute("SELECT 1 FROM chat_requests").fetchone())

    def test_breeding_guide_leads_to_available_upgrade_then_real_pond(self):
        from ergou import breed_metrics, pond_growth
        group=self.api.room
        self.assertIn("未开启",self.send("二狗繁育配对"))
        breed_metrics.switch(self.db,group,True,time.time())
        key=(group,self.api.details["senderId"])
        self.db.execute("INSERT INTO fishing_wallets(grp,member,coins) VALUES(?,?,20)",key)
        for storage in ("pond","bag"):
            item=self.db.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,grade,storage)
                                VALUES(?,?,'鲫鱼',900,7,0,?)""",(*key,storage)).lastrowid
            pond_growth.register(self.db,item)
        guide=self.send("二狗繁育配对")
        self.assertIn("需 20 鱼币",guide)
        self.assertIn("可放 4 条",self.follow(guide))
        self.assertIn("已将 #2",self.follow(self.send("二狗繁育配对")))
        quote=self.follow(self.send("二狗繁育配对"))
        self.assertIn("确认后扣费",quote)
        self.assertFalse(self.db.execute("SELECT 1 FROM breed_pairs").fetchone())

    def test_empty_bag_after_sale_during_cooldown_has_usable_action(self):
        from unittest.mock import patch
        with patch("ergou.giant_fish.encounter",return_value=None), patch("ergou.fishing.fight",return_value=None):
            self.send("二狗抛竿")
        self.send("二狗卖出鱼包")
        empty=self.send("二狗卖鱼")
        self.assertIn("再等",empty)
        self.assertIn("我的钓鱼信息",self.follow(empty))
