import unittest
from unittest.mock import Mock, patch

from ergou import giant_fish, tackle_wear
from ergou.fishing import fight
from ergou.fishing_waters import SPECIES, giant_max


class TackleWearTests(unittest.TestCase):
    def setUp(self):
        from tests.test_fish_receipts import FishReceipts
        self.player=FishReceipts()
        self.player.setUp()
        self.addCleanup(self.player.doCleanups)
        self.send=self.player.send
        self.db=self.player.db
        self.key=self.player.key
        self.db.execute("UPDATE fishing_wallets SET rod=5,coins=200 WHERE grp=? AND member=?",self.key)
        self.db.execute("INSERT INTO fishing_line_levels VALUES(?,?,5)",self.key)

    def wear(self):
        return tackle_wear.read(self.db,self.key)

    def wallet(self):
        return tuple(self.db.execute("SELECT coins,rod FROM fishing_wallets WHERE grp=? AND member=?",self.key).fetchone())

    def test_three_maximum_event_catches_then_land_last_shark_before_break(self):
        species=max(SPECIES.values(),key=giant_max)
        grams=giant_max(species)
        self.send("二狗切换水域 深渊海沟")
        self.assertEqual(self.wear(),tackle_wear.Wear())
        for attempt in range(4):
            self.player.now+=3600
            if attempt:
                self.assertIn("恢复至 100%",self.send("二狗更换鱼线"))
                self.assertIn("无需购买",self.send("二狗买鱼线"))
            event=giant_fish.Sighting(species[0],self.player.now)
            with (patch("ergou.giant_fish.current",return_value=event),
                  patch("ergou.giant_fish.encounter",return_value=(species,grams)),
                  patch("ergou.angler.slip_percent",return_value=0)):
                reply=self.send("二狗抛竿")
            if attempt<3:
                self.assertIn("上钩了",reply)
                self.assertIn("神话",reply)
                self.assertEqual(self.wear().rod,(attempt+1)*tackle_wear.strain(grams))
                self.assertEqual(self.wallet(),(200-3*attempt,5))
            else:
                self.assertIn("已收入鱼包",reply)
                self.assertIn("鱼竿撑到了收竿",reply)
                self.assertEqual(self.wallet(),(191,5))
                self.assertIn("秒后再来",self.send("二狗抛竿"))
                self.assertIn("再抛竿就会折竿",self.send("二狗我的鱼竿"))
                self.player.now+=20
                points=self.db.execute("SELECT sum(points) FROM ledger").fetchone()[0]
                self.assertIn("鱼竿折断",self.send("二狗抛竿 高级鱼饵"))
                self.assertEqual(self.db.execute("SELECT sum(points) FROM ledger").fetchone()[0],points)
                self.assertEqual(self.wallet(),(191,4))
                self.assertEqual(self.wear().rod,0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_pond WHERE grams=? AND grade=5",(grams,)).fetchone()[0],4)

    def test_fatigue_increases_break_risk_even_on_max_line(self):
        rng=Mock()
        rng.random.return_value=.5
        self.assertIsNone(fight(rng,1000,5,[],5,tackle_wear.Wear(210,0)))
        self.assertEqual(fight(rng,1000,5,[],5,tackle_wear.Wear(279,0)),"线")
        self.assertEqual(fight(rng,2_000_000,5,[],5,tackle_wear.Wear(200,0)),"线")

    def test_protection_wear_replacement_and_idempotence(self):
        self.db.execute("UPDATE fishing_wallets SET rod=1,coins=0 WHERE grp=? AND member=?",self.key)
        tackle_wear.save(self.db,self.key,tackle_wear.Wear(299,499))
        with (patch("ergou.giant_fish.encounter",return_value=None),
              patch("ergou.fishing.size_grade",return_value="标准"),
              patch("ergou.angler.slip_percent",return_value=0)):
            self.assertIn("上钩了",self.send("二狗抛竿"))
        self.assertEqual(self.wear(),tackle_wear.Wear(299,499))
        self.assertIn("还差 3",self.send("二狗修竿"))
        self.assertIn("还差 3",self.send("二狗换鱼线"))
        self.assertEqual(self.wear(),tackle_wear.Wear(299,499))
        self.db.execute("UPDATE fishing_wallets SET coins=20 WHERE grp=? AND member=?",self.key)
        self.assertIn("耐久 1%",self.send("二狗我的鱼竿"))
        self.assertIn("恢复至 100%",self.send("二狗维修鱼竿"))
        self.assertIn("无需修理",self.send("二狗修竿"))
        self.assertEqual(self.wear(),tackle_wear.Wear(299,0))
        reply=self.send("二狗购买鱼线")
        self.assertIn("恢复至 100%",reply)
        self.player.player.fixture.seq-=1
        self.player.player.send("二狗购买鱼线")
        self.assertEqual(self.wallet(),(14,1))
        self.assertEqual(self.wear(),tackle_wear.Wear())
        self.assertEqual(tackle_wear.read(self.db,("other",self.key[1])),tackle_wear.Wear())

    def test_slip_spends_once_and_rejections_do_not_wear(self):
        self.send("二狗切换水域 外海")
        with (patch("ergou.giant_fish.encounter",return_value=None),
              patch("ergou.fishing.size_grade",return_value="标准"),
              patch("ergou.angler.slip_percent",return_value=100)):
            self.assertIn("脱钩",self.send("二狗抛竿"))
        wear=self.wear()
        self.assertGreater(wear.line,0)
        self.assertGreater(wear.rod,0)
        self.assertIn("秒",self.send("二狗抛竿"))
        self.send("二狗鱼线")
        self.assertEqual(self.wear(),wear)
        self.player.now+=180
        self.assertIn("还差",self.send("二狗抛竿 高级鱼饵"))
        self.assertEqual(self.wear(),wear)

    def test_upgrades_expand_capacity_and_keep_spent_points(self):
        self.db.execute("UPDATE fishing_wallets SET rod=1 WHERE grp=? AND member=?",self.key)
        self.db.execute("UPDATE fishing_line_levels SET level=1 WHERE grp=? AND member=?",self.key)
        tackle_wear.save(self.db,self.key,tackle_wear.Wear(40,100))
        self.assertIn("500 → 1100",self.send("二狗升级鱼竿"))
        self.assertIn("1000/1100",self.send("二狗我的鱼竿"))
        self.assertIn("100/140",self.send("二狗升级鱼线"))
        self.assertEqual(self.wear(),tackle_wear.Wear(40,100))
        self.assertEqual(tackle_wear.read(self.db,(self.key[0],"neighbor")),tackle_wear.Wear())
        self.assertEqual(tackle_wear.read(self.db,("other",self.key[1])),tackle_wear.Wear())

    def test_legacy_broken_line_is_not_reset_by_upgrade(self):
        self.db.execute("INSERT INTO fishing_tackle VALUES(?,?,1,?)",(*self.key,self.player.now-120))
        self.assertIn("线耐久 0%",self.send("二狗钓鱼信息"))
        self.assertIn("已断",self.send("二狗鱼线"))
        self.assertIn("恢复至 100%",self.send("二狗买鱼线"))
        self.assertIn("300/300",self.send("二狗鱼线"))
        self.assertEqual(self.wallet(),(197,5))

    def crown_cast(self,grams):
        species=SPECIES["星渊冠鲨"]
        event=giant_fish.Sighting(species[0],self.player.now)
        with (patch("ergou.giant_fish.current",return_value=event),
              patch("ergou.giant_fish.encounter",return_value=(species,grams)),
              patch("ergou.angler.slip_percent",return_value=0)):
            return self.send("二狗抛竿")

    def test_last_line_can_be_replaced_before_the_next_attempt(self):
        self.send("二狗切换水域 深渊海沟")
        grams=giant_max(SPECIES["星渊冠鲨"])
        for repair in (True,False):
            self.player.now+=3600
            tackle_wear.save(self.db,self.key,tackle_wear.Wear(299,100))
            landed=self.crown_cast(grams)
            self.assertIn("鱼线撑到了收竿",landed)
            self.assertIn("已收入鱼包",landed)
            self.assertIn("再抛竿就会断线",self.send("二狗鱼线"))
            if repair:
                self.assertIn("100%",self.send("二狗买鱼线"))
                self.assertEqual(self.wear().line,0)
                self.player.now+=20
                self.assertIn("上钩了",self.crown_cast(grams))
            else:
                self.player.now+=20
                self.assertIn("下竿时鱼线断了",self.send("二狗抛竿"))
                self.assertIn("鱼线已断",self.send("二狗抛竿"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM fishing_pond WHERE grams=?",(grams,)).fetchone()[0],3)

    def test_near_max_does_not_defer_damage(self):
        self.send("二狗切换水域 深渊海沟")
        tackle_wear.save(self.db,self.key,tackle_wear.Wear(299,0))
        self.assertIn("鱼线断了",self.crown_cast(giant_max(SPECIES["星渊冠鲨"])-1))
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_pond").fetchone()[0],0)

    def test_grade_and_active_enhancements_change_actual_shown_odds(self):
        starter=self.send("二狗鱼钩")
        self.assertIn("传说　本场无此鱼种",starter)
        self.send("二狗切换水域 深渊海沟")
        panel=self.send("二狗我的鱼竿")
        self.assertIn("史诗　0.24%",panel)
        self.assertIn("传说　0.02%",panel)
        enhanced=self.send("二狗强化鱼竿")
        self.assertIn("幸运",enhanced)
        self.assertNotIn("史诗　0.24%",enhanced)
        with (patch("ergou.fishing.random.Random") as factory,
              patch("ergou.giant_fish.encounter",return_value=None)):
            rng=factory.return_value
            rng.choices.return_value=["普通"]
            rng.choice.side_effect=lambda school:school[0]
            rng.random.return_value=.99
            rng.triangular.side_effect=lambda low,high,mode:mode
            self.send("二狗抛竿")
            call=rng.choices.call_args
        actual=dict(zip(call.args[0],call.kwargs["weights"],strict=True))
        self.assertAlmostEqual(sum(actual.values()),100)
        for name,percent in actual.items():
            formatted=f"{percent:.4f}".rstrip("0").rstrip(".")
            self.assertIn(f"{name}　{formatted}%",enhanced)
