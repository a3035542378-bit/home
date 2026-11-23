import time
import unicodedata
import unittest
from tests.menu_commands import commands

from ergou import breed_metrics, feature_menu, pond_growth


class PondDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.new_player()

    def new_player(self):
        from tests.test_mobile_router import MobileRouter
        fixture = MobileRouter()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.send = fixture.send
        self.db = fixture.db
        self.key = (fixture.api.room, fixture.api.details["senderId"])
        self.db.execute("UPDATE groups SET config=json_set(config,'$.command_rate',300) WHERE id=?",(self.key[0],))
        self.db.execute("INSERT INTO fishing_wallets(grp,member,coins) VALUES(?,?,100)", self.key)
        self.db.execute("INSERT INTO fishing_storage_levels VALUES(?,?,'pond',2)", self.key)

    def stock(self, item, fish, grams, grade=0, price=12, storage="pond", key=None):
        self.db.execute("""INSERT INTO fishing_pond(id,grp,member,fish,grams,grade,price,storage)
                           VALUES(?,?,?,?,?,?,?,?)""",(item,*(key or self.key),fish,grams,grade,price,storage))
        pond_growth.register(self.db,item)

    def scenario(self):
        breed_metrics.switch(self.db,self.key[0],True,time.time())
        self.stock(63,"真鲷",1500)
        self.stock(71,"鹦嘴鱼",1700)
        self.stock(77,"真鲷",2690,price=13)
        self.stock(82,"鹦嘴鱼",2288,grade=1)
        self.db.execute("UPDATE pond_growth SET rounds=10 WHERE item=77")
        self.db.execute("UPDATE pond_growth SET next_at=? WHERE item=82",(time.time()+180,))

    def test_exhibit_prefers_individual_grade_before_weight(self):
        self.stock(163,"吞噬鳗",3605,grade=2,storage="bag")
        self.assertIn("已点亮",self.send("二狗收入图鉴#163"))
        self.stock(225,"吞噬鳗",3516,grade=4,storage="pond")
        self.stock(226,"吞噬鳗",4000,grade=3,storage="bag")
        self.db.execute("UPDATE fishing_pond SET grade_upgraded=1 WHERE id=225")
        self.send("二狗切换钓场 深渊海沟")
        self.assertIn("收入图鉴#225",self.send("二狗图鉴"))
        self.assertIn("放入图鉴#225",self.send("二狗查看鱼#225"))
        self.assertIn("编号225",self.send("二狗放入图鉴").splitlines()[-1])
        reply=self.send("二狗收入图鉴#225")
        self.assertIn("已换入 #225 吞噬鳗 · 传说",reply)
        self.assertIn("原展品 #163 · 稀有",reply)
        self.assertEqual(tuple(self.db.execute("SELECT grade,grams,storage FROM fishing_pond WHERE id=163").fetchone()),(2,3605,"bag"))
        self.assertIn("品质低于展品",self.send("二狗收入图鉴#226"))
        self.stock(227,"吞噬鳗",3516,grade=4,storage="bag")
        self.assertIn("同品质只接受更重",self.send("二狗收入图鉴#227"))
        self.stock(228,"吞噬鳗",3517,grade=4,storage="bag")
        batch=self.send("二狗点亮图鉴 编号226、227、228")
        self.assertIn("换展 1 种",batch)
        self.assertIn("回包: 225",batch)
        self.assertEqual(tuple(self.db.execute("SELECT item_id,grade,grams FROM fishing_exhibits").fetchone()),(228,4,3517))
        self.assertEqual(self.db.execute("SELECT grade_upgraded FROM fishing_pond WHERE id=225").fetchone()[0],1)

    def test_old_full_bag_is_one_list_and_can_make_room(self):
        self.db.execute("INSERT INTO fishing_storage_levels VALUES(?,?,'bag',2)",self.key)
        for item in range(1,9):
            self.stock(item,"鲫鱼",200+item,storage="bag")
        body=self.send("二狗查看鱼包")
        self.assertIn("8/5",body)
        self.assertEqual(sum(line.startswith("[编号:") for line in body.splitlines()),8)
        self.assertNotIn("下一页",body)
        self.assertNotIn("升级鱼包",body)
        self.assertEqual(self.send("二狗查看鱼包 2"),body)
        self.assertIn("鱼包固定放 5 条",self.send("二狗鱼包扩容"))
        for remaining in range(8,4,-1):
            self.assertIn(f"腾出 {remaining-4} 格",self.send("二狗抛竿"))
            next_step=self.send("二狗鱼包").splitlines()[-1]
            self.assertIn("放入鱼塘#",next_step)
            self.assertIn("已将",self.send(next_step))
        self.assertIn("已满 4/4",self.send("二狗鱼塘"))
        self.assertIn("4/5",self.send("二狗鱼包"))
        self.assertIn("可放 10 条",self.send("二狗升级鱼塘"))
        wallet=self.db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",self.key).fetchone()[0]
        self.assertEqual(wallet,40)
        from unittest.mock import patch
        with patch("ergou.giant_fish.encounter",return_value=None), patch("ergou.fishing.fight",return_value=None), patch("ergou.angler.slip_percent",return_value=0):
            self.assertIn("5/5",self.send("二狗抛竿"))
        self.assertIn("鱼包已满",self.send("二狗抛竿"))

    def test_home_details_and_copyable_actions(self):
        self.scenario()
        home=self.send("二狗鱼塘")
        self.assertIn("已满 4/4 条｜成长位 1/1",home)
        for block in ("[编号: 82]  [鹦嘴鱼]","上限 2.974 公斤","[编号: 77]  [真鲷","[2.690 公斤]  [13 鱼币]  [已定型]"):
            self.assertIn(block,home)
        self.assertNotIn("投喂#77",home)
        self.assertNotIn("一键卖鱼",home)
        for line in home.splitlines():
            self.assertLessEqual(sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line),80 if line.startswith("[") else 44,line)
        self.assertIn("[编号: 71]",self.send(next(l for l in commands(home) if l=="二狗鱼塘 2")))
        guide=self.send(commands(home)[-1])
        detail=self.send(next(l for l in commands(guide) if l.startswith("二狗查看鱼#")))
        for field in ("原重","现重","上限","品相加价","原价","现价"):
            self.assertIn(field,detail)
        self.assertIn("已投喂",self.send(next(l for l in commands(detail) if l.startswith("二狗投喂"))))
        self.assertIn("饲料还够 3 轮",self.send("二狗鱼塘"))
        self.assertNotIn("【投喂",self.send("二狗查看鱼#82"))

    def test_preview_copy_follow_and_event_replay(self):
        self.scenario()
        preview=self.send("二狗放入图鉴")
        command=preview.splitlines()[-1]
        self.assertEqual(command,"二狗点亮图鉴 编号82、77")
        result=self.send(command)
        self.assertIn("已点亮 2 种",result)
        self.assertIn("2/117",result)
        self.fixture.seq-=1
        self.send(command)
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_exhibits").fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_pond").fetchone()[0],2)
        self.assertIn("已点亮",self.send(result.splitlines()[-1]))
        self.assertIn("2 种",self.send("二狗图鉴榜"))

    def test_full_bag_swaps_are_independent_of_input_order(self):
        for command in ("二狗点亮图鉴#17 #18","二狗收入图鉴 #18、#17","二狗放入图鉴＃１７，＃１８，＃１７"):
            with self.subTest(command=command):
                self.new_player()
                self.stock(17,"真鲷",1000)
                self.stock(18,"鲫鱼",205,storage="bag")
                for item in range(20,24):
                    self.stock(item,"白条",80,storage="bag")
                self.db.execute("INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price) VALUES(?,?,'真鲷',9,500,5)",self.key)
                self.assertIn("没有空位",self.send("二狗批量点亮图鉴#17"))
                result=self.send(command)
                self.assertIn("已点亮 1 种 · 换展 1 种",result)
                rows=self.db.execute("SELECT id FROM fishing_pond WHERE storage='bag' ORDER BY id").fetchall()
                self.assertEqual([r[0] for r in rows],[9,20,21,22,23])

    def test_parent_protection_scope_and_clear_intent(self):
        self.scenario()
        self.db.execute("""INSERT INTO breed_pairs(grp,member,p1,p2,fish,started,due,wins,birth,fee,state)
                         VALUES(?,?,71,82,'鹦嘴鱼',0,?,1,100,6,'active')""",(*self.key,time.time()+1800))
        for group,member,item in ((self.key[0],"neighbor",90),("other",self.key[1],91)):
            if group=="other":
                self.db.execute("INSERT INTO groups SELECT ?,account,binding,paused,version,config FROM groups WHERE id=?",
                                (group,self.key[0]))
            self.db.execute("INSERT INTO fishing_wallets(grp,member) VALUES(?,?)",(group,member))
            self.stock(item,"鲤鱼",1800,key=(group,member))
            self.assertIn("没有这条鱼",self.send(f"二狗查看鱼#{item}"))
        for text in ("二狗别点亮#82 #77","二狗点亮图鉴#82 #77？","二狗点亮后会怎样？","点亮图鉴#82 #77"):
            self.send(text)
        self.assertIn("最多",self.send("二狗点亮图鉴"+" ".join(f"#{i}" for i in range(1,12))))
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_exhibits").fetchone()[0],0)
        result=self.send("二狗点亮图鉴#82 #77 #63 #90 #91")
        for phrase in ("[编号: 82]  [亲鱼正在配对","[编号: 63]  [同种只展一尾","[编号: 90]","[编号: 91]","[编号: 77]  [真鲷]"):
            self.assertIn(phrase,result)
        self.assertEqual(self.db.execute("SELECT state FROM breed_pairs").fetchone()[0],"active")
        self.assertIn("未超过现有展品重量",self.send("二狗点亮图鉴#63 #82"))

    def test_help_actions_copy_back_to_the_same_player(self):
        self.scenario()
        self.db.execute("INSERT INTO managers(grp,member) VALUES(?,?)",self.key)
        self.send("二狗投票 创建 午餐|饭|面")
        for cmd in ("互动帮助","游戏帮助","群服务帮助"):
            for action in commands(self.send("二狗"+cmd)):
                reply=self.send(action)
                self.assertTrue(reply,action)
                self.assertNotIn("没看懂",reply)
        help_lines=commands(self.send("二狗鱼塘操作"))
        for action,result in (("二狗查看鱼#82","原重"),("二狗设为招牌鱼#82","免于被偷"),
                              ("二狗换入成长位#71","已进入成长位"),("二狗升级鱼塘","消耗 60"),
                              ("二狗一键卖鱼","到账 49")):
            self.assertIn(action,help_lines)
            self.assertIn(result,self.send(action))
        empty=self.send("二狗鱼塘")
        self.assertEqual(len(empty.splitlines()),2)
        self.stock(99,"鲫鱼",205,storage="bag")
        first=self.send("二狗鱼塘").splitlines()[-1]
        self.assertEqual(first,"二狗放入鱼塘#99")
        self.assertIn("已将 #99",self.send(first))
        self.assertNotIn("下一页",self.send("二狗鱼塘"))

    def test_directory_and_leaf_examples_at_ingress(self):
        self.assertIsNone(self.send("查天气帮助"))
        self.assertEqual(self.send("二狗帮助"),self.send("二狗菜单"))
        self.assertEqual(self.send("二狗查天气帮助"),self.send("二狗天气帮助"))
        self.assertFalse(self.db.execute("SELECT 1 FROM queries").fetchone())
        self.db.execute("INSERT INTO weather_cache VALUES('北京',?,'北京：晴')",(time.time(),))
        self.assertIsNone(self.send("@二狗　天气帮助",True))
        self.assertEqual(self.db.execute("SELECT prompt FROM chat_requests").fetchone()[0],"天气帮助")
        self.assertNotIn("繁育帮助",self.send("二狗钓鱼菜单"))
        self.scenario()
        for topic in feature_menu.TOPICS:
            reply=self.send("二狗"+topic.name+"帮助")
            if topic.gate == "jianghu":
                self.assertIn("本群暂未开启江湖录功能",reply)
            elif topic.gate in ("admin","binding","parcel"):
                self.assertIn("二狗菜单",reply)
            else:
                self.assertIn(topic.title.split()[0],reply)
        self.db.execute("UPDATE groups SET config=json_set(config,'$.games',json('false')) WHERE id=?",(self.key[0],))
        self.assertNotIn("钓鱼帮助",self.send("二狗菜单"))
        self.assertIn("未开启",self.send("二狗鱼塘帮助"))
        self.assertIn("关闭",self.send("二狗点亮图鉴 编号82、77"))
