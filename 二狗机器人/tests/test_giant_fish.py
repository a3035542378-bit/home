import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ergou import angler, db, engine, giant_fish
from ergou.fishing_waters import SPECIES, WATERS, giant_min, size_grade, weight


class GiantFishing(unittest.TestCase):
    def test_windows_rates_and_sizes(self):
        now=3600*100
        event=giant_fish.window("room","新手池塘",now)
        self.assertIn(event.fish, [row[0] for row in WATERS["新手池塘"]])
        for stamp in (event.start-600,event.start-1,event.start,event.start+179):
            self.assertEqual(event,giant_fish.window("room","新手池塘",stamp))
        self.assertIn("还有 10 分钟",event.notice(event.start-600, "新手池塘"))
        self.assertIn("正在出没",event.notice(event.start, "新手池塘"))
        self.assertFalse(event.active(event.start+180))
        self.assertGreater(giant_fish.window("room","新手池塘",event.start+180).start,event.start+180)
        self.assertEqual(size_grade("鲤鱼",4000),"大型")
        self.assertEqual(size_grade("鲤鱼",11999),"大型")
        self.assertEqual(size_grade("鲤鱼",12000),"巨物")
        event = giant_fish.Sighting("泥鳅", event.start)
        for stamp,cutoff in ((event.start-1,1),(event.start,20),(event.start+180,1)):
            with patch("ergou.giant_fish.Random") as factory:
                rng=factory.return_value
                species = SPECIES["泥鳅" if stamp == event.start else "鲤鱼"]
                low = giant_min(species)
                high = species[2] if stamp == event.start else 25000
                rng.triangular.return_value=low
                rng.randrange.return_value=cutoff
                self.assertIsNone(giant_fish.encounter(event,"新手池塘",stamp,"sample"))
                rng.randrange.return_value=cutoff-1
                self.assertEqual(giant_fish.encounter(event,"新手池塘",stamp,"sample"),(species,low))
                rng.triangular.assert_called_with(low,high,low)
        for starter,floor in ((True,2),(False,5)):
            self.assertEqual(angler.slip_percent(10000,starter,True),floor)
            self.assertEqual(angler.slip_percent(0,starter),0)
            self.assertGreater(angler.slip_percent(0,starter,True),floor)
            self.assertGreater(angler.slip_percent(3,starter),floor)

    def test_every_local_species_can_be_scheduled_and_encountered(self):
        for area, school in WATERS.items():
            for species in school:
                fish, _, high, _, _, tier = species
                with self.subTest(area=area, fish=fish), patch("ergou.giant_fish.Random") as factory:
                    rng = factory.return_value
                    rng.randint.return_value = 20

                    def pick_tier(tiers, weights, k):
                        self.assertGreater(weights[tiers.index(tier)], 0)
                        return [tier]

                    def pick_fish(pool):
                        self.assertEqual(set(pool), {row[0] for row in school if row[-1] == tier})
                        return fish

                    rng.choices.side_effect = pick_tier
                    rng.choice.side_effect = pick_fish
                    sighting = giant_fish.window("group", area, 0)
                    self.assertEqual(sighting.fish, fish)
                    self.assertIn(fish, sighting.notice(sighting.start-600, area))
                    rng.randrange.return_value = 0
                    low = giant_min(species)
                    rng.triangular.return_value = low
                    self.assertEqual(giant_fish.encounter(sighting,area,sighting.start,"cast"), (species,low))
                    rng.triangular.assert_called_with(low, 25000 if fish=="鲤鱼" else high, low)
                    self.assertEqual(size_grade(fish,low),"巨物")

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
        # 从真实排期选一场普通小鱼，覆盖玩家从预告到收藏的整条路径。
        events = (giant_fish.window("one", "新手池塘", h*3600) for h in range(256))
        event = next(e for e in events if e.fish == "黄颡鱼")
        fish = event.fish
        grams = giant_min(SPECIES[fish])
        self.assertIn("巨物门槛",say("guide",f"巨物{fish}怎么钓？",event.start-601))
        self.assertIn("还有 10 分钟",say("forecast","巨物预告",event.start-600))
        with patch("ergou.giant_fish.encounter",return_value=(SPECIES[fish],grams)):
            with patch("ergou.fishing.fight",return_value="线"):
                self.assertIn("鱼线断了",say("broken","抛竿",event.start,"guest"))
            self.assertFalse(giant_fish.current(conn,"one","新手池塘",event.start).taken)
            with patch("ergou.fishing.fight",return_value="竿"):
                self.assertIn("鱼竿折断",say("rod","抛竿",event.start,"other"))
        with patch("ergou.fishing.fight",return_value=None) as fight, patch(
                "ergou.giant_fish.encounter",return_value=(SPECIES[fish],grams)),patch("ergou.fishing.random.Random") as r:
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
            self.assertIn(f"[名称: {fish}",got)
            self.assertIn("[大小: 巨物",got)
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
        self.assertIn(f"已点亮 {weight(grams)} · 巨物",say("detail","图鉴 新手池塘",event.start+24))
        self.assertIn("已点亮 1/117",say("global","全图鉴",event.start+25))
        self.assertIn("12～25 公斤",say("how","巨物鲤鱼怎么钓？",event.start+26))
        conn.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
                        VALUES('one','owner',?,?,85,'bag')""",(fish,grams+1))
        self.assertNotIn(f"{fish}可换展",say("upgrade","图鉴",event.start+27))
        self.assertIsNone(conn.execute("SELECT 1 FROM chat_requests").fetchone())
