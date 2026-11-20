import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from ergou import asset_actions, db, engine, fish_grades, fish_storage, pond_growth as growth
from tools.pond_week import report


class PondGrowthTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory()))/"game.db"
        db.initialize(self.path)
        db.demo(self.path,("one","two"))
        self.con = self.enterContext(db.closing_db(self.path))
        self.key = ("one","member")
        self.con.executemany("INSERT INTO fishing_wallets(grp,member,coins) VALUES(?,?,1000)",
                             [self.key,("one","other"),("two","member")])
        self.seq = 0

    def put(self, grams=1200, price=12, name="鲤鱼", key=None, grade=0):
        return self.con.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,grade,storage)
            VALUES(?,?,?,?,?,?,'bag')""",(*(key or self.key),name,grams,price,grade)).lastrowid

    def say(self, text, now, key=None, target=None):
        self.seq += 1
        group,member = key or self.key
        seq = engine.receive(self.con,"sim-account",group,member,str(self.seq),
                             {"text":"二狗"+text,"pond_target":target},now=now)
        engine.step(self.con)
        return self.con.execute("SELECT body FROM outbox JOIN inbox ON event_id=biz WHERE seq=?",(seq,)).fetchone()[0]

    def state(self,item):
        return dict(self.con.execute("SELECT * FROM pond_growth WHERE item=?",(item,)).fetchone())

    def coins(self):
        return self.con.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",self.key).fetchone()[0]

    def test_timer_duplicate_feed_restart_and_sale(self):
        fish = self.put(price=57)
        self.assertIn("成长位",self.say(f"放入鱼塘#{fish}",100))
        self.assertIn("没有",self.say(f"投喂#{fish}",101,("two","member")))
        self.assertIn("没有",self.say(f"投喂#{fish}",101,("one","other")))
        self.assertEqual(asset_actions.participants("投喂#1","a",None,db.DEFAULT),("a",))
        self.assertIn("已投喂",self.say(f"投喂#{fish}",102))
        balance = self.coins()
        self.assertIn("还有 3 轮",self.say(f"投喂#{fish}",103))
        self.assertEqual(self.coins(),balance)
        self.say("鱼塘",279)
        self.assertEqual(self.state(fish)["rounds"],0)
        self.assertIn("这次长了",self.say("鱼塘",280))
        state = self.state(fish)
        self.assertEqual((state["rounds"],state["food"],state["fed_segment"]),(1,2,1))
        db.initialize(self.path)
        self.assertNotIn("这次长了",self.say("鱼塘",280))
        self.assertEqual(self.state(fish),state)
        self.assertIn("已定型",self.say("鱼塘",86600))
        final = self.state(fish)
        grams,price = self.con.execute("SELECT grams,price FROM fishing_pond").fetchone()
        self.assertTrue(final["rounds"] == 10 or grams == 1560)
        self.assertGreaterEqual(price,57)
        self.assertIn(str(balance+price),self.say("资产榜",86610))
        self.assertIn("已定型",self.say(f"投喂#{fish}",86611))
        self.assertIn(f"到账 {price} 枚",self.say(f"卖鱼#{fish}",86612))
        self.assertEqual(self.coins(),balance+price)
        self.assertFalse(self.con.execute("SELECT 1 FROM pond_growth").fetchone())

    def test_stored_estimate_independent_of_polling_and_lifetime_grade_limit(self):
        self.assertEqual([fish_grades.price("鲫鱼",205,q) for q in range(5)],[4,6,9,16,27])
        self.assertEqual([fish_grades.price("鲤鱼",w,3) for w in (12000,25000)],[34,51])
        fish = self.put()
        self.say("放入鱼塘#1",100)
        self.say("投喂#1",101)
        self.con.execute("SAVEPOINT replay")
        for i in range(1,11):
            growth.settle(self.con,"one",100+180*i,"member")
        polled = self.state(fish)
        estimate = tuple(self.con.execute("SELECT grams,price,grade FROM fishing_pond").fetchone())
        self.con.execute("ROLLBACK TO replay")
        growth.settle(self.con,"one",100000,"member")
        self.assertEqual(self.state(fish),polled)
        self.assertEqual(tuple(self.con.execute("SELECT grams,price,grade FROM fishing_pond").fetchone()),estimate)
        self.con.execute("RELEASE replay")
        rng = unittest.mock.Mock()
        rng.random.return_value = 0
        rng.randint.return_value = 1
        for initial,expected in [(2,3),(3,4),(4,4),(5,5)]:
            state=dict(original_grams=1200,food=0,first_fed=0,rounds=0,fed_segment=0,appearance=0,promoted=0)
            grams,grade=1200,initial
            for _ in range(10):
                grams,grade=growth.advance("鲤鱼",state,grams,grade,5,rng)
            self.assertEqual(grade,expected)
            self.assertLessEqual(state["promoted"],1)

    def test_old_stock_giants_and_immediate_cap(self):
        for grams in (24000,26000,1200):
            self.put(grams,777)
        self.con.execute("UPDATE fishing_pond SET storage='pond'")
        self.con.execute("INSERT INTO fishing_storage_levels VALUES(?,?,'pond',5)",self.key)
        self.con.execute("DELETE FROM pond_migrations")
        with patch("ergou.db.time.time",return_value=100):
            db.initialize(self.path)
        self.assertEqual(growth.cap("鲤鱼",24000),25000)
        self.assertEqual(growth.cap("鲤鱼",1200),1560)
        self.assertEqual(growth.cap("鲤鱼",26000),26000)
        self.assertEqual(self.state(2)["next_at"],None)
        self.assertEqual(self.state(1)["next_at"],280)
        self.assertEqual(list(self.con.execute("SELECT DISTINCT price FROM fishing_pond"))[0][0],777)
        self.say("投喂#1",101)
        with patch("ergou.pond_growth.Random") as factory:
            factory.return_value.randint.return_value = 6
            factory.return_value.random.return_value = .99
            self.say("鱼塘",300)
        self.assertEqual(self.state(1)["rounds"],1)
        self.assertIsNone(self.state(1)["next_at"])
        self.assertIn("已定型",self.say("投喂#1",301))
        self.assertEqual(tuple(self.con.execute("SELECT grams,price FROM fishing_pond WHERE id=1").fetchone()),
                         (25000,777+fish_grades.price("鲤鱼",25000,0)-fish_grades.price("鲤鱼",24000,0)))

    def test_late_feeding_segment_promotion_only_once_and_partial_cost(self):
        fish = self.put(price=120)
        self.say("放入鱼塘#1",100)
        with patch("ergou.pond_growth.Random") as factory:
            rng = factory.return_value
            rng.random.return_value = .99
            self.say("投喂#1",460)
            self.assertEqual((self.state(fish)["rounds"],self.state(fish)["fed_segment"]),(2,0))
            rng.randint.return_value = 2
            # 仅第 3 轮被覆盖，一级塘概率 0.1667%。
            rng.random.side_effect = [.99,.0015]
            self.say("鱼塘",640)
            self.assertEqual(self.state(fish)["promoted"],1)
            rng.random.side_effect = None
            rng.random.return_value = .99
            self.say("鱼塘",1540)
            self.assertEqual(self.state(fish)["rounds"],8)
            before = self.coins()
            self.say("投喂#1",1541)
            self.assertEqual(before-self.coins(),6)
            self.assertEqual(self.state(fish)["food"],2)
            self.say("鱼塘",100000)
        self.assertEqual(self.state(fish)["rounds"],10)
        self.assertEqual(self.con.execute("SELECT grade FROM fishing_pond").fetchone()[0],1)
        self.assertFalse(self.con.execute("SELECT 1 FROM ledger").fetchone())
        self.assertEqual(growth.feed_cost(120,9),3)

    def test_slots_protection_transfer_and_exhibit_swap(self):
        self.con.execute("INSERT INTO fishing_storage_levels VALUES(?,?,'pond',2)",self.key)
        first,second = self.put(),self.put(3200)
        self.say(f"放入鱼塘#{first}",100)
        self.say(f"投喂#{first}",101)
        self.assertIn("成长位已满",self.say(f"放入鱼塘#{second}",110))
        self.say(f"换入成长位#{second}",180)
        self.assertEqual(self.state(first)["remaining_seconds"],100)
        self.say(f"设为招牌鱼#{second}",181)
        with patch("ergou.pond_raids.random.Random") as factory:
            factory.return_value.randrange.side_effect = [0,0]
            self.assertIn(f"#{first}",self.say("偷鱼",300,("one","other"),"member"))
        self.assertIn("招牌鱼",self.say("偷鱼",900,("one","other"),"member"))
        other = ("one","other")
        self.say(f"放入鱼塘#{first}",301,other)
        self.assertEqual(self.state(first)["next_at"],401)
        self.say(f"收入图鉴#{first}",401,other)
        progress = self.state(first)
        self.assertEqual((progress["rounds"],progress["next_at"],progress["food"]),(1,None,2))
        bigger = self.put(3900,key=other)
        self.say(f"收入图鉴#{bigger}",1000,other)
        self.assertEqual(self.state(first),progress)
        self.say(f"放入鱼塘#{first}",1001,other)
        self.assertEqual(self.state(first)["next_at"],1181)
        self.assertFalse(self.con.execute("SELECT 1 FROM fishing_records").fetchone())

    def test_two_feeds_charge_once_and_exhibit_migrates_once(self):
        item = self.put()
        self.say("放入鱼塘#1",100)
        barrier = Barrier(2)
        def feed():
            with db.closing_db(self.path) as conn:
                barrier.wait(3)
                with db.transaction(conn):
                    return fish_storage.handle(conn,self.key,"投喂#1","二狗",150)
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda _: feed(),range(2)))
        self.assertEqual(sum("已投喂" in r for r in replies),1)
        self.assertEqual(self.coins(),1000-growth.feed_cost(12,0))
        self.assertEqual(self.state(item)["food"],3)
        # 模拟升级前已有的展品，原价与编号从展柜移回库存后仍一致。
        self.con.execute("INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price,grade) VALUES(?,?, '鲫鱼',70,205,78,2)",self.key)
        self.con.execute("DELETE FROM pond_migrations")
        self.con.execute("DELETE FROM pond_growth")
        db.initialize(self.path)
        before=self.state(70)
        db.initialize(self.path)
        self.assertEqual(self.state(70),before)
        self.assertEqual((before["original_grams"],before["original_grade"],before["original_price"],before["catcher"]),(205,2,78,None))
        self.assertIn("历史来源未记录",self.say("图鉴 新手池塘 1",200))
        self.say(f"收入图鉴#{self.put(250,name='鲫鱼')}",201)
        self.assertEqual(self.state(70),before)
        self.assertIn("到账 78 枚",self.say("卖鱼#70",202))

    def test_same_fish_concurrent_settlement_sale(self):
        self.put()
        self.say("放入鱼塘#1",100)
        barrier = Barrier(2)
        def sell():
            with db.closing_db(self.path) as conn:
                barrier.wait(3)
                with db.transaction(conn):
                    return fish_storage.handle(conn,self.key,"卖鱼#1","二狗",5000)
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda _: sell(),range(2)))
        sold = [msg for msg in replies if "到账" in msg]
        self.assertEqual(len(sold),1)
        proceeds = int(sold[0].split("到账 ")[1].split(" 枚")[0])
        self.assertEqual(self.coins(),1000+proceeds)

    def test_board_uses_species_rarity_group_nick_and_bag(self):
        from ergou.fishing_waters import SPECIES
        epic = next(f for f,s in SPECIES.items() if s[-1] == "史诗")
        for key, fish, grade in [(self.key,"鲤鱼",4),(("two","member"),epic,4),
                                 (("one","other"),epic,0)]:
            item=self.put(name=fish,key=key,grade=grade)
            self.say(f"收入图鉴#{item}",100,key)
        self.con.execute("INSERT INTO asset_display_names VALUES('one',1,'other','群昵称',0)")
        candidate=self.put(name="鲫鱼")
        self.put(name="鲫鱼")
        result=self.say("图鉴榜",101)
        self.assertIn("1. 群昵称　1 种 · 1 种",result)
        self.assertIn("你排第 2",result)
        self.assertIn("还有 1 种",result)
        self.assertIn(f"二狗收入图鉴#{candidate}",result)
        self.con.execute("INSERT INTO fishing_wallets(grp,member) VALUES('one','third')")
        self.say(f"收入图鉴#{self.put(key=('one','third'))}",102,("one","third"))
        self.assertIn("你排第 2",self.say("图鉴榜",104,("one","third")))

    def test_week_counts_active_actions_only(self):
        for stamp,action in [(0,"cast"),(5,"store"),(86400,"tend"),(100,"light")]:
            growth.mark(self.con,self.key,stamp,action)
            growth.mark(self.con,self.key,stamp,action)
        self.say("鱼塘",86500,("one","other"))
        data=report(self.con,"one",date(1970,1,1))
        self.assertEqual(data["首次存塘次日主动养鱼"],(1,1))
        self.assertEqual(data["活跃钓手中点亮新鱼种"],(1,1))
        self.assertEqual(data["活跃钓手中主动存塘"],(1,1))
