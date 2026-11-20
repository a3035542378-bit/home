import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ergou import angler, db, rod, rod_stats, tackle_wear
from ergou.fishing_bait import BAITS, distribution
from ergou.fishing_waters import WATERS


class RodStages(unittest.TestCase):
    def setUp(self):
        from tests.test_fish_receipts import FishReceipts
        self.fixture = FishReceipts()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.send = self.fixture.send
        self.db = self.fixture.db
        self.key = self.fixture.key

    def seed_stages(self, count):
        for tier in range(1, count+1):
            high = rod_stats.bounds(tier)[1]
            self.db.execute("INSERT INTO rod_enhancements VALUES(?,?,?,?,?,?,?)",
                            (*self.key, tier, high, high, high, high))

    def test_cap_reforge_sealing_and_current_only(self):
        self.db.execute("UPDATE fishing_wallets SET coins=3000,rod=5 WHERE grp=? AND member=?",self.key)
        self.seed_stages(99)
        receipt = self.send("二狗强化鱼竿")
        self.assertIn("当前强化 100/100 阶",receipt)
        self.assertIn("98011～100000",receipt)
        self.assertEqual(receipt.count("本阶属性范围"),1)
        self.assertIn("上限",self.send("二狗强化鱼竿"))
        self.assertIn("消耗 400 鱼币",self.send("二狗重铸 幸运 100"))
        self.assertIn("消耗 4 鱼币",self.send("二狗重铸 幸运 1"))
        self.db.execute("UPDATE fishing_wallets SET rod=4 WHERE grp=? AND member=?",self.key)
        panel = self.send("二狗我的鱼竿")
        self.assertIn("当前强化 80/80 阶",panel)
        self.assertIn("封存 20",panel)
        self.assertNotIn("98011",panel)
        self.assertIn("封存",self.send("二狗重铸 幸运 100"))
        balance = self.db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",self.key).fetchone()[0]
        self.assertEqual(balance,1596)

    def test_boundaries_monotone_and_attributes_independent(self):
        rows = []
        for tier in range(1,101):
            low,high = rod_stats.bounds(tier)
            if rows:
                self.assertGreater(rod_stats.contribution(low),rod_stats.contribution(rows[-1]["luck"]))
            rows.append(dict.fromkeys(rod_stats.FIELDS,high) | {"tier":tier})
        def odds(active):
            return distribution(WATERS["深渊海沟"],rod.weights(5,active),BAITS["免费鱼饵"],rod.trophy_bonus(5,active))
        best = odds(rows)
        self.assertAlmostEqual(sum(best.values()),100)
        rows[-1]["luck"]=rod_stats.bounds(100)[0]
        lower = odds(rows)
        for rarity in ("稀有","珍品","史诗","传说"):
            self.assertGreater(best[rarity],lower[rarity])
        rows[-1]["hardness"]=rows[-1]["toughness"]=rod_stats.bounds(100)[0]
        self.assertEqual(odds(rows),lower)
        self.assertAlmostEqual(angler.slip_percent(3,False,False,1),5)
        self.assertEqual(angler.slip_percent(0,True,False,1),0)

    def test_cast_uses_toughness_and_hardness(self):
        self.db.execute("UPDATE fishing_wallets SET rod=5 WHERE grp=? AND member=?",self.key)
        self.seed_stages(100)
        self.send("二狗切换水域 深渊海沟")
        self.db.execute("INSERT INTO fishing_experience VALUES(?,?,3)",self.key)
        self.assertIn("下竿脱钩率 5%",self.send("二狗钓手等级"))
        from ergou.fishing_waters import SPECIES
        with (patch("ergou.giant_fish.encounter",return_value=(SPECIES["星渊冠鲨"],99000)),
              patch("ergou.angler.slip_percent",wraps=angler.slip_percent) as slip):
            self.send("二狗抛竿")
        self.assertAlmostEqual(slip.call_args.args[-1],1)
        self.assertEqual(tackle_wear.read(self.db,self.key).rod,50)

    def test_legacy_migration_preserves_rolls_and_never_repeats(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/"old.sqlite"
            db.initialize(path)
            db.demo(path,("one",))
            with db.closing_db(path) as conn:
                conn.execute("INSERT INTO fishing_wallets VALUES('one','p',98,2)")
                conn.execute("DROP TABLE rod_enhancements")
                conn.execute("CREATE TABLE rod_enhancements(grp,member,tier,quality,toughness,hardness)")
                conn.execute("INSERT INTO rod_enhancements VALUES('one','p',2,4,1,2)")
            for _ in range(2):
                db.initialize(path)
                with db.closing_db(path) as conn:
                    self.assertEqual(tuple(conn.execute("SELECT * FROM rod_enhancements").fetchone()),
                                     ("one","p",2,40,11,20,40))
                    self.assertEqual(conn.execute("SELECT coins FROM fishing_wallets").fetchone()[0],98)
                    self.assertFalse(conn.execute("PRAGMA foreign_key_check").fetchall())
