"""只读旁观者。其结果只进入断言和报告，绝不向玩家提供指令。"""

import json
import re
import sqlite3
from contextlib import closing

from ergou import feature_menu, jianghu, jianghu_rules

from .driver import choices
from .transport import GROUP, MEMBER


def snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row

        def actor(table):
            row = conn.execute(
                f"SELECT * FROM {table} WHERE grp=? AND member=?", (GROUP, MEMBER)
            ).fetchone()
            return dict(row) if row else {}

        counts = dict(
            conn.execute(
                """SELECT event_type,count(*) FROM jh_events
                      WHERE grp=? AND member=? AND chapter=1 GROUP BY event_type""",
                (GROUP, MEMBER),
            )
        )
        notices = conn.execute(
            """SELECT count(*) FROM outbox o JOIN inbox i ON i.event_id=o.biz
                       WHERE o.grp=? AND i.member=? AND instr(o.body,'正式成为镖局弟子')>0""",
            (GROUP, MEMBER),
        ).fetchone()[0]
        return {
            "draft": actor("jh_drafts"),
            "player": actor("jh_players"),
            "events": counts,
            "notices": notices,
            "model": conn.execute("SELECT count(*) FROM chat_requests").fetchone()[0],
        }


def tagged(path, seq):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return (
            conn.execute(
                """SELECT count(*) FROM jh_replies r JOIN outbox o ON r.task=o.id
                   JOIN inbox i ON i.event_id=o.biz WHERE i.seq=? AND i.grp=? AND i.member=? AND o.grp=i.grp""",
                (seq, GROUP, MEMBER),
            ).fetchone()[0]
            == 1
        )


def leak_pattern(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")
        ]
        words = {"max_hp", "group_id", "player_id", "event_type", *tables}
        for table in tables:
            if table.startswith("jh_"):
                words.update(
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM pragma_table_info(?)", (table,)
                    )
                )
    return re.compile(
        r"(?<![A-Za-z0-9_])(?:"
        + "|".join(map(re.escape, sorted(words)))
        + r"|BEGIN\s+IMMEDIATE)(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )


def addressable(cmd):
    if (
        cmd in jianghu.COMMANDS
        or feature_menu.find_topic(cmd)
        or jianghu.CHOICE.fullmatch(cmd)
    ):
        return True
    if jianghu.DUEL.fullmatch(cmd):
        return True
    if cmd.startswith("加点"):
        try:
            jianghu_rules.allocation(cmd[2:].strip())
        except ValueError:
            return False
        return True
    return False


def unaddressable(body, prefix="二狗"):
    # 目录简称可核对寻址能力；盲走驱动仍只发送原文中带完整前缀的选项。
    commands = [
        item.read(body).strip().removeprefix(prefix).strip()
        for item in choices(body, prefix)
    ]
    for match in re.finditer(r"(?:^|可发)【([^】]+)】", body, re.MULTILINE):
        commands.append(match[1].removeprefix(prefix))
    return [cmd for cmd in commands if not addressable(cmd)]


def state_label(s):
    p, d = s["player"], s["draft"]
    if not p:
        return f"身份 {d.get('identity') or '待选'}，草稿 {d.get('stats') or '空'}"
    return (
        f"{p['route'] or '待选线'} Lv.{p['level']}，潜能{p['potential']}，饥饿{p['hunger']}，"
        f"{p['silver']}两，{p['ending'] or p['next_state']}"
    )


def check_hop(cmd, before, after, now, body):
    """预期来自规格，查询类指令检查整份玩法快照相等。未知跳必须显式补断言。"""
    p, q = before["player"], after["player"]
    d = after["draft"]
    if cmd == "闯江湖":
        assert d and d["identity"] is None and not q, "未建立待选身份草稿"
    elif not p and cmd.startswith("选"):
        assert (
            d["identity"] == ("平民" if cmd.endswith("1") else "镖局学徒") and not q
        ), "身份未落盘"
    elif cmd.startswith("加点"):
        stats = jianghu_rules.allocation(cmd[2:].strip())
        assert (
            json.loads(d["stats"]) == stats
            and d["identity"] == before["draft"]["identity"]
            and not q
        ), "草稿不符"
    elif cmd == "确认加点":
        assert (
            not d and q["identity"] == before["draft"]["identity"] and q["silver"] == 30
        ), "建角失败"
        assert [
            q[k] for k in ("strength", "agility", "constitution", "insight")
        ] == json.loads(before["draft"]["stats"])
    elif (not p["route"] and cmd.startswith("选")) or cmd == "再战":
        route = p["route"] or ("拳" if cmd.endswith("1") else "剑")
        assert q["route"] == route and q["karma"] == (-10 if route == "拳" else 10)
        assert ("假镖师" if route == "拳" else "野狗") in body, "缺首战战报"
        if "到账" in body:
            assert (
                q["first_win_at"] == now and q["potential"] == 10 and q["silver"] == 50
            )
            assert after["events"].get("first_win") == 1
        else:
            assert (
                q["first_defeat"] and q["first_win_at"] is None and "救下了你" in body
            )
    elif cmd in ("练拳", "练剑"):
        cost = 10 if p["level"] == 1 else (15 if p["insight"] >= 20 else 20)
        assert (
            cmd == "练" + p["route"]
            and q["level"] == p["level"] + 1
            and q["potential"] == p["potential"] - cost
        )
    elif cmd == "打坐":
        if p["meditate_at"] is None:
            assert (
                q["meditate_at"] == now
                and q["potential"] == p["potential"]
                and "开始打坐" in body
            )
        else:
            rounds = max(0, int((now - p["meditate_at"]) // 120))
            effective = min(12, rounds)
            gain = min(60, effective * (2 + p["constitution"] // 5))
            assert q["meditate_at"] == p["meditate_at"] + 120 * rounds
            assert q["potential"] == p["potential"] + gain
            assert q["hunger"] == max(0, p["hunger"] - effective * (5 + p["strength"]))
    elif cmd == "客栈":
        assert before == after and "吃一份花" in body, "客栈预览应保留原资产"
    elif cmd == "吃包子":
        cost = min(5, p["silver"])
        assert q["silver"] == p["silver"] - cost and q["hunger"] == min(
            100, p["hunger"] + cost * 10
        )
    elif cmd == "面板":
        assert before == after and "气血上限" in body
    elif cmd == "主线":
        opened = now >= p["first_win_at"] + 300
        expected = ("fight" if p["route"] == "拳" else "offer") if opened else "unopened"
        assert q["next_state"] == expected
    elif cmd == "历练" and p["next_state"] == "fight":
        if p["defeated"]:
            assert q["next_state"] == "resolve"
        elif "没能击退" in body:
            assert q["defeated"] and q["next_state"] == "fight"
        else:
            assert q["ending"] == "自胜"
    elif cmd == "了结追索":
        assert p["next_state"] == "resolve" and q["ending"] == "解围"
    elif cmd.startswith("选") and p["next_state"] == "offer":
        assert q["ending"] == ("加入" if cmd.endswith("1") else "婉拒")
    else:
        raise AssertionError("该跳缺少业务态判据")
