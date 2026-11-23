"""微信入站、短时钟、同群多人资产与跨群重放。"""

from datetime import datetime
import random
import pytest

from ergou import db as storage, jianghu_rules as rules
from ergou.jianghu_martial import Duelist, resolve
from tests import test_jianghu as baseline
from tests.jianghu.transport import session, START


@pytest.fixture
def room():
    sim = baseline.JianghuReplay()
    sim.setUp()
    try:
        yield sim
    finally:
        sim.doCleanups()


def ready(s, name="leaf", silver=100):
    # 已通关玩家夹具；完整从冷启动开始的路径另经微信监听器验证。
    s.conn.execute(
        """INSERT INTO jh_players(grp,member,identity,strength,agility,constitution,insight,luck,title,route,level,
                 first_win_at,ending,completed_at,next_state,silver,potential)
                 VALUES(?,?,'平民',40,20,10,10,5,'武夫','拳',3,?,'自胜',?,'done',?,600)""",
        (s.group, name, s.now - 8 * 86400, s.now - 1, silver),
    )
    s.say("江湖身世", member=name)


def mention(s, cmd, to, member="leaf", **kwargs):
    return s.say(cmd, member=member, extra={"duel_target": to}, **kwargs)


def scalar(s, sql, *args):
    return s.conn.execute(sql, args).fetchone()[0]


def test_real_listener_chapters_and_replay(tmp_path):
    with session(tmp_path / "wechat.sqlite") as w:
        t = START
        for cmd in (
            "闯江湖",
            "选 1",
            "加点 臂力40 身法10 根骨10 悟性20",
            "确认加点",
            "选 2",
            "练剑",
            "打坐",
        ):
            _, body = w.send("二狗" + cmd, t)
            assert body and "没看懂" not in body
        t += 10 * 60
        for cmd in ("打坐", "练剑", "主线", "选 2", "主线", "独行江湖", "运镖"):
            _, body = w.send("二狗" + cmd, t)
            assert body and "没看懂" not in body
        w.restart()
        assert "镖货" in w.send("二狗交镖", t + 179)[1]
        assert "到账 20 两" in w.send("二狗交镖", t + 180)[1]
        assert "还没有接镖" in w.send("二狗交镖", t + 180)[1]
        assert "第二章已完成" in w.send("二狗取回账册", t + 180)[1]
        msg = w.send("二狗决战黑木崖", t + 180)[1]
        if "第三章已完成" not in msg:
            msg = w.send(msg.splitlines()[-1], t + 180)[1]
        assert "第三章已完成" in msg
        assert "已装备" in w.send(msg.splitlines()[-1], t + 180)[1]
        assert not w.send("加入恩怨", t + 180)[1]
        assert not w.send("@二狗 暗杀", t + 180, mentioned=True)[1]


def test_market_gold_and_bounty(room):
    s = room
    for name in ("leaf", "b", "c", "owner"):
        ready(s, name, 9000)
    item = s.conn.execute(
        "INSERT INTO jh_goods(grp,member,name,power) VALUES('east','b','短刀',8)"
    ).lastrowid
    assert "5000" in s.say(f"洗练#{item}", member="b")
    s.say(f"确认洗练#{item}", member="b", source="reforge")
    s.say(f"确认洗练#{item}", member="b", source="reforge")
    assert s.record("b")["silver"] == 4000
    s.say(f"上架#{item} 21", member="b")
    s.say(f"购买装备#{item} 20")
    assert s.record()["silver"] == 9000
    s.say(f"购买装备#{item} 21")
    s.say(f"购买装备#{item} 21", member="c")
    assert (s.record()["silver"], s.record("b")["silver"], s.record("c")["silver"]) == (
        8979,
        4019,
        9000,
    )
    mention(s, "赐金条 @c 5", "c")
    assert not scalar(s, "SELECT gold FROM jh_world WHERE member='c'")
    mention(s, "赐金条 @c 5", "c", "owner")
    s.say("确认发江湖红包", member="c", source="packet")
    s.say("确认发江湖红包", member="c", source="packet")
    assert "领到 5" in s.say("领江湖红包")
    assert "没有" in s.say("领江湖红包")
    for name in ("leaf", "b", "c"):
        s.say("加入恩怨", member=name)
    start = s.record()["silver"]
    assert "已托管" in mention(s, "悬赏 @b 200", "b")
    assert s.record()["silver"] == start - 200
    s.say("退出恩怨", member="b")
    assert (
        s.record()["silver"] == start
        and scalar(s, "SELECT count(*) FROM jh_contracts") == 0
    )
    s.say("加入恩怨", member="b")
    s.conn.execute(
        "UPDATE jh_players SET strength=0,constitution=0,agility=0 WHERE member='b'"
    )
    mention(s, "悬赏 @b 200", "b")
    bal = s.record("b")["silver"]
    outcome = mention(s, "暗杀 @b", "b", "c", source="strike")
    assert "保护" in outcome
    assert s.record("b")["silver"] == bal - bal // 10
    assert s.record("c")["silver"] == 9000 + 200 + bal // 10
    mention(s, "暗杀 @b", "b", "c", source="strike")
    assert "保护" in mention(s, "暗杀 @b", "b", "leaf")
    assert s.record("b")["silver"] == bal - bal // 10
    s.group = "west"
    s.say("开启江湖", member="owner")
    ready(s)
    assert "对方还没有" in mention(s, "暗杀 @b", "b")
    assert "暂无悬赏" in s.say("悬赏榜")


