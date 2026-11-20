"""通过隔离微信监听入口回放鱼获、展出和繁育。"""
import time
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from ergou import breed_metrics, breeding, exhibit_batch
from ergou.fish_receipts import grid, mass, width


class FishReceipts(unittest.TestCase):
    def setUp(self):
        from tests.test_pond_directory import PondDirectoryTests
        self.player=PondDirectoryTests()
        self.player.setUp()
        self.addCleanup(self.player.doCleanups)
        self.db=self.player.db
        self.key=self.player.key
        self.now=int(time.time())
        self.trace=[]
        breed_metrics.switch(self.db,self.key[0],True,self.now)

    def send(self,cmd):
        with patch("time.time",return_value=self.now), patch("tests.test_mobile_router.datetime") as clock:
            clock.now.return_value=datetime.fromtimestamp(self.now,timezone.utc)
            self.player.fixture.listener.verify()
            body=self.player.send(cmd)
        self.assertIsNotNone(body,cmd)
        self.trace.append((cmd,body))
        return body

    def follow(self,reply):
        cmd=reply.splitlines()[-1]
        self.assertTrue(cmd.startswith("二狗"),cmd)
        return self.send(cmd)

    def check_grid(self,body,rows,count):
        data=[line for line in body.splitlines() if line.startswith("[")]
        self.assertEqual(len(data),rows)
        offsets=None
        for line in data:
            coords=[width(line[:i]) for i,c in enumerate(line) if c in "[]"]
            self.assertEqual(len(coords),2*count)
            if offsets is not None:
                self.assertEqual(coords,offsets)
            offsets=coords

    def test_card_and_first_exhibits(self):
        stock=self.player.stock
        stock(68,"钻光鱼",48,storage="bag")
        stock(70,"吞噬鳗",2447,storage="pond")
        self.db.execute("UPDATE sqlite_sequence SET seq=93 WHERE name='fishing_pond'")
        self.send("二狗切换钓场 深渊海沟")
        with patch("ergou.fishing.random.Random") as factory, patch("ergou.giant_fish.encounter",return_value=None):
            rng=factory.return_value
            rng.choices.return_value=["普通"]
            rng.choice.side_effect=lambda rows: next((r for r in rows if isinstance(r,tuple) and r[0]=="蝰鱼"),rows[0])
            rng.triangular.return_value=114
            card=self.send("二狗抛竿")
        self.check_grid(card,2,3)
        self.assertIn("114 克",card)
        self.assertIn("[编号: 94",card)
        self.assertIn("2/5",self.follow(card))
        preview=self.send("二狗放入图鉴")
        self.check_grid(preview,3,3)
        self.assertNotIn("回包",preview)
        self.assertIn("本次已选 3 种",preview)
        self.assertIn("已点亮 3 种",self.follow(preview))
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_exhibits").fetchone()[0],3)

    def test_parent_steps_and_expired_quote(self):
        for i,fish in ((64,"鲤鱼"),(70,"吞噬鳗"),(71,"吞噬鳗")):
            self.player.stock(i,fish,2447)
        self.db.execute("UPDATE pond_growth SET rounds=10 WHERE item=71")
        self.db.execute("UPDATE pond_growth SET rounds=9 WHERE item=70")
        self.db.execute("UPDATE pond_growth SET next_at=? WHERE item=64",(self.now+180,))
        guide=self.send("二狗繁育配对")
        self.check_grid(guide,2,3)
        self.assertIn("编号 64 会暂停",guide)
        moved=self.follow(guide)
        self.assertIn("编号 64 已暂停",moved)
        waiting=self.follow(moved)
        self.assertIn(breeding.clock(self.now+180),waiting)
        self.assertIsNone(self.db.execute("SELECT next_at FROM pond_growth WHERE item=64").fetchone()[0])
        self.now+=180
        ready=self.follow(waiting)
        quote=self.follow(ready)
        self.assertIn("75%",quote)
        self.now+=breeding.QUOTE_SECONDS
        expired=self.follow(quote)
        self.assertIn("报价已过期，未扣费",expired)
        quote=self.follow(expired)
        balance=lambda:self.db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",self.key).fetchone()[0]
        self.assertEqual(balance(),100)
        with patch("ergou.breeding.Random") as factory:
            factory.return_value.random.return_value=.1
            factory.return_value.randint.return_value=50
            active=self.follow(quote)
        self.assertTrue(active.startswith("🥚 已开始配对"))
        self.assertEqual(balance(),94)
        self.assertIn("配对中",self.follow(active))
        self.now+=breeding.DURATION
        pending=self.follow(active)
        self.assertIn("幼鱼可领取",pending)
        claim=self.follow(pending)
        self.assertIn("亲自繁育",claim)
        self.assertIn("鱼塘",self.follow(claim))
        self.assertIn("已经领取",self.follow(pending))
        self.assertEqual(self.db.execute("SELECT count(*) FROM breed_fry").fetchone()[0],1)

    def test_mixed_batch_and_invalid_inputs(self):
        for item,fish in ((70,"吞噬鳗"),(68,"钻光鱼"),(98,"蝰鱼")):
            self.player.stock(item,fish,110,storage="bag")
        self.db.execute("INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price) VALUES(?,?,'吞噬鳗',51,100,2)",self.key)
        for suffix in ("序号为98,70,68"," 编号98、70、68"," 98，70 68","#98#70#68"," 98；#70、68","　９８\n７０;６８"):
            self.assertEqual(exhibit_batch.parse("点亮图鉴"+suffix),(98,70,68))
        before=list(map(tuple,self.db.execute("SELECT * FROM fishing_pond ORDER BY id")))
        for suffix in (" 98-100"," #98 #70?"," 编号98、70、68，"," 98；#70、68abc"," "+",".join(map(str,range(1,12)))):
            self.assertTrue(self.send("二狗点亮图鉴"+suffix))
            self.assertEqual(before,list(map(tuple,self.db.execute("SELECT * FROM fishing_pond ORDER BY id"))))
        preview=self.send("二狗放入图鉴")
        self.assertIn("回包: 51",preview)
        self.assertIn("首次点亮",preview)
        result=self.send("二狗点亮图鉴 编号98、70；#68\n98、99")
        self.assertIn("已点亮 2 种 · 换展 1 种",result)
        self.assertIn("编号: 99",result)
        self.assertIn("回包: 51",result)
        self.assertEqual(list(map(tuple,self.db.execute("SELECT id,storage FROM fishing_pond"))),[(51,"bag")])
        self.assertIn("图鉴",self.follow(result))

    def test_long_names_and_mass_precision(self):
        self.check_grid("\n".join(grid([("编号: 1","曜金蓝鳍王",mass(1234567)),
                                      ("编号: 12345","蝰鱼",mass(2447))])),2,3)
        self.assertEqual(mass(1234567),"1.234567 吨")

    def test_supported_spellings_at_wechat_ingress(self):
        for suffix in ("序号为98,70,68"," 编号98、70、68"," 98，70 68","#98#70#68"," 98；#70、68","　９８\n７０;６８"):
            with self.subTest(suffix=suffix):
                for item,fish in ((98,"蝰鱼"),(70,"吞噬鳗"),(68,"钻光鱼")):
                    self.player.stock(item,fish,110,storage="bag")
                self.assertIn("已点亮 3 种",self.send("二狗点亮图鉴"+suffix))
                self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_exhibits").fetchone()[0],3)
                self.db.execute("DELETE FROM fishing_exhibits")

    def test_full_pond_claim_and_failed_pair(self):
        for item,fish in ((70,"吞噬鳗"),(71,"吞噬鳗"),(64,"鲤鱼"),(68,"钻光鱼")):
            self.player.stock(item,fish,2447)
        self.db.execute("UPDATE pond_growth SET rounds=10")
        for roll in (.9,.1):
            quote=self.send("二狗繁育配对#70 #71")
            with patch("ergou.breeding.Random") as factory:
                factory.return_value.random.return_value=roll
                factory.return_value.randint.return_value=50
                self.follow(quote)
            self.now+=breeding.DURATION
            status=self.send("二狗繁育状态")
            if roll>.75:
                self.assertIn("本次繁育失败",status)
                self.assertIn("成年吞噬鳗",self.follow(status))
        self.assertIn("腾出 1 个塘位后可领",status)
        self.assertIn("鱼塘操作",self.follow(status))
        self.assertIn("幼鱼已保留",self.send("二狗领取幼鱼"))
        self.assertIn("已卖出",self.send("二狗卖鱼#64"))
        self.assertIn("亲自繁育",self.follow(self.send("二狗繁育状态")))

    def test_heaviest_feasible_exhibit_when_bag_is_full(self):
        self.player.stock(123456,"吞噬鳗",1234567)
        for item in range(1,6):
            self.player.stock(item,"吞噬鳗",item*100,storage="bag")
        self.db.execute("INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price) VALUES(?,?,'吞噬鳗',61,75,2)",self.key)
        card=self.send("二狗查看鱼#123456")
        self.check_grid(card,2,3)
        self.assertIn("1.234567 吨",card)
        reply=self.send("二狗点亮图鉴 编号123456、4、5")
        self.assertIn("鱼包没有空位",reply)
        self.assertEqual(self.db.execute("SELECT item_id FROM fishing_exhibits").fetchone()[0],5)

    def test_group_service_outcomes_at_ingress(self):
        from ergou import queries
        self.db.execute("UPDATE groups SET config=json_set(config,'$.prefix','团团')")
        self.assertIsNone(self.player.send("团团天气 未收录城"))
        self.assertTrue(queries.work(self.db,lambda *args,**kwargs: {"results":[]}))
        weather=self.db.execute("""SELECT body FROM queries JOIN inbox ON inbox.seq=queries.id
                              JOIN outbox ON outbox.biz=inbox.event_id WHERE queries.state='FAILED'""").fetchone()[0]
        self.trace.append(("团团天气 未收录城",weather))
        self.assertIn("城市查询无结果",weather)
        self.assertIn("天气",self.send(weather.splitlines()[-1]))
        self.db.execute("INSERT INTO managers VALUES(?,?)",self.key)
        created=self.send("团团投票 创建 午餐|饭|面")
        code=created.split()[2]
        self.db.execute("UPDATE polls SET deadline=?", (self.now-1,))
        self.assertIn("已截止",self.send(f"团团投票 {code} 1"))
        self.assertIn("0 人参与",self.send(f"团团投票 {code}"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM ballots").fetchone()[0],0)
