"""v1.9 冻结基线：所有剧情与奖励均由正常消息提交，微信身份与时间隔离。"""

from datetime import datetime
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ergou import db, engine, jianghu_rules as rules, jobs


class JianghuReplay(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "p1.sqlite"
        db.initialize(self.path)
        db.demo(self.path, ("east", "west"))
        self.conn = self.enterContext(db.closing_db(self.path))
        self.now = datetime(2026, 11, 22, 8, tzinfo=db.BJ).timestamp()
        self.group = "east"
        self.n = 0
        self.conn.execute(
            "INSERT INTO bot_owner(bot_id,owner_user_id,bound_at) VALUES('sim-account','owner',0)"
        )
        for grp in ("east", "west"):
            self.conn.execute(
                "INSERT INTO directed_groups(grp,account,binding,since) VALUES(?,'sim-account',1,0)",
                (grp,),
            )
            self.conn.execute(
                """INSERT INTO group_binding(group_id,bot_id,bound_at,label,checked)
                VALUES(?,'sim-account',0,?,0)""",
                (grp, grp),
            )
        self.say("开启江湖", member="owner")

    def send(self, text, member="leaf", source=None, process=False, extra=None):
        self.n += 1
        source = source or str(self.n)
        seq = engine.receive(
            self.conn,
            "sim-account",
            self.group,
            member,
            source,
            {"text": text, **(extra or {})},
            now=self.now,
        )
        if process:
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys;from ergou.db import closing_db;from ergou.engine import step\n"
                    "with closing_db(sys.argv[1]) as conn: step(conn)",
                    str(self.path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
            )
        else:
            engine.step(self.conn)
        row = self.conn.execute(
            "SELECT body FROM outbox JOIN inbox ON biz=event_id WHERE seq=?", (seq,)
        ).fetchone()
        return row[0] if row else ""

    def say(self, cmd, **kw):
        return self.send("二狗" + cmd, **kw)

    def record(self, member="leaf"):
        return dict(
            self.conn.execute(
                "SELECT * FROM jh_players WHERE grp=? AND member=?", (self.group, member)
            ).fetchone()
        )

    def create(self, stats, member="leaf"):
        for cmd in (
            "闯江湖",
            "选 1",
            "加点 " + " ".join(k + str(v) for k, v in zip(rules.ATTRIBUTES, stats)),
            "确认加点",
        ):
            self.say(cmd, member=member)
        self.assertIsNone(self.record(member)["route"])

    def start(self, stats, route, member="leaf"):
        self.create(stats, member)
        msg = self.say("选 " + ("1" if route == "拳" else "2"), member=member)
        if self.record(member)["first_win_at"] is None:
            msg = self.send(msg.splitlines()[-1], member=member)
        p = self.record(member)
        self.assertEqual((p["level"], p["silver"], p["potential"], p["route"]), (1, 50, 10, route))
        self.send(msg.splitlines()[-1], member=member)
        self.assertEqual(self.record(member)["level"], 2)
        self.say("打坐", member=member)

    def level_three(self, route, member="leaf"):
        self.say("打坐", member=member)
        self.say("练" + route, member=member)
        self.assertEqual(self.record(member)["level"], 3)

    def ending(self, member, ending, first_level, subprocess_loss=False):
        route = "拳" if ending in ("解围", "自胜") else "剑"
        self.start((0, 40, 0, 40) if ending == "解围" else (40, 10, 10, 20), route, member)
        self.now += 86400
        if first_level:
            self.level_three(route, member)
        self.assertIsNone(self.record(member)["completed_at"])
        self.say("主线", member=member)
        if ending == "解围":
            # 打坐后先吃饱，再让全流程在真实子进程内处理，退出后换新进程。
            self.say("吃包子", member=member)
            self.assertGreaterEqual(self.record(member)["hunger"], 20)
            loss = self.say("历练", member=member, process=subprocess_loss)
            self.assertIn("第3回合", loss)
            self.assertIn("没能击退", loss)
            self.assertEqual(
                (self.record(member)["next_state"], self.record(member)["defeated"]), ("fight", 1)
            )
            exact_line = loss.splitlines()[-1]
            offered = self.send(exact_line, member=member, process=subprocess_loss)
            self.assertIn("亮出信物", offered)
            choose = offered.splitlines()[-1]
            receipt = self.send(choose, member=member, source="choose-" + self.group + member)
            self.send(choose, member=member, source="choose-" + self.group + member)
        elif ending == "自胜":
            receipt = self.say("历练", member=member)
        else:
            receipt = self.say(
                "选 " + ("1" if ending == "加入" else "2"),
                member=member,
                source="offer-" + self.group + member,
            )
        self.assertEqual(self.record(member)["ending"], ending)
        if not first_level:
            self.assertIsNone(self.record(member)["completed_at"])
            self.level_three(route, member)
        else:
            self.assertIn("已完成", receipt)
        self.say("主线", member=member)
        self.assertIsNotNone(self.record(member)["completed_at"])
        events = dict(
            self.conn.execute(
                """SELECT event_type,count(*) FROM jh_events
            WHERE grp=? AND member=? GROUP BY event_type""",
                (self.group, member),
            )
        )
        self.assertEqual(events.get("chapter_done"), 1)
        self.assertEqual(events.get("join_broadcast", 0), int(ending == "加入"))
        if ending == "解围":
            self.assertIn("引路人出手制敌", self.say("面板", member=member))

    def test_r1_through_r6(self):
        for n, (ending, first_level) in enumerate(
            (
                ("解围", True),
                ("自胜", False),
                ("加入", True),
                ("加入", False),
                ("婉拒", True),
                ("婉拒", False),
            ),
            1,
        ):
            with self.subTest(route=n):
                self.ending("r" + str(n), ending, first_level, n == 1)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM outbox WHERE body LIKE '%🎉 恭喜%'").fetchone()[
                0
            ],
            2,
        )

    def test_groups(self):
        for grp in ("east", "west"):
            self.group = grp
            self.say("开启江湖", member="owner")
            self.ending("same", "加入", True)
        self.group = "east"
        self.send("二狗选 1", member="same", source="offer-eastsame")
        self.assertEqual(
            [
                tuple(r)
                for r in self.conn.execute("""SELECT grp,count(*) FROM jh_events
            WHERE event_type='join_broadcast' GROUP BY grp ORDER BY grp""")
            ],
            [("east", 1), ("west", 1)],
        )

    def test_meditation_normal_capped_remainder(self):
        start = self.now
        fighter = (40, 10, 10, 20)
        for member, stats in (
            ("w1", fighter),
            ("w2", fighter),
            ("long", (20, 20, 20, 20)),
            ("twice", (20, 20, 20, 20)),
            ("once", (20, 20, 20, 20)),
        ):
            self.start(stats, "拳", member)
            self.say("吃包子", member=member)
            self.assertEqual(self.record(member)["hunger"], 100)
        initial_silver = self.record("w2")["silver"]
        # 固定随机输入，隔离按次抽取的奇遇与买包子的支出。
        with patch("ergou.jianghu.random.Random.randrange", return_value=99):
            for hour in range(1, 5):
                self.now = start + hour * 3600
                self.say("打坐", member="w2")
                if self.record("w2")["hunger"] < 20:
                    self.say("吃包子", member="w2")
            self.say("打坐", member="w1")
            self.assertEqual(
                (self.record("w1")["potential"], self.record("w2")["potential"]), (16, 16)
            )
            self.assertEqual(self.record("w1")["hunger"], 0)
            self.assertEqual(self.record("w2")["silver"], initial_silver - 10)
            for hour in (6, 12):
                self.now = start + hour * 3600
                self.say("打坐", member="twice")
            self.say("打坐", member="once")
            self.assertEqual(
                (self.record("twice")["potential"], self.record("once")["potential"]), (72, 60)
            )
            self.now = start + 36 * 3600 + 1200
            self.say("打坐", member="long")
            expected = start + 36 * 3600
            p = self.record("long")
            self.assertEqual((p["potential"], p["meditate_at"]), (60, expected))
            self.say("打坐", member="long")  # 新消息 ID
            self.assertEqual(p, self.record("long"))
            self.now -= 3600
            self.say("打坐", member="long")
            self.assertEqual(p, self.record("long"))
            self.now = start + 37 * 3600
            self.say("面板", member="long")
            self.assertEqual(p, self.record("long"))
            self.say("打坐", member="long")
            self.assertEqual(self.record("long")["potential"], 66)
            self.assertEqual(self.record("long")["meditate_at"], self.now)

    def test_params_and_initiative(self):
        for s, c, hp, dmg, rate, hours in [
            (20, 20, 300, [103, 106, 109], 6, 3),
            (40, 10, 500, [203, 206, 209], 4, 4),
            (0, 0, 100, [3, 6, 9], 2, 8),
        ]:
            for level in (1, 2, 3):
                p = dict(strength=s, constitution=c, level=level, route="拳", agility=20, hunger=20)
                f = rules.fighter(p, "甲")
                self.assertEqual(
                    (f.hp, rules.damage(f, rules.ENEMIES["蒙面人"])), (hp, dmg[level - 1])
                )
                p["hunger"] = 19
                self.assertEqual(
                    rules.damage(rules.fighter(p, "甲"), rules.ENEMIES["蒙面人"]),
                    max(1, dmg[level - 1] // 2),
                )
            self.assertEqual(rules.meditation(0, 3600, c)[1], rate)
            self.assertLess((hours - 1) * rate, 15)
            self.assertGreaterEqual(hours * rate, 15)
        rng = random.Random()
        a = rules.Fighter("甲", 100, 15, 10, 20)
        b = rules.Fighter("乙", 100, 15, 10, 20)
        for first in (0, 1):
            with patch.object(rng, "randrange", return_value=first):
                self.assertIn("第1回合　" + ("甲", "乙")[first], rules.fight(a, b, rng)[1])
        self.assertIn("第1回合　乙", rules.fight(a, rules.Fighter("乙", 100, 15, 10, 21), rng)[1])

    def test_draft_and_reward_restart_at_midnight(self):
        self.say("闯江湖")
        self.say("选 1")
        self.say("加点 臂力0 身法40 根骨0 悟性40")
        self.assertIn("少", self.say("加点 臂力20 身法10 根骨10 悟性20"))
        self.say("加点 悟性20 身法10 根骨10 臂力40")
        self.say("确认加点", process=True)
        self.assertEqual(self.record()["title"], "莽撞武夫")
        midnight = datetime(2026, 11, 23, tzinfo=db.BJ).timestamp()
        self.now = midnight - 1
        self.say("选 1", source="reward", process=True)
        p = self.record()
        self.assertEqual((p["silver"], p["potential"]), (50, 10))
        self.say("选 1", source="reward", process=True)
        self.assertEqual(self.record(), p)
        self.assertIn("明日", self.say("主线"))
        self.now = midnight
        self.assertIn("蒙面人", self.say("主线"))

    def test_receipt_guidance_across_midnight_with_group_prefix(self):
        self.now = datetime(2026, 11, 22, 23, 30, 47, tzinfo=db.BJ).timestamp()
        self.start((20, 20, 30, 10), "剑", "leaf")
        self.conn.execute(
            "UPDATE groups SET config=json_set(config,'$.prefix','小侠') WHERE id='east'"
        )
        meal = self.send("小侠吃包子")
        self.assertEqual(meal.splitlines()[-1], "小侠打坐")  # 当前潜能不足以升级。
        before = self.record()
        self.now += 3599
        waiting = self.send(meal.splitlines()[-1])
        self.assertIn("北京时间 2026-11-23 00:30:47", waiting)
        self.assertEqual(waiting.splitlines()[-1], "小侠打坐")
        self.assertEqual(self.record(), before)
        self.now += 1
        self.send(waiting.splitlines()[-1])
        self.assertEqual(self.record()["potential"], before["potential"] + 8)

        self.send("小侠主线")
        self.assertEqual(self.record()["next_state"], "offer")
        meal = self.send("小侠吃包子")
        self.assertEqual(meal.splitlines()[-1], "小侠主线")
        offer = self.send(meal.splitlines()[-1])
        self.assertEqual(offer.splitlines()[-2:], ["小侠选 1", "小侠选 2"])

    def test_two_players_follow_their_own_start_and_training(self):
        self.say("闯江湖", member="sword")
        self.assertIn("你在本群还没有角色", self.say("选 2", member="fist"))
        self.say("闯江湖", member="fist")
        self.assertIn("镖局学徒", self.say("选 2", member="fist"))
        self.assertIn("平民", self.say("选 1", member="sword"))
        for member, stats, cost, choice, route, rate in (
            ("sword", "臂力10　身法16　根骨35　悟性19", 20, 2, "剑", 9),
            ("fist", "臂力20 身法10 根骨10 悟性40", 15, 1, "拳", 4),
        ):
            self.assertEqual(self.send(stats, member=member), "")
            draft = self.say(stats, member=member)
            self.assertIn(f"升三级花 {cost} 潜能", draft)
            intro = self.send(draft.splitlines()[-1], member=member)
            self.assertIn("选 1 拆开查看", intro)
            self.assertIn("选 2 原封退还", intro)
            win = self.say(f"选 {choice}", member=member)
            level = self.send(win.splitlines()[-1], member=member)
            self.assertIn(f"还差 {cost} 潜能", level)
            rest = self.send(level.splitlines()[-1], member=member)
            self.assertIn(f"每小时 {rate} 点", rest)
            self.assertIn("09:00:00", rest)
            again = self.say("练" + route, member=member)
            self.assertIn("12:00:00" if route == "拳" else "11:00:00", again)
            before = self.record(member)
            self.assertIn("属性已锁定", self.say("加点 " + stats, member=member))
            self.assertIn(f"Lv.{before['level']}", self.say("闯江湖", member=member))
            self.assertEqual(before, self.record(member))

    def test_personal_panel_previews_meditation_without_claiming(self):
        self.create((20, 10, 10, 40))
        self.assertIn("当前状态：待决定镖信去向", self.say("面板"))
        self.say("选 1")
        self.assertIn("当前状态：未开始打坐", self.say("面板"))
        self.say("练拳")
        self.say("打坐")
        before = self.record()
        self.now += 3599
        self.assertIn("打坐中 · 尚未满一小时", self.say("面板"))
        self.now += 1
        for cmd in ("面板", "江湖面板", "闯江湖"):
            self.assertIn("打坐中 · 可领 4 潜能", self.say(cmd))
        self.assertEqual(self.record(), before)
        self.now += 86400
        panel = self.say("面板")
        self.assertIn("打坐中 · 可领 48 潜能", panel)
        self.assertIn("镖信续章已开放", panel)
        self.assertEqual(self.record(), before)
        self.say("主线")
        self.assertIn("主线：待迎战蒙面人", self.say("面板"))
        self.assertIn("常规潜能 +48", self.say("打坐"))
        self.assertIn("打坐中 · 尚未满一小时", self.say("面板"))

    def test_invites_close_and_dispatch(self):
        for member in ("a", "b", "c"):
            self.start((40, 10, 10, 20), "拳", member)
        self.assertIn("权限不足", self.say("关闭江湖", member="a"))

        def invite(actor, target):
            return self.say("切磋 @群友", member=actor, extra={"duel_target": target})

        self.assertIn("收到了", invite("a", "b"))
        self.assertIn("待回应", invite("c", "a"))
        self.now += 300
        self.assertIn("没有", self.say("应战", member="b"))
        invite("a", "b")
        self.assertIn("婉拒", self.say("拒绝", member="b"))
        invite("a", "b")
        before = self.record("b")
        self.assertIn("无损切磋", self.say("应战", member="b"))
        self.assertEqual(self.record("b"), before)
        invite("a", "b")
        self.say("关闭江湖", member="owner")
        self.say("开启江湖", member="owner")
        self.assertIn("没有", self.say("应战", member="b"))
        while True:
            row = jobs.claim(self.conn, "sim-account", now=self.now)
            if not row:
                break
            if isinstance(row, dict):
                self.assertNotIn("回合", row["body"])
                jobs.finish(
                    self.conn,
                    "sim-account",
                    row["id"],
                    row["attempt"],
                    "ACKNOWLEDGED",
                    "模拟",
                    self.now,
                )
        self.assertEqual(
            self.conn.execute("""SELECT count(*) FROM attempts a JOIN jh_replies j ON a.task=j.task
              WHERE j.version=1""").fetchone()[0],
            0,
        )
        self.assertEqual(self.send("闯江湖", member="silent"), "")

    def test_two_writers_and_two_directions(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        for member in ("a", "b", "c"):
            self.start((20, 20, 20, 20), "拳", member)
        barrier = Barrier(2)

        def run(spec):
            actor, target = spec
            with db.closing_db(self.path) as conn:
                barrier.wait(5)
                engine.receive(
                    conn,
                    "sim-account",
                    "east",
                    actor,
                    "duel-" + actor,
                    {"text": "二狗切磋 @群友", "duel_target": target},
                    now=self.now,
                )
                engine.step(conn)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, [("a", "b"), ("c", "a")]))
        invitations = self.conn.execute("SELECT inviter,invitee FROM jh_invites").fetchall()
        self.assertEqual(len(invitations), 1)
        invitee = invitations[0]["invitee"]
        self.say("关闭江湖", member="owner")
        self.say("开启江湖", member="owner")
        self.assertIn("没有", self.say("应战", member=invitee))

    def test_local_only_menu_prefix_and_unopened_rooms(self):
        self.conn.execute(
            "UPDATE groups SET config=json_set(config,'$.prefix','小侠') WHERE id='east'"
        )
        for menu in ("菜单", "全菜单"):
            self.assertIn("【江湖录帮助】", self.send("小侠" + menu))
        for alias in ("江湖帮助", "江湖菜单", "江湖录菜单"):
            self.assertEqual(self.send("小侠" + alias), self.send("小侠江湖录帮助"))
        self.assertIn("小侠闯江湖", self.send("小侠江湖帮助"))
        self.conn.execute(
            "INSERT INTO chat_models VALUES('east',1,'glm','fixture',?,?)", (b"fixture", self.now)
        )
        self.send("@小侠　闯江湖", extra={"mention_account": "sim-account"})
        self.assertEqual(
            self.conn.execute("SELECT prompt FROM chat_requests").fetchone()[0], "闯江湖"
        )
        self.assertFalse(self.conn.execute("SELECT 1 FROM jh_drafts").fetchone())
        self.send("小侠闯江湖")
        self.assertTrue(self.conn.execute("SELECT 1 FROM jh_drafts WHERE grp='east'").fetchone())
        self.group = "west"
        for menu in ("菜单", "全菜单"):
            self.assertNotIn("江湖录帮助", self.say(menu))
        self.assertIn("暂未开启", self.say("江湖录帮助"))
        self.assertIn("尚未开启", self.say("闯江湖"))
        self.assertFalse(self.conn.execute("SELECT 1 FROM jh_drafts WHERE grp='west'").fetchone())
        self.assertIn("积分", self.say("积分"))