def test_kinship_training_house_retirement(room):
    s = room
    for n in ("leaf", "b"):
        ready(s, n)
    assert "五分钟" in mention(s, "拜师 @b", "b")
    assert "没有可处理" in s.say("接受师徒")
    s.now += 301
    assert "没有可处理" in s.say("接受师徒", member="b")
    mention(s, "拜师 @b", "b")
    s.say("接受师徒", member="b")
    initial = s.record("b")["potential"]
    for skill in ("太极剑", "九阳功"):
        for lv in range(1, 6):
            assert f"{lv} 级" in s.say("研习" + skill)
    assert s.record("b")["potential"] == initial + 10
    assert "院门" in s.say("购买宅院")
    assert "5 潜能" in s.say("家园收功")
    assert "已经" in s.say("家园收功") or "已在" in s.say("家园收功")
    assert "黑木崖结案" in s.say("确认转生")
    s.conn.execute("UPDATE jh_world SET stage=4 WHERE member='leaf'")
    assert "100点" in s.say("确认转生")
    assert "已重配" in s.say("重配天赋 臂力40 身法20 根骨20 悟性20")
    assert s.record()["strength"] == 40
    assert "洗点券" in s.say("重配天赋 臂力40 身法20 根骨20 悟性20")
    s.say("关闭江湖", member="owner")
    before = s.record()["silver"]
    s.say("确认发江湖红包")
    assert s.record()["silver"] == before


@pytest.mark.parametrize("days", [7, 30])
def test_cash_conservation_over_days(room, days):
    s = room
    ready(s, silver=0)
    for day in range(days):
        s.say("运镖")
        s.now += 180
        assert "到账 20" in s.say("交镖", source=f"delivery-{day}")
        s.say("交镖", source=f"delivery-{day}")
        if day == 3:
            s.say("购买宅院")
        s.now += 86400 - 180
    assert (
        s.record()["silver"]
        == days * 20 - 80
        == scalar(s, "SELECT SUM(silver) FROM jh_money_log")
    )


def test_contest_window_final_hit_and_rewards(room):
    s = room
    ready(s)
    s.now = datetime(2026, 11, 28, 19, 59, 59, tzinfo=storage.BJ).timestamp()
    assert "20:00" in s.say("围攻")
    s.now += 1
    for i in range(12):
        out = s.say("围攻")
        if "最后一击" in out:
            break
        assert "两分钟" in s.say("围攻")
        s.now += 120
    assert "最后一击" in out
    assert (
        scalar(s, "SELECT sum(score) FROM jh_encounters WHERE activity='首领'") == 800
    )
    assert "已被击退" in s.say("围攻")
    s.say("投身正道")
    assert "贡献" in s.say("阵营战")
    assert "贡献" in s.say("华山论剑")
    s.now += 3 * 3600
    assert "到账" in s.say("大会领奖")
    assert "还没有" in s.say("大会领奖")
    s.now += 2 * 86400
    assert "3 金条" in s.say("大会领奖")
    assert scalar(s, "SELECT gold FROM jh_world") == 5


def test_martial_seed_and_effects():
    body = rules.Fighter("少侠", 300, 60, 15, 30)
    other = Duelist(rules.Fighter("守擂人", 120, 35, 8, 15))
    for inner in ("九阳功", "北冥秘术", "太白经", "双手互搏"):
        for seed in range(12):
            player = Duelist(body, "降龙掌", inner, 5, 5, 90)
            a = resolve(player, other, random.Random(seed))
            assert a == resolve(player, other, random.Random(seed))
            assert 1 <= len(a[1].splitlines()) <= 3


def test_concurrent_market_and_last_hit(room):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from ergou import engine

    s = room
    for n in ("leaf", "b", "c"):
        ready(s, n)
    ident = s.conn.execute(
        "INSERT INTO jh_goods(grp,member,name,power,price) VALUES('east','leaf','青锋剑',4,20)"
    ).lastrowid

    def race(cmd, label):
        gate = Barrier(2)

        def send(name):
            with storage.closing_db(s.path) as conn:
                gate.wait(timeout=5)
                engine.receive(
                    conn,
                    "sim-account",
                    "east",
                    name,
                    label + name,
                    {"text": "二狗" + cmd},
                    now=s.now,
                )
                engine.step(conn)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(send, ("b", "c")))
        while engine.step(s.conn):
            pass

    race(f"购买装备#{ident} 20", "race-buy")
    balances = sorted(s.record(n)["silver"] for n in ("b", "c"))
    assert balances == [80, 100] and s.record()["silver"] == 119
    s.now = datetime(2026, 11, 28, 20, 5, tzinfo=storage.BJ).timestamp()
    s.conn.execute(
        "INSERT INTO jh_encounters VALUES('east','首领','2026-11-28','leaf',799,0,'',0)"
    )
    race("围攻", "race-boss")
    assert (
        scalar(s, "SELECT sum(score) FROM jh_encounters WHERE activity='首领'") == 800
    )
    assert scalar(s, "SELECT sum(gold) FROM jh_world") == 1


