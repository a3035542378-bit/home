"""从隔离微信事件产生帮助页与其下一句的回执，供回归和交付报告使用。"""
import json
import os
import time
import unicodedata
import unittest
from tests.menu_commands import commands
from unittest.mock import patch

from ergou import breed_metrics, feature_menu, games, pond_growth, queries


def business_state(db):
    tables=("ledger","redemptions","games","players","ballots","candidates","draws","fishing_pond",
            "fishing_wallets","fishing_exhibits","pond_growth","pond_activity","breed_pairs","breed_previews",
            "rod_enhancements","group_member_role","permission_audit_log","smart_controls","queries","chat_requests")
    return {t:[tuple(row) for row in db.execute("SELECT * FROM "+t+" ORDER BY rowid")] for t in tables}


def width(line):
    return sum(2 if unicodedata.east_asian_width(c) in ("F","W") else 1 for c in line)


class HelpWalkthrough(unittest.TestCase):
    def setUp(self):
        self.replays={}
        self.enterContext(patch.dict(os.environ,{"ERGOU_KDN_ID":"fixture","ERGOU_KDN_KEY":"fixture","ERGOU_DHL_KEY":""}))

    def player(self):
        from tests.test_mobile_router import MobileRouter
        f=MobileRouter()
        f.setUp()
        self.addCleanup(f.doCleanups)
        db=f.db
        key=(f.api.room,f.api.details["senderId"])
        db.execute("UPDATE groups SET config=json_set(config,'$.command_rate',300)")
        breed_metrics.switch(db,key[0],True,time.time())
        db.execute("INSERT INTO managers VALUES(?,?)",key)
        db.execute("INSERT INTO fishing_wallets(grp,member,coins) VALUES(?,?,190)",key)
        db.execute("INSERT INTO fishing_storage_levels VALUES(?,?,'pond',3)",key)
        db.execute("INSERT INTO fishing_pond(id,grp,member,fish,grams,grade,price,storage) VALUES(71,?,?,'鲫鱼',205,1,8,'bag')",key)
        pond_growth.register(db,71)
        db.execute("INSERT INTO reward_offers VALUES(?,'选片权',3)",key[:1])
        db.execute("INSERT INTO candidates VALUES(?,?)",key)
        return f

    def follow(self,f,cmd):
        result=f.send(cmd)
        if result is None:
            job=f.db.execute("SELECT id,kind,argument FROM queries WHERE state='PENDING'").fetchone()
            self.assertIsNotNone(job,cmd)
            def provider(url,params,deadline,*args,**kwargs):
                if url==queries.KDN:
                    return {"Success":True,"State":"2"}
                if url==queries.FORECAST:
                    return {"current":{"time":"2026-11-20T10:00","temperature_2m":18}}
                return {"results":[{"name":job["argument"],"latitude":28,"longitude":116,"country":"中国","country_code":"CN"}]}
            data={"query":{"pages":[{"title":"大熊猫","pageid":123,"extract":"大熊猫是熊科动物。"}]}}
            with patch("ergou.bulletins.public_get",return_value=json.dumps(data).encode()):
                self.assertTrue(queries.work(f.db,provider))
            row=f.db.execute("SELECT body FROM inbox JOIN outbox ON event_id=biz JOIN queries ON queries.id=inbox.seq WHERE inbox.seq=? AND queries.state='DONE'",(job["id"],)).fetchone()
            self.assertIsNotNone(row,cmd)
            result=row[0]
        self.assertTrue(result)
        for failure in ("没看懂这个指令","业务处理失败","CAPABILITY_UNSUPPORTED","本群没有这个局号"):
            self.assertNotIn(failure,result,cmd)
        return result

    def test_every_topic_and_copyable_command(self):
        for topic in feature_menu.TOPICS:
            if topic.name in ("管理","绑定"):
                continue
            with self.subTest(topic=topic.name):
                f=self.player()
                before=business_state(f.db)
                command="二狗"+topic.name+"帮助"
                body=f.send(command)
                self.assertEqual(before,business_state(f.db))
                for alias in topic.aliases:
                    self.assertEqual(f.send("二狗"+alias),body)
                self.assertEqual(before,business_state(f.db))
                self.assertTrue(all(width(line)<=48 for line in body.splitlines()),body)
                steps=[]
                for cmd in commands(body):
                    result=self.follow(f,cmd)
                    steps.append((cmd,result))
                    if cmd=="二狗放入鱼塘#71":
                        self.assertIn("已将 #71",result)
                    if cmd=="二狗投喂#71":
                        self.assertIn("已投喂",result)
                    if cmd=="二狗放入图鉴":
                        copy=result.splitlines()[-1]
                        receipt=self.follow(f,copy)
                        self.assertIn("已点亮",receipt)
                        steps.append((copy,receipt))
                    if cmd=="二狗开始 成语接龙":
                        action=next(l for l in result.splitlines() if l.startswith("二狗G"))
                        self.assertIn("意气风发",self.follow(f,action))
                    if cmd=="二狗强化鱼竿" or cmd=="二狗回退强化" or cmd=="二狗重铸 韧性 1":
                        self.assertIn("成功",result)
                self.assertTrue(any(l.startswith("【") for l in body.splitlines()),body)
                self.assertTrue(steps,topic.name)
                self.replays[topic.name]=(command,body,steps)

    def test_management_and_binding(self):
        from tests.test_owner_roles import OwnerRoles
        from tests.test_wechat_group_binding import GroupBindingTests
        f=OwnerRoles()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.say("parent","授权群主")
        f.say("chief","授权管理员","manager")
        for member,enabled in (("reader",False),("manager",True),("chief",True),("parent",True)):
            before=business_state(f.db)
            body=f.say(member,"管理帮助")
            self.assertEqual(before,business_state(f.db))
            self.assertEqual("投票 创建" in body,enabled)
            self.assertEqual("本群设置" in body,member in ("parent","chief"))
            self.assertEqual("主人转移" in body,member=="parent")
            self.assertEqual("绑定帮助" in f.say(member,"群服务帮助"),member=="parent")
            if not enabled:
                self.assertIn("菜单",body)
        f.say("reader","抽签 报名")
        steps=[]
        for cmd in commands(body):
            if "@" in cmd or cmd in ("二狗授权群主","二狗取消群主授权"):
                continue  # 真实提及、授权变更在专门的身份用例中验证。
            result=f.say("parent",cmd.removeprefix("二狗"))
            self.assertNotIn("权限不足",result)
            self.assertNotIn("没看懂",result)
            steps.append((cmd,result))
        steps.append(("私聊：二狗群主授权列表",f.say("parent","群主授权列表",private=True)))
        self.replays["管理"]=("二狗管理帮助",body,steps)
        binding=GroupBindingTests()
        binding.setUp()
        self.addCleanup(binding.doCleanups)
        guide=f.say("parent","绑定帮助")
        steps=[]
        for room,cmd,mention in ((binding.b,"@二狗 激活本群",True),(binding.b,"二狗绑定状态",False),(binding.b,"二狗停用本群",False)):
            binding.say(room,cmd,mentioned=mention)
            result=binding.db.execute("SELECT body FROM binding_receipts WHERE source=?",(str(binding.cursor),)).fetchone()
            self.assertIsNotNone(result,cmd)
            steps.append((cmd,result[0]))
        self.assertIn("停用",steps[-1][1])
        self.replays["绑定"]=("二狗绑定帮助",guide,steps)

    def test_views_with_due_growth_do_not_settle(self):
        f=self.player()
        self.follow(f,"二狗放入鱼塘#71")
        f.db.execute("UPDATE pond_growth SET next_at=? WHERE item=71",(time.time()-4000,))
        self.follow(f,"二狗开始 成语接龙")
        f.db.execute("UPDATE games SET deadline=?",(time.time()-30,))
        before=business_state(f.db)
        for cmd in ("菜单","全菜单","鱼塘怎么养","投喂帮助","繁育帮助","钓鱼进阶","强化玩法"):
            self.assertTrue(f.send("二狗"+cmd))
        self.assertEqual(before,business_state(f.db))
        self.follow(f,"二狗鱼塘")
        self.assertNotEqual(before["pond_growth"],business_state(f.db)["pond_growth"])

    def test_all_game_openings_and_join_midgame(self):
        from random import Random
        for name,game in games.GAMES.items():
            board=game.initial(Random(17))
            rules=dict(game_id=game.id)
            with self.subTest(game=name):
                hint=games.turn_hint(name,rules,board,"G72","团团")
                if game.id in games.QUIZZES:
                    self.assertIn(board["clue"],hint)
                    self.assertNotIn(board["answer"],hint)
                else:
                    action=hint.splitlines()[-1].removeprefix("团团G72 ")
                    game.move(board,action)
        f=self.player()
        first=self.follow(f,"二狗游戏列表")
        self.assertIn("二狗游戏列表 2",commands(first))
        self.assertIn("下一页",self.follow(f,"二狗游戏列表 2"))
        opened=self.follow(f,"二狗开始 成语接龙")
        self.follow(f,next(l for l in opened.splitlines() if l.startswith("二狗G")))
        f.api.details["senderId"]="neighbor"
        joined=self.follow(f,next(l for l in commands(opened) if l.startswith("二狗加入")))
        action=next(l for l in joined.splitlines() if l.startswith("二狗G"))
        self.assertNotIn("意气风发",action)
        self.assertIn(action.partition(" ")[2],self.follow(f,action))
        self.assertIn("已退出",self.follow(f,"二狗退出 G01"))

    def test_personal_steps_and_feature_gates(self):
        f=self.player()
        f.db.execute("UPDATE fishing_wallets SET coins=1")
        self.assertIsNone(f.send("帮助"))
        body=f.send("二狗菜单")
        self.replays["主菜单"]=("二狗菜单",body,[("二狗天气帮助",self.follow(f,"二狗天气帮助"))])
        for cmd in ("升级鱼竿","升级鱼塘","强化鱼竿"):
            result=self.follow(f,"二狗"+cmd)
            self.assertIn("还差",result)
            self.assertIn("发送即卖出",self.follow(f,result.splitlines()[-1]))
        f.db.execute("UPDATE groups SET config=json_set(config,'$.games',json('false'),'$.draws',json('false'))")
        before=business_state(f.db)
        self.assertNotIn("钓鱼帮助",self.follow(f,"二狗菜单"))
        self.assertNotIn("抽签 报名",self.follow(f,"二狗互动帮助"))
        self.assertNotIn("鱼饵",self.follow(f,"二狗积分帮助"))
        self.assertNotIn("【游戏帮助】",self.follow(f,"二狗全菜单"))
        self.assertEqual(before,business_state(f.db))
        with patch.dict(os.environ,{"ERGOU_KDN_KEY":"","ERGOU_DHL_KEY":""}):
            self.assertNotIn("快递帮助",self.follow(f,"二狗全菜单"))
            self.assertIn("暂未接通",self.follow(f,"二狗快递 申通 12345678"))
        result=self.follow(f,"二狗兑换 选片权")
        self.assertIn("还差 3 分，未扣积分",result)
        self.follow(f,"二狗签到")
        choice=self.follow(f,"二狗兑换列表").splitlines()[-1]
        self.assertIn("剩余 0 分",self.follow(f,choice))

    def test_missing_fish_numbers_give_current_objects(self):
        f=self.player()
        self.assertIn("二狗放入鱼塘",self.follow(f,"二狗投喂"))
        self.follow(f,"二狗放入鱼塘#71")
        for query,outcome in (("查看鱼","原重"),("投喂","已投喂"),("设为招牌鱼","免于被偷")):
            result=self.follow(f,"二狗"+query)
            command=result.splitlines()[-1]
            self.assertEqual(command,"二狗"+query+"#71")
            self.assertIn(outcome,self.follow(f,command))
        self.assertIn("没有需要",self.follow(f,"二狗换入成长位"))

    def test_custom_prefix_from_directory_to_receipt(self):
        f=self.player()
        f.db.execute("UPDATE groups SET config=json_set(config,'$.prefix','团团')")
        menu=f.send("二狗菜单")
        self.assertEqual(menu,f.send("团团菜单"))
        self.assertIn("团团全菜单",menu.splitlines())
        for cmd in commands(menu,"团团"):
            self.assertTrue(self.follow(f,cmd))
        self.assertIsNone(f.send("天气帮助"))
        self.assertIsNone(f.send("@二狗　天气帮助",True))
        help_page=self.follow(f,"团团查天气帮助")
        self.assertEqual(help_page.splitlines()[-1],"团团天气 抚州")
        self.assertIn("18",self.follow(f,help_page.splitlines()[-1]))
        result=self.follow(f,"团团卖鱼")
        self.assertIn("团团卖鱼#71",result.splitlines())
        self.assertIn("到账 8",self.follow(f,result.splitlines()[-1]))

    def test_smart_switch_instructions(self):
        f=self.player()
        f.db.execute('UPDATE smart_controls SET admins=?',(json.dumps([f.api.details["senderId"]]),))
        body=self.follow(f,"二狗管理帮助")
        for cmd in ("关闭智能对话","开启智能对话"):
            self.assertIn("@二狗 "+cmd,commands(body))
            result=f.send("@二狗　"+cmd,True)
            self.assertTrue(result)
            self.assertEqual(f.db.execute("SELECT enabled FROM smart_controls").fetchone()[0],int(cmd=="开启智能对话"))
        self.assertIsNone(f.send("@二狗　天气帮助",True))
        self.assertEqual(f.db.execute("SELECT prompt FROM chat_requests").fetchone()[0],"天气帮助")

    def test_role_and_local_keyword_examples(self):
        from tests.test_owner_roles import OwnerRoles
        f=OwnerRoles()
        f.setUp()
        self.addCleanup(f.doCleanups)
        key=(f.group,)
        f.db.execute("INSERT INTO reply_rule_sets VALUES(?,1,?)",(*key,json.dumps([dict(keyword="集合地点",mode="exact",kind="text",content="东门集合。")])))
        self.assertIn("群关键词",f.say("reader","关键词帮助"))
        self.assertEqual("东门集合。",f.say("reader","集合地点"))
        f.say("parent","授权群主")
        self.assertIn("已授权",f.say("chief","查看群主状态"))
        self.assertIn("已授权管理员",f.say("chief","授权管理员","helper"))
        self.assertIn("已取消管理员",f.say("chief","取消管理员","helper"))
        self.assertIn("投票关",f.say("chief","本群设置 投票 关闭"))
        self.assertIn("关闭",f.say("parent","全局配置 新群游戏 关闭"))
        self.assertIn("已取消群主授权",f.say("parent","取消群主授权"))
        self.assertIn("主人已转移",f.say("parent","主人转移","next"))
