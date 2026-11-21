from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ergou import db, engine, fishing_bait, hotspot


class HotspotTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(TemporaryDirectory()))/"game.sqlite"
        db.initialize(path)
        db.demo(path,("one","two"))
        self.con = self.enterContext(db.closing_db(path))
        self.key = ("one","angler")
        self.hour = int(datetime(2026,11,21,23,tzinfo=db.BJ).timestamp())
        self.site = hotspot.area_at(datetime.fromtimestamp(self.hour,db.BJ))
        rng = self.enterContext(patch("ergou.hotspot.Random")).return_value
        rng.choice.side_effect = lambda pool:pool[0]
        rng.triangular.side_effect = lambda low,high,mode:low
        self.ticket = rng.randrange

    def say(self,source,cmd,stamp):
        seq=engine.receive(self.con,"sim-account",*self.key,source,{"text":"二狗"+cmd},now=stamp)
        engine.step(self.con)
        return self.con.execute("SELECT body FROM outbox JOIN inbox ON event_id=biz WHERE seq=?",(seq,)).fetchone()[0]

    def attempt(self,stamp,area=None,key=None):
        return hotspot.encounter(self.con,key or self.key,area or self.site,stamp,"event",fishing_bait.BAITS["免费鱼饵"])

    def test_boundaries_prices_and_next_site(self):
        self.ticket.return_value=0
        for offset in (0,1199,1199.99):
            self.assertEqual(self.attempt(self.hour+offset)[1][-1],"传说")
        for offset in (-1,1200,3599,3600):
            self.assertIsNone(self.attempt(self.hour+offset))
        self.assertIsNone(self.attempt(self.hour,"新手池塘"))
        for ticket,tier in ((5,"传说"),(6,"史诗"),(35,"史诗"),(36,None)):
            self.ticket.return_value=ticket
            hit=self.attempt(self.hour)
            self.assertEqual(hit[1][-1] if hit else None,tier)
        tomorrow=hotspot.area_at(datetime.fromtimestamp(self.hour+3600,db.BJ))
        self.assertNotEqual(tomorrow,self.site)
        guide=self.say("guide","鱼讯",self.hour+1200)
        self.assertIn("11-22 00:00～00:20",guide)
        self.assertIn("切换钓场 "+tomorrow,guide)
        for hours in (0,1,2):
            self.assertEqual(hotspot.area_at(datetime.fromtimestamp(self.hour-3600*hours,db.BJ)),self.site)

    def test_escape_landing_replay_and_quota(self):
        self.ticket.return_value=1
        self.say("move","切换钓场 "+self.site,self.hour)
        self.enterContext(patch("ergou.giant_fish.encounter",return_value=None))
        fight=self.enterContext(patch("ergou.fishing.fight",return_value=None))
        self.enterContext(patch("ergou.fishing_bait.choose_rarity",return_value="普通"))
        with patch("ergou.angler.slip_percent",return_value=100):
            self.assertIn("脱钩",self.say("escape","抛竿",self.hour+2))
        self.assertFalse(hotspot.claimed(self.con,self.key,self.hour))
        with patch("ergou.angler.slip_percent",return_value=0):
            got=self.say("land","抛竿",self.hour+40)
            self.assertIn("本场活动鱼已入包",got)
            self.assertEqual(got,self.say("land","抛竿",self.hour+50))
            self.assertNotIn("热点咬钩",self.say("second","抛竿",self.hour+80))
        fish,grade=self.con.execute("SELECT fish,grade FROM fishing_pond ORDER BY id LIMIT 1").fetchone()
        self.assertEqual(grade,4)
        self.assertIn(fish,got)
        grams=self.con.execute("SELECT grams FROM fishing_pond ORDER BY id LIMIT 1").fetchone()[0]
        self.assertGreater(grams,15000)
        self.assertEqual(fight.call_args_list[0].args[1],hotspot.assisted_load(grams))
        self.assertTrue(hotspot.claimed(self.con,self.key,self.hour))
        self.assertFalse(hotspot.claimed(self.con,self.key,self.hour+3600))
        for key in (("two","angler"),("one","other")):
            self.assertIsNotNone(self.attempt(self.hour,key=key))
        self.assertEqual(self.con.execute("SELECT count(*) FROM fishing_giant_claims").fetchone()[0],0)

    def test_full_trail_precedes_hotspot(self):
        self.say("move","切换钓场 "+self.site,self.hour)
        self.con.execute("INSERT INTO fishing_first_epic VALUES('one','angler',49,NULL)")
        with patch("ergou.hotspot.encounter") as special, patch("ergou.giant_fish.encounter",return_value=None), \
                patch("ergou.fishing.fight",return_value=None), patch("ergou.angler.slip_percent",return_value=0):
            self.assertIn("首条亲钓史诗",self.say("pity","抛竿",self.hour+1))
            special.assert_not_called()

    def test_epic_floor_and_giant_priority(self):
        from ergou import fish_grades, fishing_waters
        self.ticket.return_value=10
        self.say("move","切换钓场 "+self.site,self.hour)
        self.enterContext(patch("ergou.fishing.fight",return_value=None))
        self.enterContext(patch("ergou.angler.slip_percent",return_value=0))
        self.enterContext(patch("ergou.fishing_bait.choose_rarity",return_value="普通"))
        small=fishing_waters.WATERS[self.site][0]
        with patch("ergou.giant_fish.encounter",return_value=(small,fishing_waters.giant_min(small))), \
                patch("ergou.hotspot.encounter") as special:
            self.say("giant","抛竿",self.hour+1)
            special.assert_not_called()
        with patch("ergou.giant_fish.encounter",return_value=None), \
                patch("ergou.fish_grades.final_grade",return_value=fish_grades.Grade(2,2)):
            self.assertIn("热点咬钩 · 史诗",self.say("epic","抛竿",self.hour+61))
        self.assertEqual(self.con.execute("SELECT grade FROM fishing_pond ORDER BY id DESC LIMIT 1").fetchone()[0],3)
        self.assertFalse(self.con.execute("SELECT 1 FROM ledger WHERE kind LIKE '%热点%'").fetchone())