def test_gifts_novices_ward_and_points(room):
    s = room
    ready(s)
    ready(s, "b")
    assert "发放 3" in mention(s, "赐金条 @b 3", "b", "owner")
    s.say("兑换免死金牌", member="b")
    s.say("兑换大还丹", member="b")
    s.conn.execute(
        "UPDATE jh_players SET hunger=1,strength=0,agility=0,constitution=0 WHERE member='b'"
    )
    assert "恢复" in s.say("服大还丹", member="b")
    assert "还差 5" in s.say("兑换江湖天赋")
    assert "签到到账" in s.say("签到")
    s.now += 86400
    s.say("签到")
    assert "已扣本群 5 积分" in s.say("兑换江湖天赋")
    assert "已获" in s.say("兑换江湖天赋")
    assert (
        scalar(s, "SELECT SUM(points) FROM ledger WHERE grp='east' AND member='leaf'")
        == 1
    )
    for n in ("b", "leaf"):
        s.say("加入恩怨", member=n)
    s.conn.execute("UPDATE jh_players SET first_win_at=? WHERE member='b'", (s.now,))
    assert "保护" in mention(s, "暗杀 @b", "b")
    s.now += 7 * 86400
    # 不同事件可能闪避。先等到真实一次胜利，再核对抵扣及保护。
    for _ in range(8):
        receipt = mention(s, "暗杀 @b", "b")
        if "金牌" in receipt:
            break
        s.now += 86400
    assert "金牌" in receipt
    assert s.record("b")["silver"] == 100
    assert scalar(s, "SELECT ward FROM jh_world WHERE member='b'") == 0


def test_close_revokes_new_relationship_invites(room):
    s = room
    ready(s)
    ready(s, "b")
    mention(s, "结为道侣 @b", "b")
    s.say("关闭江湖", member="owner")
    s.say("开启江湖", member="owner")
    assert "没有可处理" in s.say("接受道侣", member="b")


def test_paging_and_faction_paths(room):
    s = room
    for name in ("leaf", "b"):
        ready(s, name)
    for _ in range(12):
        s.conn.execute(
            "INSERT INTO jh_goods(grp,member,name,price) VALUES('east','leaf','木剑',9)"
        )
    assert "江湖装备 2" in s.say("江湖装备")
    assert "#1 " in s.say("江湖装备 2")
    assert "坊市 2" in s.say("坊市", member="b")
    assert "#12 " in s.say("坊市 2", member="b")
    assert "魔教" in s.say("加入魔教")
    assert s.record()["karma"] <= -20
    assert "正道" in s.say("投身正道", member="b")
    assert s.record("b")["karma"] >= 20


def test_native_social_target_and_forged_name():
    from tests.test_jianghu_mentions import JianghuMentions

    case = JianghuMentions()
    try:
        case.setUp()
        for name in ("player-a", "player-b"):
            case.conn.execute(
                """INSERT INTO jh_players(grp,member,identity,strength,agility,constitution,insight,luck,title,
                route,level,first_win_at,completed_at) VALUES(?,?,'平民',20,20,20,20,5,'练家子','拳',3,1,2)""",
                (case.api.room, name),
            )
        assert "请从微信" in case.say("二狗结拜 @群友")["body"]
        from unittest.mock import patch

        original = case.api.get

        def member_record(path):
            if path.endswith("/members/player-b"):
                return {
                    "groupId": case.api.room,
                    "username": "player-b",
                    "state": "present",
                    "member": {"username": "player-b", "roomDisplayName": "小乙"},
                }
            return original(path)

        from ergou.agent_wechat import reply_mentions

        with patch.object(case.api, "get", side_effect=member_record):
            invite = case.say("二狗结拜 @小乙", ["player-b"])
        assert "五分钟内" in invite["body"]
        assert reply_mentions(invite) == ["player-a", "player-b"]
        assert case.conn.execute("SELECT inviter,invitee FROM jh_relations").fetchone()[
            :
        ] == ("player-a", "player-b")
    finally:
        case.doCleanups()


def test_tournament_opponents_and_insight_limit(room):
    s = room
    for member in ("leaf", "b"):
        ready(s, member)
    s.conn.execute("UPDATE jh_players SET insight=40 WHERE member='b'")
    assert "上限 8 级" in s.say("江湖身世", member="b")
    for level in range(1, 9):
        assert f" {level} 级" in s.say("研习太极剑", member="b")
    assert "上限 8 级" in s.say("研习太极剑", member="b")
    assert "擂主" in s.say("华山论剑")
    receipt = s.say("华山论剑", member="b")
    assert "本次论剑贡献" in receipt and "擂主" not in receipt
    assert s.record()["silver"] == 100
