import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ergou import angler, db, engine, giant_fish
from ergou.fishing_waters import SPECIES, size_grade


class GiantFishing(unittest.TestCase):
    def test_windows_rates_and_sizes(self):
        now=3600*100
        event=giant_fish.window("room","新手池塘",now)
        self.assertEqual(event.fish,"鲤鱼")
        for stamp in (event.start-600,event.start-1,event.start,event.start+179):
            self.assertEqual(event,giant_fish.window("room","新手池塘",stamp))
        self.assertIn("还有 10 分钟",event.notice(event.start-600))
        self.assertIn("正在出没",event.notice(event.start))
        self.assertFalse(event.active(event.start+180))
        self.assertGreater(giant_fish.window("room","新手池塘",event.start+180).start,event.start+180)
        self.assertEqual(size_grade("鲤鱼",4000),"大型")
        self.assertEqual(size_grade("鲤鱼",11999),"大型")
        self.assertEqual(size_grade("鲤鱼",12000),"巨物")
        for stamp,cutoff in ((event.start-1,1),(event.start,20),(event.start+180,1)):
            with patch("ergou.giant_fish.Random") as factory:
                rng=factory.return_value
                rng.triangular.return_value=18000
                rng.randrange.return_value=cutoff
                self.assertIsNone(giant_fish.encounter(event,"新手池塘",stamp,"sample"))
                rng.randrange.return_value=cutoff-1
                self.assertEqual(giant_fish.encounter(event,"新手池塘",stamp,"sample"),(SPECIES["鲤鱼"],18000))
                rng.triangular.assert_called_with(12000,25000,12000)
        for starter,floor in ((True,2),(False,5)):
            self.assertEqual(angler.slip_percent(10000,starter,True),floor)
            self.assertEqual(angler.slip_percent(0,starter),0)
            self.assertGreater(angler.slip_percent(0,starter,True),floor)
            self.assertGreater(angler.slip_percent(3,starter),floor)

    def test_giant_cast_and_collection(self):
        tmp=self.enterContext(tempfile.TemporaryDirectory())
        path=Path(tmp)/"game.sqlite"
        db.initialize(path)
        db.demo(path,("one","two"))
        conn=self.enterContext(db.closing_db(path))
        conn.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        conn.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        def say(source,cmd,now,member="owner"):
            seq=engine.receive(conn,"sim-account","one",member,source,{"text":"二狗"+cmd},now=now)
            engine.step(conn)
            return conn.execute("SELECT body FROM inbox JOIN outbox ON event_id=biz WHERE seq=?",(seq,)).fetchone()[0]
        event=giant_fish.window("one","新手池塘",0)
        self.assertIn("还有 10 分钟",say("forecast","巨物预告",event.start-600))
        with patch("ergou.giant_fish.encounter",return_value=(SPECIES["鲤鱼"],18000)):
            with patch("ergou.fishing.fight",return_value="线"):
                self.assertIn("鱼线断了",say("broken","抛竿",event.start,"guest"))
            self.assertFalse(giant_fish.current(conn,"one","新手池塘",event.start).taken)
            with patch("ergou.fishing.fight",return_value="竿"):
                self.assertIn("鱼竿折断",say("rod","抛竿",event.start,"other"))
        with patch("ergou.fishing.fight",return_value=None) as fight, patch(
                "ergou.giant_fish.encounter",return_value=(SPECIES["鲤鱼"],18000)),patch("ergou.fishing.random.Random") as r:
            rng=r.return_value
            rng.choices.return_value=["普通"]
            rng.choice.side_effect=lambda items:items[0]
            rng.triangular.return_value=1200
            rng.random.return_value=.049
            lost=say("miss","抛竿",event.start)
            self.assertIn("脱钩",lost)
            self.assertIsNone(conn.execute("SELECT 1 FROM fishing_pond").fetchone())
            self.assertIn("再来",say("fast","抛竿",event.start+1))
            rng.random.return_value=.05
            with patch("ergou.fish_grades.roll_upgrade", return_value=2):
                got=say("hit","抛竿",event.start+20)
            self.assertIn("神话 ✨升品",got)
            self.assertIn("＋1000 积分",got)
            self.assertIn("鲤鱼（普通 · 巨物）",got)
            self.assertIn("本轮巨物已被钓走",got)
            self.assertTrue(fight.called)
            self.assertEqual(got,say("hit","抛竿",event.start+20))
        self.assertIn("下次随机出没",say("gone","巨物鱼讯",event.start+21,"other"))
        self.assertTrue(giant_fish.current(conn,"one","新手池塘",event.start+21).taken)
        self.assertFalse(giant_fish.current(conn,"two","新手池塘",event.start+21).taken)
        with db.closing_db(path) as reopened:
            claimed=giant_fish.current(reopened,"one","新手池塘",event.start+22)
            self.assertIsNone(giant_fish.encounter(claimed,"新手池塘",event.start+22,"another"))
            self.assertFalse(giant_fish.current(reopened,"one","新手池塘",event.start+180).taken)
        self.assertIn("收入图鉴#1",say("home","图鉴",event.start+21))
        self.assertNotIn("收入图鉴#1",say("other","图鉴",event.start+22,"other"))
        self.assertIn("已点亮",say("light","收入图鉴#1",event.start+23))
        self.assertIn("已点亮 18公斤 · 巨物",say("detail","图鉴 新手池塘",event.start+24))
        self.assertIn("已点亮 1/114",say("global","全图鉴",event.start+25))
        self.assertIn("12～25 公斤",say("how","巨物鲤鱼怎么钓？",event.start+26))
        conn.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
                        VALUES('one','owner','鲤鱼',20000,85,'bag')""")
        self.assertIn("鲤鱼可换展",say("upgrade","图鉴",event.start+27))
        self.assertIsNone(conn.execute("SELECT 1 FROM chat_requests").fetchone())
