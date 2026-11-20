import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ergou import db, engine, fish_grades, giant_fish


def without_slips(test):
    """库存和扣费测试需要固定鱼获，脱钩与成长另行覆盖。"""
    return patch("ergou.angler.slip_percent", new=lambda *_: 0)(test)


class FishingTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))/"test.sqlite"
        db.initialize(path)
        db.demo(path,("one","two"))
        self.db = self.enterContext(db.closing_db(path))

    def say(self, source, text, now, group="one", member="player"):
        seq=engine.receive(self.db,"sim-account",group,member,source,{"text":"二狗 "+text},now=now)
        engine.step(self.db)
        return self.db.execute("SELECT body FROM outbox JOIN inbox ON biz=event_id WHERE seq=?",(seq,)).fetchone()[0]

    def test_giant_notice_only_prompts_starter_pond(self):
        for index, area in enumerate(giant_fish.WATERS):
            hour = (index + 1) * 3600
            event = giant_fish.window("one", area, hour)
            starter = area == "新手池塘"
            with self.subTest(area=area):
                self.say(f"move-{index}", f"切换水域 {area}", hour)
                if area in ("新手池塘", "外海"):
                    cast = self.say(f"cast-{index}", "抛竿", event.start - 600)
                    self.assertIn("还有 10 分钟", cast)
                    self.assertEqual(giant_fish.WARNING in cast, starter)
                for offset, timing in ((-600, "还有 10 分钟"), (0, "正在出没")):
                    notice = self.say(f"news-{index}-{offset}", "巨物鱼讯", event.start + offset)
                    self.assertIn(area, notice)
                    self.assertIn(timing, notice)
                    self.assertEqual(giant_fish.WARNING in notice, starter)
                    self.assertEqual("二狗抛竿" in notice, starter)
                self.db.execute("INSERT INTO fishing_giant_claims VALUES('one',?,?)", (area, event.start))
                gone = self.say(f"gone-{index}", "巨物鱼讯", event.start + 1)
                self.assertIn("下次随机出没", gone)
                self.assertEqual(giant_fish.WARNING in gone, starter)

    def test_catches_are_isolated_and_idempotent(self):
        self.assertIn("空",self.say("a","我的鱼获",100))
        first=self.say("b","钓鱼",101)
        self.assertIn("上钩",first)
        self.assertEqual(first,self.say("b","钓鱼",102))
        self.assertIn("1 秒",self.say("c","钓鱼",120))
        self.assertIn("上钩",self.say("d","钓鱼",121))
        self.assertIn("2 条",self.say("e","我的鱼获",162))
        self.assertIn("空",self.say("f","我的鱼获",163,group="two"))
        self.assertIn("空",self.say("g","我的鱼获",164,member="other"))

    def test_explicit_fishing_in_model_mode(self):
        self.db.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        self.assertIn("抛竿",self.say("h","钓鱼玩法",100))
        self.assertIn("上钩",self.say("i","抛竿",101))
        self.assertIn("19 秒",self.say("j","钓鱼",102))
        self.assertIn("1 条",self.say("k","我的鱼获",103))
        self.assertEqual(self.db.execute("SELECT count(*) FROM chat_requests").fetchone()[0],0)
        engine.receive(self.db,"sim-account","one","player","l",{"text":"二狗 钓鱼有什么技巧？"},now=104)
        engine.step(self.db)
        self.assertIsNone(self.db.execute("SELECT 1 FROM chat_requests").fetchone())
        self.db.execute("""UPDATE groups SET config=json_set(config,'$.disabled_games',json_array('钓鱼')) WHERE id='one'""")
        self.assertIn("关闭",self.say("m","抛竿",165))

    def test_pond_wallet_and_atomic_sales(self):
        self.assertIn("30 鱼币",self.say("w","我的鱼竿",100))
        self.say("a","抛竿",101)
        item,price=self.db.execute("SELECT id,price FROM fishing_pond").fetchone()
        self.say("b","钓鱼",102)
        self.assertIn("30 鱼币",self.say("w2","我的鱼竿",103))
        self.assertIn(f"#{item}",self.say("c","查看鱼包",104))
        self.assertIn("没有",self.say("d",f"卖鱼#{item}",105,member="other"))
        sold=self.say("e",f"卖鱼#{item}",106)
        self.assertEqual(sold,self.say("e",f"卖鱼#{item}",107))
        self.assertIn("没有",self.say("f",f"卖鱼#{item}",108))
        self.assertIn(f"{30+price} 鱼币",self.say("g","我的鱼竿",109))
        self.assertIn("2 级",self.say("h","升级鱼竿",110))
        self.assertIn("1 条",self.say("i","我的鱼获",111))
        self.say("j","抛竿",162)
        self.assertIn("卖出 1 条",self.say("k","卖出鱼包",163))
        self.assertIn("空",self.say("l","卖出鱼包",164))

    @without_slips
    def test_old_records_and_model_mode_sale(self):
        self.db.execute("INSERT INTO fishing_records VALUES('one','player',9,12000,'鲈鱼',1900,20)")
        self.db.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        self.assertIn("9 条",self.say("a","我的鱼获",100))
        self.assertIn("空",self.say("b","鱼塘",101))
        self.say("c","钓鱼",102)
        self.assertIn("卖出",self.say("d","卖鱼#1",103))
        self.assertIn("10 条",self.say("e","我的鱼获",104))
        self.assertEqual(self.db.execute("SELECT count(*) FROM chat_requests").fetchone()[0],0)

    def test_rod_grade_follows_level_without_enhancement(self):
        self.assertIn("鱼竿 1 级（普通）", self.say("initial", "钓鱼信息", 100))
        self.say("gear", "我的鱼竿", 101)
        self.db.execute("UPDATE fishing_wallets SET coins=200 WHERE grp='one' AND member='player'")
        for level, (old, new) in enumerate(zip(("普通", "优良", "稀有", "史诗"),
                                               ("优良", "稀有", "史诗", "传说")), start=1):
            with self.subTest(level=level):
                now = 102 + 3*level
                self.assertIn(f"下级 {level+1} 级（{new}）", self.say(f"look-{level}", "我的鱼竿", now))
                result = self.say(f"up-{level}", "鱼竿升级", now+1)
                self.assertIn(f"品质：{old} → {new}", result)
                self.assertIn(f"鱼竿 {level+1} 级（{new}）", self.say(f"info-{level}", "钓鱼信息", now+2))
        self.assertIn("已满 5 级（传说）", self.say("max", "升级鱼竿", 130))
        self.assertEqual(tuple(self.db.execute("SELECT rod,coins FROM fishing_wallets").fetchone()), (5,0))
        self.assertEqual(self.db.execute("SELECT count(*) FROM rod_enhancements").fetchone()[0], 0)

    def test_enhance_reforge_and_rollback(self):
        self.say("a","我的鱼竿",100)
        self.db.execute("UPDATE fishing_wallets SET coins=100,rod=2")
        first=self.say("b","强化鱼竿",101)
        self.assertEqual(first,self.say("b","强化鱼竿",102))
        self.say("c","强化鱼竿",103)
        def rows():
            return list(map(tuple,self.db.execute("SELECT tier,quality,toughness,hardness FROM rod_enhancements ORDER BY tier")))
        old=rows()
        self.assertIn("上限",self.say("d","强化鱼竿",104))
        self.say("e","重铸 硬度 1",105)
        changed=rows()
        self.assertEqual(old[0][:3],changed[0][:3])
        self.assertEqual(old[1],changed[1])
        self.assertTrue(all(1<=x<=3 for x in changed[0][1:]))
        from ergou.rod import levels,weights
        w=weights(2,levels(self.db,("one","player")))
        self.assertAlmostEqual(sum(w),110)
        self.assertGreater(w[3],16)
        self.assertGreater(w[4],4)
        self.say("f","回退强化",106)
        self.assertEqual(rows(),changed[:1])
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets").fetchone()[0],60)
        self.db.execute("UPDATE fishing_wallets SET coins=2")
        self.assertIn("需要",self.say("g","重铸 韧性",107))
        self.assertEqual(rows(),changed[:1])

    def test_assets_consistent_after_sale_and_scoped_to_group(self):
        self.say("a","抛竿",100)
        self.say("b","我的鱼竿",101,group="two")
        self.db.execute("UPDATE fishing_wallets SET coins=98765 WHERE grp='two'")
        board=self.say("c","资产排行榜",102)
        self.assertIn("你排第 1",board)
        self.assertNotIn("98765",board)
        self.say("d","卖出鱼包",103)
        self.assertEqual(board,self.say("e","资产榜",104))
        self.assertIn("未入榜",self.say("f","资产榜",105,member="other"))

    def test_asset_names_prefer_room_name_over_nickname_and_exclude_remarks(self):
        from unittest.mock import Mock
        from ergou.rod import refresh_names
        self.say("a","我的鱼竿",100)
        client=Mock(base="/account")
        person=dict(username="player",nickname="小雨",roomDisplayName="雨哥",displayName="私人备注")
        client.get.return_value=dict(groupId="one",username="player",state="present",member=person)
        for i,expected in enumerate(("雨哥","小雨","你")):
            self.db.execute("DELETE FROM asset_display_names")
            refresh_names(self.db,client,"one")
            board=self.say(str(i),"资产榜",101+i)
            self.assertIn("[第 1 名]  ["+expected+"]",board)
            self.assertNotIn("私人备注",board)
            self.assertNotIn("player",board)
            if i==0: person["roomDisplayName"]=""
            else: person["nickname"]=""

    def test_points_and_draw_show_the_same_public_name(self):
        from ergou import operations
        group=self.db.execute("SELECT binding FROM groups WHERE id='one'").fetchone()
        self.db.execute("INSERT INTO asset_display_names VALUES('one',?,'player','小雨',100)",(group[0],))
        operations.act(self.db,dict(name="admin",role="系统管理员",scopes="[]"),"one",
                       dict(action="调分",key="award",target="player",points=10,reason="测试"))
        import time
        self.assertIn("小雨",self.say("a","总榜",time.time()+1))
        self.say("b","抽签 报名",110)
        self.assertIn("小雨",self.say("c","抽签 开始 1",111,member="operator"))
        self.assertIn("player",self.db.execute("SELECT winners FROM draws").fetchone()[0])

    def test_damage_purchase_and_escape_are_atomic(self):
        from unittest.mock import patch
        self.say("a","抛竿",100)
        self.say("b","抛竿",160)
        self.db.execute("UPDATE fishing_wallets SET rod=2,coins=100")
        self.say("sea","切换水域 外海",161)
        with patch("ergou.fishing.fight",return_value="线"):
            failure=self.say("c","抛竿",220)
            self.assertIn("鱼线断了",failure)
            self.assertEqual(failure,self.say("c","抛竿",221))
            self.assertIn("鱼线已断",self.say("d","抛竿",222))
        self.assertIn("已装好",self.say("e","买鱼线",223))
        self.assertIn("无需购买",self.say("f","买鱼线",224))
        self.assertIn("秒后",self.say("g","抛竿",225))
        with patch("ergou.fishing.fight",return_value="竿"):
            self.assertIn("鱼竿 2 → 1 级（普通）",self.say("h","抛竿",280))
        self.assertEqual(tuple(self.db.execute("SELECT rod,coins FROM fishing_wallets").fetchone()),(1,97))
        self.assertEqual(self.db.execute("SELECT count(*) FROM fishing_pond").fetchone()[0],2)
        self.assertIn("2 条",self.say("i","我的鱼获",281))
        self.assertIn("品质：普通 → 优良", self.say("restore", "升级鱼竿", 282))

    def test_collection_and_weight_board_survive_sale(self):
        self.say("a","钓鱼",100)
        self.assertIn("1/114",self.say("b","全图鉴",101))
        self.assertIn("🐾 "+self.db.execute("SELECT fish FROM fishing_species").fetchone()[0]+"（",self.say("c","鱼类图鉴 1",102)+self.say("d","图鉴 2",103)+self.say("e","图鉴 3",104))
        self.assertIn("0/114",self.say("f","全图鉴",105,group="two"))
        self.assertIn("#",self.say("g","鱼包 重量",106))
        board=self.say("h","重量榜",107)
        self.assertIn("第 1 名",board)
        self.say("i","卖出鱼包",108)
        self.assertEqual(board,self.say("j","重量排行榜",109))
        self.assertIn("1/114",self.say("k","全图鉴",110))

    @without_slips
    @patch("ergou.fishing.fight", new=lambda *_: None)
    def test_book_by_water_through_chat(self):
        from ergou.fishing_waters import WATERS
        for area,pool in WATERS.items():
            self.assertTrue(all(0 < row[1] < row[2] for row in pool))
            self.say("go-"+area,"切换海域 "+area,100,member=area)
            self.say("cast-"+area,"抛竿",101,member=area)
            first=self.say("book-"+area,"图鉴 "+area,102,member=area)
            self.assertIn(f"已发现 1/{len(pool)} 种",first)
            pages=[first]
            for page in range(2,(len(pool)+5)//6+1):
                self.assertIn(f"图鉴 {area} {page}",pages[-1])
                pages.append(self.say(f"{area}-{page}",f"鱼类图鉴 {area} {page}",103,member=area))
            joined="\n".join(pages)
            for row in pool:
                self.assertIn(row[0]+"（",joined)
            landed=self.db.execute("SELECT fish FROM fishing_species WHERE grp='one' AND member=?",(area,)).fetchone()[0]
            self.assertEqual(joined.count("🐾 "+landed+"（"),1)
        self.assertIn("未找到",self.say("unknown","图鉴 无名河",104))
        self.assertIn("共 2 页",self.say("past","图鉴 荷花湿地 3",105))

    def test_mobile_catalog_and_giant_records(self):
        self.db.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        menu=self.say("menu","全图鉴",100)
        for kind,count in (("普通",62),("稀有",27),("珍品",16),("史诗",6),("传说",3)):
            cmd=kind+"图鉴"
            self.assertIn(f"【{cmd}】{count} 种",menu)
            self.assertIn(f"（{kind}）",self.say(cmd,cmd,101))
        self.assertIn("巨物鲤鱼 · 12～25 公斤",menu)
        self.say("wallet","我的鱼竿",102)
        self.db.execute("INSERT INTO fishing_species(grp,member,fish,best_grams) VALUES('one','player','鲤鱼',12000)")
        self.db.execute("INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price) VALUES('one','player','鲤鱼',21,1286,10)")
        self.db.execute("""INSERT INTO fishing_pond(id,grp,member,fish,grams,price,storage)
                           VALUES(25,'one','player','鲤鱼',13000,57,'bag')""")
        giant=self.say("giant","查看巨物图鉴",103)
        for snippet in ("🐾 巨物鲤鱼","新手池塘 · 12.000 公斤起","已点亮 0/114","已发现 1/114",
                        "个人纪录 12.000 公斤 · 巨物","【收入图鉴#25】鲤鱼换展","【巨物图鉴 2】"):
            self.assertIn(snippet,giant)
        self.assertNotIn("1.286 公斤",giant)
        self.assertIn("2/19",self.say("next","巨物图鉴第２页",104))
        self.assertIn("珍品图鉴 2",self.say("rare","全图鉴 珍品",105))
        self.assertIn("已换入",self.say("store","收入图鉴#25",107))
        self.assertIn("已点亮 1/114",self.say("done","巨物图鉴",108))
        self.assertIn("已点亮 0/114",self.say("isolated","巨物图鉴",109,member="other"))
        self.assertIsNone(self.db.execute("SELECT 1 FROM chat_requests").fetchone())

    def test_trophy_rates_by_bait_and_rod(self):
        from unittest.mock import Mock
        from ergou import fishing_bait, rod
        from ergou.fishing_waters import SPECIES, WATERS
        rng=Mock()
        rng.choices.return_value=["普通"]
        for area,school in WATERS.items():
            stocked={row[-1] for row in school}
            for bait,epic,legend in zip(fishing_bait.BAITS.values(),(.12,.18,.24),(.01,.015,.02)):
                for level in (1,5):
                    fishing_bait.choose_rarity(rng,school,rod.weights(level,[]),bait)
                    kinds=rng.choices.call_args.args[0]
                    weights=rng.choices.call_args.kwargs["weights"]
                    self.assertEqual(set(kinds),stocked)
                    self.assertEqual(len(kinds),len(weights))
                    for tier,pct in (("史诗",epic),("传说",legend)):
                        if tier in stocked:
                            self.assertAlmostEqual(weights[kinds.index(tier)]*100/sum(weights),pct)


    def test_trophy_cast_through_storage_and_book(self):
        from ergou.fishing_waters import SPECIES
        self.db.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        self.assertIn("没有传说鱼",self.say("empty-tier","传说图鉴 新手池塘",99))
        self.say("travel","切换水域 外海",100)
        with patch("ergou.fishing.random.Random") as factory:
            rng=factory.return_value
            rng.choice.side_effect=lambda pool:pool[0]
            rng.triangular.side_effect=lambda low,high,mode:high
            rng.random.return_value=.99
            for i,(tier,name) in enumerate((("史诗","风暴长尾鲨"),("传说","曜金蓝鳍王"))):
                rng.choices.return_value=[tier]
                stamp=101+20*i
                msg=self.say(tier,"抛竿",stamp)
                self.assertIn(f"[名称: {name}",msg)
                self.assertIn("[大小: 巨物",msg)
                self.assertEqual(msg,self.say(tier,"抛竿",stamp))
                item,grams=self.db.execute("SELECT id,grams FROM fishing_pond WHERE fish=?",(name,)).fetchone()
                self.assertEqual(grams,SPECIES[name][2])
                self.assertIn("已点亮",self.say("store"+tier,f"收入图鉴#{item}",stamp+1))
                self.assertIn(f"✨ {name}",self.say("book"+tier,"查看"+tier+"图鉴",stamp+2))
        self.assertIn("1.100 吨",self.say("board","重量榜",140))
        hint=self.say("guide","曜金蓝鳍王怎么钓？",141)
        self.assertIn("0.01%",hint)
        self.assertIn("切换水域 外海",hint)
        self.assertIsNone(self.db.execute("SELECT 1 FROM chat_requests").fetchone())

    def test_exhibits_are_manual_scoped_and_display_only(self):
        self.say("cast","抛竿",100)
        item,name,grams=self.db.execute("SELECT id,fish,grams FROM fishing_pond").fetchone()
        self.assertIn("已点亮 0/114",self.say("before","全图鉴",101))
        self.assertIn("没有",self.say("foreign",f"放入图鉴#{item}",102,member="other"))
        self.assertIn("没有",self.say("wrong-room",f"放入图鉴#{item}",102,group="two"))
        put=self.say("exhibit",f"放入图鉴#{item}",103)
        self.assertIn("已点亮",put)
        self.assertEqual(put,self.say("exhibit",f"放入图鉴#{item}",104))
        self.assertIn("已点亮 1/114",self.say("after","全图鉴",105))
        self.assertIn("已点亮 0/114",self.say("another","全图鉴",105,member="other"))
        self.assertIn("空",self.say("bag","查看鱼包",106))
        self.assertIn("没有",self.say("sell",f"卖鱼#{item}",107))
        self.assertIn("没有",self.say("pond",f"放入鱼塘#{item}",108))
        self.assertIn("空",self.say("sellbag","卖出鱼包",109))
        self.assertIn("空",self.say("sellpond","一键卖鱼",110))
        self.assertEqual(tuple(self.db.execute("SELECT item_id,fish,grams FROM fishing_exhibits").fetchone()),
                         (item,name,grams))
        self.assertIn("资产 30 鱼币",self.say("assets","资产榜",111))

    def test_exhibit_replacement_only_heavier_and_atomic_at_capacity(self):
        self.say("start","我的鱼竿",100)
        def add(fish,grams,storage):
            return self.db.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
                VALUES('one','player',?,?,?,?)""",(fish,grams,grams+1,storage)).lastrowid
        old=add("白条",50,"pond")
        self.assertIn("已点亮",self.say("first",f"点亮图鉴#{old}",101))
        lighter=add("白条",49,"bag")
        equal=add("白条",50,"bag")
        heavy=add("白条",51,"bag")
        heaviest=add("白条",52,"pond")
        add("泥鳅",100,"bag")
        add("泥鳅",150,"bag")
        for i,item in enumerate((lighter,equal)):
            self.assertIn("只接受更重",self.say(f"reject{i}",f"放入图鉴#{item}",102+i))
        self.assertIn("腾出一格",self.say("no-room",f"放入图鉴#{heaviest}",105))
        def specimen():
            return tuple(self.db.execute("SELECT item_id,grams FROM fishing_exhibits WHERE fish='白条'").fetchone())
        self.assertEqual(specimen(),(old,50))
        self.assertIn("已放回鱼包",self.say("swap",f"放入图鉴#{heavy}",106))
        self.assertEqual(specimen(),(heavy,51))
        row=self.db.execute("SELECT storage,grams,price FROM fishing_pond WHERE id=?",(old,)).fetchone()
        self.assertEqual(tuple(row),("bag",50,51))
        self.assertIn("5/5",self.say("full","查看鱼包",107))
        fresh=add("鲫鱼",200,"pond")
        self.assertIn("已点亮",self.say("new",f"放入图鉴#{fresh}",108))
        self.say("make-room",f"卖鱼#{lighter}",109)
        self.assertIn("已放回鱼包",self.say("frompond",f"放入图鉴#{heaviest}",110))
        self.assertEqual(specimen(),(heaviest,52))
        self.assertIn("已点亮 52 克",self.say("book","图鉴 新手池塘",111))
        self.assertIn("未点亮",self.say("unlit","图鉴",112))
        self.assertEqual(self.db.execute("SELECT storage FROM fishing_pond WHERE id=?",(heavy,)).fetchone()[0],"bag")

    def test_species_questions_use_the_stocked_waters_in_model_mode(self):
        from ergou.fishing import catch_guide, requested_fish
        from ergou.fishing_waters import HABITAT
        self.db.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        for fish,area in HABITAT.items():
            self.assertEqual(requested_fish(fish+"怎么钓？"),fish)
            self.assertIn("切换水域 "+area,catch_guide(fish,"二狗"))
        reply=self.say("natural","渊底银甲王怎么钓？",100)
        self.assertIn("切换水域 深渊海沟",reply)
        self.assertIn("22.000 公斤～300.000 公斤",reply)
        self.assertEqual(reply,self.say("ask","鱼种查询 渊底银甲王",101))
        self.assertIn("没找到",self.say("unknown","鱼种查询 不存在的鱼",102))
        self.assertFalse(self.db.execute("SELECT 1 FROM chat_requests").fetchone())

    def test_line_upgrades_and_max_immunity(self):
        from unittest.mock import Mock
        from ergou.fishing import fight
        self.assertIn("5.5 公斤",self.say("l0","鱼线",99))
        reply=self.say("l1","升级鱼线",100)
        self.assertIn("2 级",reply)
        self.assertEqual(reply,self.say("l1","升级鱼线",101))
        self.assertIn("需要 60",self.say("poor","升级鱼线",102))
        self.assertIn("1 级",self.say("other","鱼线",103,group="two"))
        self.db.execute("UPDATE fishing_wallets SET coins=600 WHERE grp='one'")
        self.db.execute("INSERT INTO fishing_tackle VALUES('one','player',1,90)")
        self.assertIn("二狗买鱼线",self.say("broken","升级鱼线",104))
        self.say("repair","买鱼线",105)
        self.assertIn("2 级",self.say("inspect","鱼线",106))
        for i in range(3):
            self.say("up"+str(i),"升级鱼线",110+i)
        self.assertIn("已满",self.say("cap","升级鱼线",114))
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets WHERE grp='one'").fetchone()[0],97)
        rng=Mock()
        rng.random.return_value=0
        self.assertEqual(fight(rng,7000,1,[],1),"线")
        self.assertIsNone(fight(rng,7000,1,[],2))
        rng.random.side_effect=[1,0]
        self.assertIsNone(fight(rng,60000,1,[],5))
        self.assertEqual(fight(rng,60000,1,[],5),"竿")

    @without_slips
    def test_starter_water_protects_regular_fish_and_recovers(self):
        from unittest.mock import patch
        self.assertIn("新手池塘",self.say("water","水域",90))
        with patch("ergou.fishing.size_grade",return_value="标准"), patch("ergou.fishing.fight",side_effect=AssertionError("新手常规鱼不判损坏")):
            for i in range(5):
                self.assertIn("上钩",self.say(str(i),"抛竿",100+60*i))
            self.say("space","放入鱼塘#1",340.5)
            self.say("sea","切换水域 外海",341)
            self.db.execute("UPDATE fishing_tackle SET broken=1")
            self.db.execute("UPDATE fishing_wallets SET coins=0")
            self.assertIn("已断",self.say("block","钓鱼",400))
            self.say("home","切换水域 新手池塘",401)
            self.assertIn("上钩",self.say("rescue","钓鱼",402))
            self.assertIn("卖出",self.say("sell","卖出鱼包",403))
            self.assertGreater(self.db.execute("SELECT coins FROM fishing_wallets").fetchone()[0],2)
            self.assertEqual(self.db.execute("SELECT broken FROM fishing_tackle").fetchone()[0],1)

    def test_region_pools_and_old_offshore_selection(self):
        from ergou.fishing_waters import WATERS,FISH,HABITAT
        self.assertEqual(len(HABITAT),len(FISH))
        self.say("start","我的鱼竿",90)
        self.db.execute("INSERT INTO fishing_waters(grp,member) VALUES('one','player')")
        self.assertIn("当前：外海",self.say("where","海域",91))
        for i,(area,pool) in enumerate(WATERS.items()):
            self.assertTrue({"普通","稀有","珍品"} <= {f[-1] for f in pool})
            self.assertIn(area,self.say(f"go{i}","切换水域 "+area,100+i*65))
            self.say(f"cast{i}","抛竿",101+i*65)
            fish=self.db.execute("SELECT fish,grams FROM fishing_pond ORDER BY id DESC LIMIT 1").fetchone()
            # First two catches guaranteed; later casts can damage equipment.
            if i<2:
                self.assertIn(fish[0],{f[0] for f in pool})
        self.assertIn("420.000 公斤",self.say("info","水域介绍 深海暗礁",1000))
        self.assertIn("未找到",self.say("bad","切换水域 不存在",1001))

    @without_slips
    def test_bag_and_pond_limits_before_charging_and_isolated_sales(self):
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        for i in range(5):
            catch=self.say(str(i),"抛竿",100+i*60)
        self.assertIn("鱼包已满（5/5 条）",catch)
        self.assertIn("二狗查看鱼包",catch)
        def state():
            return tuple(self.db.execute("""SELECT coins,last_attempt,count FROM fishing_wallets
                JOIN fishing_tackle USING(grp,member) JOIN fishing_records USING(grp,member)
                WHERE grp='one' AND member='player'""").fetchone())
        before=state()
        self.assertIn("先腾出 1 格",self.say("immediate","钓鱼",341))
        self.assertIn("鱼包已满",self.say("full","抛竿",400))
        self.assertIn("累计 5 竿",self.say("full-level","钓手等级",400))
        self.assertEqual(state(),before)
        self.assertIn("没有",self.say("steal","放入鱼塘#1",400,member="other"))
        self.assertIn("没有",self.say("wrong-group","放入鱼塘#1",400,group="two"))
        board=self.say("board","资产榜",400)
        moved=self.say("move","放入鱼塘#1",400)
        self.assertIn("1/1",moved)
        self.assertEqual(moved,self.say("move","放入鱼塘#1",400))
        self.assertIn("鱼塘已满",self.say("fullpond","放入鱼塘#2",400))
        self.assertEqual(self.say("board2","资产榜",400),board)
        self.assertIn("4/5",self.say("bag","查看鱼包",400))
        self.assertIn("上钩",self.say("cast","抛竿",400))
        self.assertIn("卖出 5 条",self.say("clearbag","卖出鱼包",401))
        self.assertIn("[编号: 1]",self.say("pond","鱼塘",402))
        self.assertIn("卖出 1 条",self.say("clearpond","一键卖鱼",403))
        self.assertIn("空",self.say("empty","一键卖鱼",404))
        self.assertEqual(self.db.execute("SELECT count(*) FROM chat_requests").fetchone()[0],0)

    @without_slips
    def test_bags_are_private_to_each_member_and_group(self):
        for i in range(5):
            self.say(f"owner-{i}","抛竿",100+60*i)
        self.assertIn("鱼包已满",self.say("full","抛竿",341))
        for group,member in (("one","other"),("two","player")):
            self.assertIn("0/5",self.say("empty","查看鱼包",342,group,member))
            self.assertIn("1/5",self.say("catch","抛竿",343,group,member))
            listed=self.say("list","查看鱼包",344,group,member)
            self.assertNotIn("#1 ",listed)
            self.assertIn("没有",self.say("sell-one","卖鱼#1",345,group,member))
            self.assertIn("卖出 1 条",self.say("sell-bag","卖出鱼包",346,group,member))
        self.assertIn("5/5",self.say("owner-list","查看鱼包",347))
        self.assertIn("空",self.say("pond-empty","鱼塘",348))

    def test_upgrade_costs_maxima_pages_and_weights(self):
        from ergou.fishing_waters import weight
        self.assertEqual([weight(x) for x in (999,1000,30102,1000000)],["999 克","1.000 公斤","30.102 公斤","1.000 吨"])
        self.say("init","我的鱼竿",100)
        self.db.execute("UPDATE fishing_wallets SET coins=2000")
        self.db.execute("INSERT INTO fishing_storage_levels VALUES('one','player','bag',5)")
        for cmd in ("升级鱼包","背包扩容","升级背包"):
            self.assertIn("鱼包固定放 5 条",self.say(cmd,cmd,101))
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets").fetchone()[0],2000)
        for i,size in enumerate((4,10,20,30)):
            result=self.say(f"upgrade-{i}","升级鱼塘",120+i)
            self.assertIn(f"可放 {size} 条",result)
            self.assertEqual(result,self.say(f"upgrade-{i}","升级鱼塘",125+i))
        self.assertIn("已满级",self.say("max","升级鱼塘",130))
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets").fetchone()[0],1470)
        self.db.executemany("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
            VALUES('one','player','测试鱼',?,5,'bag')""",[(i*1000,) for i in range(1,21)])
        self.assertIn("鱼包已满",self.say("cap","抛竿",200))
        first=self.say("page","查看鱼包 重量",201)
        self.assertEqual(sum(l.startswith("[编号:") for l in first.splitlines()),20)
        self.assertIn("20/5",first)
        self.assertIn("移出 16 条",first)
        self.assertIn("20.000 公斤",first.split("[编号: 20]")[1].splitlines()[0])
        self.assertNotIn("下一页",first)
        self.assertEqual(first,self.say("last","鱼包 重量 4",202))
        self.db.executemany("""INSERT INTO fishing_pond(grp,member,fish,grams,price)
            VALUES('one','player','大鱼',?,5)""",[(2000000,)]*30)
        self.assertIn("仍在鱼包",self.say("limit","放入鱼塘#1",203))
        self.assertIn("2.000 吨",self.say("large","鱼塘",204))

    def test_pond_mobile_layout_and_sale_scope(self):
        self.say("wallet","我的鱼竿",100)
        def put(grams):
            self.db.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price)
                               VALUES('one','player','鲫鱼',?,4)""",(grams,))
        put(205)
        single=self.say("single","鱼塘",101)
        self.assertIn("已满 1/1 条｜成长位 0/1",single)
        self.assertIn("[编号: 1]  [鲫鱼]",single)
        self.assertIn("[205 克]  [4 鱼币]",single)
        self.assertNotIn("下一页",single)
        self.assertNotIn("一键卖鱼",single)
        self.assertIn("【鱼塘操作】",single.splitlines()[-1])
        self.say("upgrade","升级鱼塘",102)
        put(106)
        multi=self.say("multi","鱼塘 重量",103)
        self.assertIn("[编号: 1]  [鲫鱼]",multi)
        help_text=self.say("guide","鱼塘操作",103)
        self.assertIn("【一键卖鱼】清空 2 条，共 8 鱼币",help_text)
        self.assertIn("卖出 2 条",self.say("sell","一键卖鱼",104))
        empty=self.say("empty","查看鱼塘",105)
        self.assertIn("二狗抛竿",empty)
        self.assertNotIn("二狗卖鱼#",empty)

    def test_existing_pond_migration_preserves_ids_and_overflow(self):
        import sqlite3
        from contextlib import closing
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"legacy.sqlite"
        with closing(sqlite3.connect(path)) as old, old:
            old.execute("""CREATE TABLE fishing_pond(id INTEGER PRIMARY KEY AUTOINCREMENT,grp TEXT,
                        member TEXT,fish TEXT,grams INTEGER,price INTEGER)""")
            old.executemany("INSERT INTO fishing_pond VALUES(?,'one','player','老鱼',999,12)",[(41,),(75,)])
        db.initialize(path)
        db.demo(path,("one","two"))
        db.initialize(path)
        with db.closing_db(path) as migrated:
            self.db=migrated
            self.say("wallet","我的鱼竿",100)
            old_pond=self.say("legacy","鱼塘",101)
            self.assertIn("2/1",old_pond)
            self.assertIn("[编号: 41]  [老鱼]",old_pond)
            self.assertIn("已保留",old_pond)
            self.assertIn("[编号: 76",self.say("new","抛竿",102))
            self.assertIn("仍在鱼包",self.say("wait","放入鱼塘#76",103))
            self.assertIn("可放 4 条",self.say("upgrade","升级鱼塘",104))
            self.assertIn("3/4",self.say("keep","放入鱼塘#76",105))
            self.assertIn("12 枚鱼币",self.say("sell","卖鱼#75",106))

    def test_mobile_text_width_for_fishing_commands(self):
        import unicodedata
        def width(line):
            return sum(2 if unicodedata.east_asian_width(c) in ("W","F") else 1 for c in line)
        for i,cmd in enumerate(("抛竿","查看鱼包","图鉴 深渊海沟","水域","水域介绍 深渊海沟",
                                "鱼市","我的鱼竿","鱼线","强化玩法","钓鱼玩法","钓鱼进阶",
                                "渊底银甲王怎么钓？","资产榜","重量榜")):
            with self.subTest(cmd=cmd):
                reply=self.say(f"mobile-{i}",cmd,100+i)
                for line in reply.splitlines():
                    self.assertLessEqual(width(line),80 if line.startswith("[") else 44,line)

    @without_slips
    @patch("ergou.fish_grades.final_grade", new=lambda *_: fish_grades.Grade(0,0))
    def test_paid_bait_debits_member_once_for_an_accepted_cast(self):
        from unittest.mock import patch
        self.db.execute("INSERT INTO chat_models VALUES('one',1,'glm','fixture',?,100)",(b"fixture",))
        self.db.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('one',1,1)")
        self.db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
            VALUES('one','player',0,'奖励',20,'test','award',90,'测试')""")
        self.assertIn("20",self.say("menu","鱼饵",100))
        self.assertIn("你有 0 积分",self.say("other","抛竿 高级鱼饵",101,member="other"))
        self.assertIn("你有 0 积分",self.say("room","抛竿 高级鱼饵",101,group="two"))
        first=self.say("paid","钓鱼 高级鱼饵",101)
        self.assertIn("余 15 分",first)
        self.assertEqual(first,self.say("paid","钓鱼 高级鱼饵",101))
        self.assertIn("1 秒",self.say("early","抛竿 顶级鱼饵",120))
        self.assertIn("上钩",self.say("free","抛竿",121))
        self.say("offshore","切换水域 外海",122)
        with patch("ergou.fishing.fight",return_value="线"):
            broken=self.say("top","抛竿 顶级鱼饵",141)
            self.assertIn("鱼线断了",broken)
            self.assertIn("余 0 分",broken)
        self.assertIn("鱼线已断",self.say("cannot","抛竿 顶级鱼饵",161))
        self.say("repair","买鱼线",162)
        self.assertIn("你有 0 积分",self.say("poor","抛竿 高级鱼饵",163))
        self.say("home","切换水域 新手池塘",164)
        self.assertIn("上钩",self.say("retry-free","抛竿",164))
        self.assertEqual([r[0] for r in self.db.execute("SELECT points FROM ledger WHERE kind='鱼饵' ORDER BY id")],[-5,-15])
        self.assertEqual(self.db.execute("SELECT coins FROM fishing_wallets WHERE grp='one' AND member='player'").fetchone()[0],27)
        self.assertFalse(self.db.execute("SELECT 1 FROM chat_requests").fetchone())

    @without_slips
    def test_actual_paid_cast_uses_bonuses_and_full_bag_skips_debit(self):
        from unittest.mock import patch
        self.db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
            VALUES('one','player',0,'奖励',30,'test','award',90,'测试')""")
        with patch("ergou.fishing.random.Random") as factory:
            rng=factory.return_value
            rng.choices.return_value=["普通"]
            rng.choice.side_effect=lambda pool: pool[0]
            rng.triangular.side_effect=lambda low,high,mode: mode
            for i,(suffix,factor,mode) in enumerate((("",1,.15),(" 高级鱼饵",2,.50),(" 顶级鱼饵",4,.85))):
                self.say(f"cast{i}","抛竿"+suffix,100+i*20)
                self.assertEqual(rng.choices.call_args.kwargs["weights"],(90,8*factor,2*factor))
                low,high,actual=rng.triangular.call_args.args
                self.assertAlmostEqual(actual,low+(high-low)*mode)
        self.say("four","抛竿",160)
        self.say("five","抛竿",180)
        self.assertIn("已满",self.say("full","抛竿 高级鱼饵",200))
        self.assertEqual(self.db.execute("SELECT sum(points) FROM ledger WHERE kind='鱼饵'").fetchone()[0],-20)
        balance=self.db.execute("SELECT sum(points) FROM ledger").fetchone()[0]
        self.say("sell","卖出鱼包",200)
        self.assertIn(f"余 {balance-5} 分",self.say("retry","抛竿 高级鱼饵",200))

    @without_slips
    def test_group_cooldown_can_change_and_high_daily_counts_are_allowed(self):
        from ergou import admin
        self.db.execute("UPDATE groups SET config=json_remove(config,'$.fishing_cooldown_seconds') WHERE id='one'")
        self.db.execute("INSERT INTO fishing_records VALUES('one','player',500,100000,'鲤鱼',900,100)")
        self.assertIn("1 秒",self.say("before","钓鱼",119))
        self.assertIn("上钩",self.say("boundary","钓鱼",120))
        actor={"role":"系统管理员","name":"operator"}
        for invalid in (0,86401,True):
            with self.assertRaises(ValueError):
                admin.configure(self.db,actor,"one",1,{"fishing_cooldown_seconds":invalid})
        admin.configure(self.db,actor,"one",1,{"fishing_cooldown_seconds":7})
        self.assertIn("每 7 秒",self.say("guide","钓鱼玩法",121))
        self.assertIn("每 20 秒",self.say("other-guide","钓鱼玩法",121,group="two"))
        self.assertIn("1 秒",self.say("after","抛竿",126))
        self.assertIn("上钩",self.say("ready","抛竿",127))

    def test_bait_increases_rare_odds_and_weight_within_species_range(self):
        import random
        from ergou import fishing_bait, rod
        for level in range(1,6):
            observed=[]
            for bait in fishing_bait.BAITS.values():
                weights=fishing_bait.rarity_weights(rod.weights(level,[]),bait)
                rng=random.Random(123)
                grams=[round(rng.triangular(100,900,100+800*bait.weight_mode)) for _ in range(1000)]
                self.assertTrue(all(100<=g<=900 for g in grams))
                observed.append((weights[1]/sum(weights),weights[2]/sum(weights),sum(grams)))
            for low,high in zip(observed,observed[1:]):
                self.assertTrue(all(a<b for a,b in zip(low,high)))

    def test_slipped_paid_fish_grants_level_without_catch_or_damage(self):
        from unittest.mock import Mock, patch
        import random
        self.db.execute("INSERT INTO fishing_records VALUES('one','player',9,900,'白条',100,50)")
        self.db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
            VALUES('one','player',0,'奖励',5,'test','award',50,'测试')""")
        self.assertIn("再抛 1 竿升级",self.say("old","钓手等级",99))
        rng=Mock(wraps=random.Random(1))
        rng.random.return_value=0
        with patch("ergou.fishing.random.Random",return_value=rng):
            reply=self.say("slip","抛竿 高级鱼饵",100)
            self.assertIn("脱钩了",reply)
            self.assertIn("升到钓手 2 级",reply)
            self.assertIn("余 0 分",reply)
            self.assertEqual(reply,self.say("slip","抛竿 高级鱼饵",101))
        self.assertIn("19 秒",self.say("early","抛竿",101))
        self.assertIn("你有 0 积分",self.say("poor","抛竿 高级鱼饵",120))
        self.assertIn("累计 10 竿",self.say("check","钓鱼等级",121))
        self.assertIn("下竿脱钩率 4%",self.say("risk","钓手等级",122))
        self.assertIn("累计 0 竿",self.say("other","钓手等级",123,member="other"))
        self.assertIn("累计 0 竿",self.say("room","钓手等级",123,group="two"))
        self.assertIn("9 条",self.say("catch","我的鱼获",124))
        self.assertEqual(tuple(self.db.execute("SELECT broken,last_attempt FROM fishing_tackle").fetchone()),(0,100))
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_pond").fetchone())
        self.assertFalse(self.db.execute("SELECT 1 FROM fishing_species").fetchone())
        self.assertEqual(self.db.execute("SELECT sum(points) FROM ledger").fetchone()[0],0)

    def test_hook_protection_progress_and_damage_outcomes(self):
        from unittest.mock import Mock, patch
        from ergou import angler
        import random
        for count,pond,sea in [(0,0,0),(2,0,0),(3,5,12),(9,5,12),(10,4,11),(200,2,5)]:
            self.assertEqual(angler.slip_percent(count,True),pond)
            self.assertEqual(angler.slip_percent(count,False),sea)
        rng=Mock(wraps=random.Random(3))
        rng.random.return_value=0
        with patch("ergou.fishing.random.Random",return_value=rng), patch("ergou.giant_fish.encounter",return_value=None):
            for i in range(3):
                self.assertIn("上钩",self.say(str(i),"钓鱼",100+20*i))
            self.say("go","切换水域 外海",145)
            for i,damage in enumerate(("竿","线")):
                with patch("ergou.fishing.fight",return_value=damage):
                    reply=self.say("damage"+damage,"抛竿",160+20*i)
                self.assertNotIn("脱钩",reply)
                self.assertIn(f"再抛 {6-i} 竿升级",reply)
        self.assertIn("鱼线已断",self.say("blocked","抛竿",200))
        self.assertIn("累计 5 竿",self.say("level","钓手等级",201))
        self.assertIn("下竿脱钩率 12%",self.say("risk","钓手等级",202))

    def test_disabled_and_help(self):
        self.assertIn("每 20 秒",self.say("a","钓鱼玩法",100))
        self.db.execute("UPDATE groups SET config=json_set(config,'$.games',0) WHERE id='one'")
        self.assertIn("关闭",self.say("b","钓鱼",101))
        self.assertNotIn("钓鱼",self.say("c","菜单",102))
