"""使用模拟群及临时 SQLite 验证繁育上线规则。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from ergou import breeding, breed_metrics, db, engine, pond_growth


class Game:
    def __init__(self,path):
        self.path=path
        db.initialize(path)
        db.demo(path,("east","west"))
        self.con=db.connect(path)
        self.con.executemany("INSERT INTO fishing_wallets(grp,member,coins) VALUES(?,?,100)",
                             [("east","p"),("east","q"),("west","p")])
        self.con.execute("INSERT INTO fishing_storage_levels VALUES('east','p','pond',2)")
        breed_metrics.switch(self.con,"east",True,0)
        self.seq=0

    def fish(self,fish="鲤鱼",grams=24500,group="east",member="p",adult=True):
        c=self.con
        item=c.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,grade,grade_upgraded,storage)
                   VALUES(?,?,?,?,200,5,1,'pond')""",(group,member,fish,grams)).lastrowid
        pond_growth.register(c,item,member)
        c.execute("UPDATE pond_growth SET rounds=?,appearance=15 WHERE item=?",(10 if adult else 0,item))
        return item

    def say(self,cmd,t,group="east",member="p",target=None,source=None):
        self.seq+=1
        seq=engine.receive(self.con,"sim-account",group,member,source or f"evt{self.seq}",
                           {"text":"二狗"+cmd,"pond_target":target},now=t)
        engine.step(self.con)
        return self.con.execute("SELECT body FROM inbox JOIN outbox ON event_id=biz WHERE seq=?",(seq,)).fetchone()[0]

    def confirm(self,a,b,t,group="east"):
        self.say(f"繁育配对#{a} #{b}",t,group=group)
        return self.say(f"确认配对#{a} #{b}",t,group=group)

    def pair(self):
        a,b=self.fish(),self.fish()
        with patch.object(breeding,"SUCCESS",1):
            assert "已开始配对" in self.confirm(a,b,100)
        return a,b

    def balance(self):
        return self.con.execute("SELECT coins FROM fishing_wallets WHERE grp='east' AND member='p'").fetchone()[0]