class NativeR1(unittest.TestCase):
    def test_follow_receipt_across_worker_restart(self):
        from ergou import agent_wechat
        from tests.test_agent_wechat import Fixture

        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "native.sqlite"
        db.initialize(path)
        conn = self.enterContext(db.closing_db(path))
        api = Fixture()
        secret = "r1-fixture" * 5
        agent_wechat.link(conn, api, "测试群", secret)
        listener = agent_wechat.Listener(conn, api, secret)
        now = datetime(2026, 11, 22, 8, tzinfo=db.BJ).timestamp()
        cursor = 12
        conn.execute(
            "INSERT INTO directed_groups(grp,account,binding,since) VALUES(?,?,1,?)",
            (api.room, api.account, now - 2),
        )
        conn.execute(
            "INSERT INTO bot_owner(bot_id,owner_user_id,bound_at) VALUES(?,?,?)",
            (api.account, "member", now),
        )

        # 使用生产监听器的入站过滤、bridge 鉴权、真实指令路由及 outbox。
        def incoming(text, *, worker=False, source=None, mentioned=False):
            nonlocal cursor
            cursor += 1
            with patch("time.time", return_value=now):
                listener.verify()
                api.details.update(
                    body=text,
                    mentions={
                        "state": "known",
                        "self": mentioned,
                        "all": False,
                        "userIds": [api.account] if mentioned else [],
                    },
                    serverId=str(source or cursor),
                    createdAt=datetime.fromtimestamp(now, db.BJ).isoformat(),
                )
                seq = listener.consume(
                    dict(
                        cursor=str(cursor),
                        kind="message.committed",
                        data=dict(
                            threadId=api.room,
                            messageId="upstream-row",
                            origin="live",
                            direction="incoming",
                        ),
                    )
                )
                if not seq:
                    return ""
                if worker:
                    subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import sys;from unittest.mock import patch;from ergou import db,engine\n"
                            "with patch('time.time',return_value=float(sys.argv[2])),db.closing_db(sys.argv[1]) as c: engine.step(c)",
                            str(path),
                            str(now),
                        ],
                        cwd=Path(__file__).resolve().parents[1],
                        check=True,
                    )
                else:
                    engine.step(conn)
            row = conn.execute(
                "SELECT body FROM inbox JOIN outbox ON biz=event_id WHERE seq=?", (seq,)
            ).fetchone()
            return row[0] if row else ""

        from ergou import reply_rules

        conn.execute(
            "INSERT INTO chat_models VALUES(?,1,'glm','fixture',?,?)", (api.room, b"fixture", now)
        )
        mock_rule = reply_rules.validate_rules(
            [
                dict(mode="contains", keyword=keyword, kind="text", content="群内关键词回执")
                for keyword in ("主线", "历练", "打坐", "确认加点")
            ]
        )
        conn.execute("INSERT INTO reply_rule_sets VALUES(?,1,?)", (api.room, db.dump(mock_rule)))

        def model_count():
            return conn.execute("SELECT count(*) FROM chat_requests").fetchone()[0]

        self.assertEqual(incoming("历练"), "")
        self.assertEqual(model_count(), 0)
        self.assertEqual(incoming("@二狗\u2005历练", mentioned=True), "")
        self.assertEqual(model_count(), 1)
        self.assertEqual(incoming("二狗聊聊主线"), "群内关键词回执")
        for cmd in (
            "开启江湖",
            "闯江湖",
            "选 1",
            "加点 臂力0 身法40 根骨0 悟性40",
            "确认加点",
            "选 1",
        ):
            body = incoming("二狗" + cmd)
        self.assertIn("再战", body)
        restored = incoming(body.splitlines()[-1])
        incoming(restored.splitlines()[-1])
        incoming("二狗打坐")
        now += 86400
        incoming("二狗打坐")
        incoming("二狗练拳")
        incoming("二狗吃包子")
        entering = incoming("二狗主线")
        self.assertIn("那封镖信招来了蒙面人", entering)
        self.assertEqual(conn.execute("SELECT count(*) FROM reply_rule_hits").fetchone()[0], 1)
        before_model = model_count()
        loss = incoming(entering.splitlines()[-1], worker=True)
        self.assertNotEqual(loss, engine.UNKNOWN_COMMAND.format(prefix="二狗"))
        self.assertTrue(loss.startswith("⚔️ 迎战蒙面人\n第1回合"))
        self.assertEqual(
            conn.execute(
                "SELECT defeated FROM jh_players WHERE grp=? AND member='member'", (api.room,)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(model_count(), before_model)
        self.assertIn("没能击退", loss)
        raw = conn.execute(
            """SELECT o.body FROM outbox o JOIN inbox i ON i.event_id=o.biz
                WHERE i.source=?""",
            (str(cursor),),
        ).fetchone()[0]
        self.assertEqual(raw, loss)
        listener = agent_wechat.Listener(conn, api, secret)
        option = incoming(raw.splitlines()[-1], worker=True)
        action = option.splitlines()[-1]
        receipt = incoming(action)
        original = cursor
        incoming(action, source=original)
        self.assertEqual(model_count(), before_model)
        self.assertIn("引路人出手制敌", receipt)
        self.assertEqual(
            dict(conn.execute("SELECT event_type,count(*) FROM jh_events GROUP BY event_type")),
            {"first_win": 1, "chapter_done": 1},
        )