class BreedingTests(unittest.TestCase):
    def setUp(self):
        folder=self.enterContext(tempfile.TemporaryDirectory())
        self.game=Game(Path(folder)/"breed.sqlite")
        self.addCleanup(lambda: self.game.con.close())

    def test_interrupt_sale(self):
        self.interrupt_on_departure("sale")

    def test_interrupt_raid(self):
        self.interrupt_on_departure("raid")

    def test_interrupt_exhibit(self):
        self.interrupt_on_departure("exhibit")

    def test_interrupt_bulk(self):
        self.interrupt_on_departure("bulk")

    def test_boundary_restart_replay_and_two_claims(self):
        game=self.game
        a,b=game.pair()
        assert "配对中" in game.say(f"繁育配对#{b} #{a}",120)
        assert game.balance()==94
        assert "还差 1 秒" in game.say("繁育状态",1899)
        assert "还差 1 秒" in game.say("领取幼鱼",1899)
        game.con.close()
        db.initialize(game.path)
        game.con=db.connect(game.path)
        assert "幼鱼可领取" in game.say("繁育状态",1900)
        assert "已领取" in game.say("领取幼鱼",1900,source="claim")
        assert "已领取" in game.say("领取幼鱼",1901,source="claim")
        assert "已经领取" in game.say("领取幼鱼",1902)
        assert game.balance()==94
        assert game.con.execute("SELECT count(*) FROM breed_fry").fetchone()[0]==1


    def test_full_pending_parent_departure_and_seven_days(self):
        game=self.game
        a,b=game.pair()
        game.fish("鲫鱼")
        game.fish("泥鳅")
        assert "幼鱼已保留" in game.say("繁育状态",100+7*86400)
        assert "鱼塘已满" in game.say("领取幼鱼",100+7*86400)
        assert "幼鱼已保留" in game.say(f"繁育配对#{b} #{a}",101+7*86400)
        assert game.con.execute("SELECT count(*) FROM breed_pairs").fetchone()[0]==1
        assert "到账" in game.say(f"卖鱼#{a}",102+7*86400)
        assert "已领取" in game.say("领取幼鱼",103+7*86400)
        assert "已经领取" in game.say("领取幼鱼",104+7*86400)
        assert game.con.execute("SELECT count(*) FROM breed_fry").fetchone()[0]==1


    def interrupt_on_departure(self,action):
        game=self.game
        a,b=game.pair()
        if action=="raid":
            with patch("ergou.pond_raids.random.Random") as rng:
                rng.return_value.randrange.side_effect=[0,0]
                assert "已收入你的鱼包" in game.say("偷鱼",1899,member="q",target="p")
        else:
            cmd={"sale":f"卖鱼#{a}","bulk":"一键卖鱼","exhibit":f"收入图鉴#{b}"}[action]
            reply=game.say(cmd,1899)
            assert any(word in reply for word in ("卖出","已点亮"))
        assert "中止" in game.say("领取幼鱼",1900)
        assert game.con.execute("SELECT state FROM breed_pairs").fetchone()[0]=="cancelled"


    def test_eligibility_denials_and_failed_retry(self):
        game=self.game
        a=game.fish()
        other=game.fish("白条")
        immature=game.fish(grams=1200,adult=False)
        foreign=game.fish(group="west")
        peer=game.fish(member="q")
        for item in [a,other,immature,foreign,peer]:
            assert "已开始配对" not in game.say(f"繁育配对#{a} #{item}",20)
        assert game.balance()==100
        b=game.fish()
        with patch.object(breeding,"SUCCESS",0):
            assert "已开始配对" in game.confirm(a,b,100)
        assert "未开启" in game.say("领取幼鱼",1900,group="west")
        assert "失败" in game.say("繁育状态",1900)
        assert "已开始配对" in game.confirm(a,b,1901)
        assert game.balance()==88


    def test_fry_independent_curve_no_catch_credit_or_inheritance(self):
        game=self.game
        a,b=game.pair()
        assert "已领取" in game.say("领取幼鱼",1900)
        row=game.con.execute("SELECT * FROM breed_fry").fetchone()
        item=row["item"]
        assert row["birth"]<row["adult"]==500 and 200<=row["birth"]<=300
        def quote():
            return tuple(game.con.execute("""SELECT p.grams,p.price,p.grade,g.appearance,g.rounds FROM fishing_pond p
                          JOIN pond_growth g ON g.item=p.id WHERE p.id=?""",(item,)).fetchone())
        assert quote()==(row["birth"],2,0,0,0)
        assert "无需投喂" in game.say(f"投喂#{item}",1902)
        assert "成年" in game.say(f"繁育配对#{a} #{item}",1903)
        game.say("鱼塘",3699)
        assert quote()[0]>1.3*row["birth"] and quote()[-1]==9
        game.say("鱼塘",3700)
        assert quote()==(500,3,0,0,10)
        assert "已开始配对" in game.confirm(item,b,3701)
        assert "已点亮" in game.say(f"收入图鉴#{item}",3702)
        assert "塘养繁育" in game.say("图鉴 新手池塘 1",3703)
        for table in ("ledger","fishing_records","fishing_species","fishing_grade_news"):
            assert not game.con.execute(f"SELECT 1 FROM {table}").fetchone()


    def test_pending_concurrency_and_group_claim(self):
        game=self.game
        game.pair()
        game.say("繁育状态",1900)
        assert "未开启" in game.say("领取幼鱼",1900,group="west")
        assert "没有待领" in game.say("领取幼鱼",1900,member="q")
        barrier=Barrier(2)
        def claim(_):
            with db.closing_db(game.path) as c:
                barrier.wait(3)
                with db.transaction(c):
                    return breeding.play(c,("east","p"),{"arrived":1900},"领取幼鱼","二狗")
        with ThreadPoolExecutor(2) as pool:
            replies=list(pool.map(claim,range(2)))
        assert sum("已领取" in r for r in replies)==1
        assert game.con.execute("SELECT count(*) FROM breed_fry").fetchone()[0]==1


    def test_low_balance_and_simultaneous_independent_groups(self):
        game=self.game
        a,b=game.fish(),game.fish()
        game.con.execute("UPDATE fishing_wallets SET coins=5 WHERE grp='east' AND member='p'")
        assert "余额不足" in game.confirm(a,b,30)
        assert game.balance()==5
        assert not game.con.execute("SELECT 1 FROM breed_pairs").fetchone()
        game.con.execute("UPDATE fishing_wallets SET coins=6 WHERE grp='east' AND member='p'")
        game.con.execute("INSERT INTO fishing_storage_levels VALUES('west','p','pond',2)")
        breed_metrics.switch(game.con,"west",True,30)
        x,y=game.fish(group="west"),game.fish(group="west")
        assert "已开始配对" in game.confirm(a,b,31)
        assert "已开始配对" in game.confirm(x,y,31,group="west")
        assert game.balance()==0
        assert game.con.execute("SELECT count(*) FROM breed_pairs WHERE state='active'").fetchone()[0]==2


    def test_parent_sold_at_deadline_preserves_unseen_entitlement(self):
        game=self.game
        a,b=game.pair()
        assert "到账" in game.say(f"卖鱼#{a}",1900)
        assert "已领取" in game.say("领取幼鱼",1901)
        assert "已经领取" in game.say("领取幼鱼",1902)


    def test_fry_keeps_curve_after_theft_and_moving_back_to_pond(self):
        game=self.game
        a,b=game.pair()
        game.say("领取幼鱼",1900)
        item=game.con.execute("SELECT item FROM breed_fry").fetchone()[0]
        game.say(f"卖鱼#{a}",1901)
        game.say(f"卖鱼#{b}",1902)
        with patch("ergou.pond_raids.random.Random") as rng:
            rng.return_value.randrange.side_effect=[0,0]
            assert "已收入你的鱼包" in game.say("偷鱼",2440,member="q",target="p")
        assert game.con.execute("SELECT rounds FROM pond_growth WHERE item=?",(item,)).fetchone()[0]==3
        assert "进入成长位" in game.say(f"放入鱼塘#{item}",4000,member="q")
        game.say("鱼塘",5260,member="q")
        assert "到账 3 枚" in game.say(f"卖鱼#{item}",5261,member="q")
        assert not game.con.execute("SELECT 1 FROM breed_fry WHERE item=?",(item,)).fetchone()

    def test_quote_gates_and_next_day_banner(self):
        g=self.game
        a,b=g.fish(),g.fish()
        assert "先查看" in g.say(f"确认配对#{a} #{b}",100)
        quote=g.say(f"繁育配对#{a} #{b}",101)
        for text in (f"[编号: {a}]  [鲤鱼]",f"[编号: {b}]  [鲤鱼]","6 鱼币","75%","确认配对"):
            assert text in quote
        assert g.balance()==100
        assert "先查看" in g.say(f"确认配对#{a} #{b}",701)
        with patch.object(breeding,"SUCCESS",1):
            ack=g.confirm(a,b,702)
        assert breeding.clock(2502) in ack
        assert "配对中" in g.say(f"确认配对#{a} #{b}",703)
        assert g.balance()==94
        pond=g.say("鱼塘",86500)
        assert "幼鱼可领取" in pond.splitlines()[2]
        assert "领取幼鱼" in pond.splitlines()[3]
        assert "幼鱼可领取" not in g.say("鱼塘",86501,group="west")
        claim=g.say("领取幼鱼",86502)
        assert "鲤鱼幼鱼" in claim and "你亲自繁育的第一尾" in claim
        assert "亲自繁育的第一尾" in g.say("鱼塘",86503)

    def test_flag_rollback_preserves_assets_and_invalidates_quotes(self):
        g=self.game
        a,b=g.fish(),g.fish()
        g.say(f"繁育配对#{a} #{b}",100)
        breed_metrics.switch(g.con,"east",False,101)
        assert "未开启" in g.say(f"确认配对#{a} #{b}",102)
        breed_metrics.switch(g.con,"east",True,103)
        assert "先查看" in g.say(f"确认配对#{a} #{b}",104)
        with patch.object(breeding,"SUCCESS",1):
            g.confirm(a,b,105)
        breed_metrics.switch(g.con,"east",False,106)
        assert "未开启" in g.say("领取幼鱼",2000)
        assert g.balance()==94
        breed_metrics.switch(g.con,"east",True,2001)
        assert "已领取" in g.say("领取幼鱼",2002)
        assert g.balance()==94

    def test_weekly_history_retention_and_net_recovery(self):
        g=self.game
        a,b=g.pair()
        g.say("领取幼鱼",2000)
        item=g.con.execute("SELECT item FROM breed_fry").fetchone()[0]
        assert "已点亮" in g.say(f"收入图鉴#{item}",2001)
        g.confirm(a,b,2002)
        data=breed_metrics.week(g.con,"east",2002)
        assert list(data.values())==[1,1,1,1,1,1,12,0,12,0,0]
        # 展品换回包，保留第一尾；次周出售不会改写首周留存或净回收。
        g.say(f"收入图鉴#{a}",3000)
        g.say("卖出鱼包",8*86400)
        assert breed_metrics.week(g.con,"east",9*86400)==data
        assert tuple(g.con.execute("SELECT item,price FROM breed_sales").fetchone())==(item,2)

    def test_metrics_count_sale_after_theft_and_passive_eligibility(self):
        g=self.game
        a,b=g.pair()
        g.say("领取幼鱼",1900)
        item=g.con.execute("SELECT item FROM breed_fry").fetchone()[0]
        g.say(f"卖鱼#{a}",1901)
        g.say(f"卖鱼#{b}",1902)
        with patch("ergou.pond_raids.random.Random") as rng:
            rng.return_value.randrange.side_effect=[0,0]
            g.say("偷鱼",1910,member="q",target="p")
        assert breed_metrics.week(g.con,"east",1911)["留下首尾幼鱼"]==0
        g.say("卖出鱼包",1912,member="q")
        assert breed_metrics.week(g.con,"east",1912)["实际鱼币净回收"]==4
        x=g.fish(member="q")
        y=g.fish(grams=1200,member="q",adult=False)
        g.con.execute("UPDATE pond_growth SET rounds=9,next_at=2100 WHERE item=?",(y,))
        breed_metrics.refresh(g.con,("east","q"),2000)
        assert breed_metrics.week(g.con,"east",2099)["有两条同种成年塘鱼"]==1
        assert breed_metrics.week(g.con,"east",2100)["有两条同种成年塘鱼"]==2
        g.say(f"卖鱼#{x}",2099,member="q")
        assert breed_metrics.week(g.con,"east",2100)["有两条同种成年塘鱼"]==1

    def test_first_pair_moves_real_bag_fish_then_quotes_for_free(self):
        g=self.game
        a,b=g.fish(),g.fish()
        g.con.execute("UPDATE fishing_pond SET storage='bag' WHERE id=?", (b,))
        g.fish(member="q")
        g.fish(group="west")
        reply=g.say("繁育配对",10)
        self.assertIn(f"[编号: {a}]  [鱼塘]  [成年]",reply)
        self.assertIn(f"[编号: {b}]  [鱼包]  [成年]",reply)
        self.assertEqual(reply.splitlines()[-1],f"二狗放入鱼塘#{b}")
        self.assertIn("已将",g.say(f"放入鱼塘#{b}",11))
        guide=g.say("繁育配对",12)
        self.assertEqual(guide.splitlines()[-1],f"二狗繁育配对#{a} #{b}")
        self.assertIn("确认配对",g.say(f"繁育配对#{a} #{b}",13))
        self.assertEqual(g.balance(),100)

    def test_first_pond_upgrade_balance_and_full_pond(self):
        g=self.game
        a,b=g.fish(),g.fish()
        g.con.execute("UPDATE fishing_pond SET storage='bag' WHERE id=?", (b,))
        g.con.execute("DELETE FROM fishing_storage_levels")
        g.con.execute("UPDATE fishing_wallets SET coins=7 WHERE member='p'")
        spare=g.fish("泥鳅")
        g.con.execute("UPDATE fishing_pond SET storage='bag' WHERE id=?", (spare,))
        reply=g.say("繁育配对",10)
        for word in ("1/1","20 鱼币","余额 7",f"卖鱼#{spare}"):
            self.assertIn(word,reply)
        self.assertLessEqual(len(reply.splitlines()),8)
        self.assertNotIn("放入鱼塘",reply)
        self.assertEqual(g.balance(),7)
        g.say(f"卖鱼#{spare}",11)
        self.assertIn("二狗升级鱼塘",g.say("繁育配对",12))
        self.assertIn("可放 4 条",g.say("升级鱼塘",13))
        for name in ("泥鳅","白条","鳊鱼"):
            g.fish(name)
        g.con.execute("UPDATE fishing_wallets SET coins=0 WHERE member='p'")
        reply=g.say("繁育配对",14)
        self.assertIn("先腾 1 个塘位",reply)
        self.assertNotIn("放入鱼塘",reply)
        self.assertLessEqual(len(reply.splitlines()),8)

    def test_first_pair_single_fish_uses_its_habitat_and_own_stock(self):
        g=self.game
        a=g.fish("虹鳟",1000)
        g.fish("虹鳟",1000,member="q")
        g.fish("虹鳟",1000,group="west")
        reply=g.say("繁育配对",10)
        for word in (f"[编号: {a}]  [鱼塘]  [成年]","还缺一条","山涧溪流","二狗切换钓场 山涧溪流"):
            self.assertIn(word,reply)
        g.say("切换钓场 山涧溪流",11)
        self.assertIn("二狗抛竿",g.say("繁育配对",12))

    def test_first_pair_fry_needs_growth_then_becomes_eligible_offline(self):
        g=self.game
        a,b=g.fish(),g.fish(grams=250,adult=False)
        g.con.execute("INSERT INTO breed_fry VALUES(?,250,500,'p',1)",(b,))
        reply=g.say("繁育配对",10)
        self.assertIn(f"[编号: {b}]  [鱼塘]  [幼鱼]",reply)
        self.assertIn(f"二狗换入成长位#{b}",reply)
        self.assertIn("进入成长位",g.say(f"换入成长位#{b}",11))
        self.assertIn("正在成长",g.say("繁育配对",12))
        self.assertNotIn(f"繁育配对#{a} #{b}",g.say("繁育配对",1810))
        self.assertIn(f"繁育配对#{a} #{b}",g.say("繁育配对",1811))
        self.assertEqual(g.balance(),100)

    def test_week_query_cohorts_change_on_eligibility_and_confirmation(self):
        g=self.game
        def cohorts(t,group="east"):
            data=breed_metrics.week(g.con,group,t)
            return data["查询过配对但尚无资格"], data["已有资格却未发起配对"]
        g.say("繁育配对",10)
        g.say("繁育配对",11)
        g.say("繁育状态",12,member="q")
        g.say("繁育配对",12,group="west")
        self.assertEqual(cohorts(12),(1,0))
        a,b=g.fish(),g.fish()
        breed_metrics.refresh(g.con,("east","p"),13)
        self.assertEqual(cohorts(13),(0,1))
        g.say(f"繁育配对#{a} #{b}",14)
        self.assertEqual(cohorts(14),(0,1))
        g.say(f"确认配对#{a} #{b}",15)
        self.assertEqual(cohorts(15),(0,0))
        for _ in range(2):
            g.fish(member="q")
        breed_metrics.refresh(g.con,("east","q"),16)
        breed_metrics.switch(g.con,"west",True,16)
        g.say("繁育配对",17,group="west")
        self.assertEqual(cohorts(18,"west"),(1,0))
        self.assertEqual(cohorts(18),(0,1))
        g.say("繁育配对",breed_metrics.WEEK, member="outside")
        self.assertEqual(cohorts(breed_metrics.WEEK+1),(0,1))
        self.assertFalse(g.con.execute("SELECT 1 FROM breed_queries WHERE member='outside'").fetchone())

    def test_new_player_can_follow_first_level_quote_without_query_debit(self):
        g=self.game
        reply=g.say("繁育配对",10,member="new")
        self.assertIn("余额 30 鱼币",reply)
        self.assertIn("0/1",reply)
        self.assertFalse(g.con.execute("SELECT 1 FROM fishing_wallets WHERE member='new'").fetchone())
        self.assertIn("消耗 20 鱼币",g.say("升级鱼塘",11,member="new"))
        self.assertIn("二狗抛竿",g.say("繁育配对",12,member="new"))

    def test_two_bag_fish_with_only_one_free_slot(self):
        g=self.game
        a,b=g.fish(),g.fish()
        g.con.execute("UPDATE fishing_pond SET storage='bag' WHERE id IN (?,?)",(a,b))
        for fish in ("泥鳅","白条","虹鳟"):
            g.fish(fish)
        reply=g.say("繁育配对",10)
        self.assertIn(f"[编号: {a}]  [鱼包]",reply)
        self.assertIn(f"[编号: {b}]  [鱼包]",reply)
        self.assertIn("升级鱼塘",reply)
        self.assertNotIn("放入鱼塘",reply)
        self.assertEqual(g.balance(),100)
