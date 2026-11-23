"""江湖后续章节与人物成长。由本地消息事务调用。"""

from dataclasses import replace
from datetime import datetime
import hashlib
import re

from .db import BJ
from . import jianghu_rules as rules

MAX_SKILL = 5
ESCORT_SECONDS = 180
PATROL_SECONDS = 120
FACTIONS = {"投身正道": "正道", "加入魔教": "魔教", "独行江湖": "散人"}
OUTER = ("太极剑", "降龙掌")
INNER = ("九阳功", "北冥秘术", "太白经", "双手互搏")
LEARN = re.compile(r"研习\s*(" + "|".join(OUTER + INNER) + ")")

GUIDES = {
    "江湖天下": (
        "🏮 江湖天下",
        ("主线", "续写自己的江湖故事"),
        ("镖局", "接镖赚银两"),
        ("武馆", "学内外功"),
        ("江湖天气", "看今日天气和福缘"),
        ("江湖装备", "穿戴或洗练"),
        ("江湖市集", "交易和置宅"),
        ("江湖恩怨", "悬赏与江湖保护"),
        ("江湖结缘", "师徒、结拜和道侣"),
        ("江湖大会", "围攻、阵营战和论剑"),
        ("江湖钱庄", "金条和红包"),
    ),
    "镖局": (
        "🐎 镖局",
        ("运镖", "接一趟三分钟的镖"),
        ("交镖", "到时结算银两"),
        ("除恶", "挑战拦路人，获胜可拾装备"),
    ),
    "武馆": (
        "🥋 武馆",
        *[
            (f"研习{x}", "修习或提升这门" + ("外功" if x in OUTER else "内功"))
            for x in OUTER + INNER
        ],
        ("江湖身世", "看功力、装束和岁数"),
        ("转生", "查看条件和代价"),
    ),
    "江湖市集": (
        "🏮 集市",
        ("坊市", "看本群在售装备"),
        ("江湖装备", "查看自己的装备和用法"),
        ("家园", "购宅或领取收益"),
        ("胭脂铺", "修整仪容"),
        ("江湖天赋", "查看积分兑换"),
        ("夜市", "看戏听曲"),
    ),
    "江湖结缘": (
        "🤝 江湖结缘",
        ("拜师 @群友", "请对方收你为徒"),
        ("结拜 @群友", "邀请结为兄弟"),
        ("结为道侣 @群友", "邀请结伴"),
        ("我的羁绊", "查看关系和待回应邀请"),
        ("师门援手 @群友", "替近期遇袭的徒弟向对手挑战"),
    ),
    "江湖恩怨": (
        "⚔️ 江湖恩怨",
        ("加入恩怨", "自愿参加，落败会失去一成银两"),
        ("退出恩怨", "退出争斗"),
        ("悬赏榜", "查看悬赏与撤单指令"),
        ("悬赏 @群友 200", "托管200两，限本群已加入者"),
        ("暗杀 @群友", "挑战已加入的对手"),
    ),
    "江湖大会": (
        "🏆 江湖大会",
        ("围攻", "北京时间20点起合力挑战首领"),
        ("首领榜", "查看本日有效伤害"),
        ("阵营战", "周六晚代表阵营出战"),
        ("华山论剑", "参加本周论剑"),
        ("大会领奖", "领取最近一期已结束的奖励"),
    ),
    "江湖钱庄": (
        "🪙 江湖钱庄",
        ("江湖账本", "看银两、金条和最近变动"),
        ("金条商店", "查看江湖特权"),
        ("发江湖红包", "用一根金条发五份游戏银两"),
        ("领江湖红包", "领取本群红包"),
    ),
}


def guide(name, prefix):
    title, *entries = GUIDES[name]
    return (
        title
        + "\n"
        + "\n".join(f"【{cmd}】{desc}" for cmd, desc in entries)
        + f"\n{prefix}{entries[0][0]}"
    )


def world(db, key):
    return db.execute("SELECT * FROM jh_world WHERE grp=? AND member=?", key).fetchone()


def change(db, key, **fields):
    sql = ",".join(f"{name}=?" for name in fields)
    db.execute(
        f"UPDATE jh_world SET {sql} WHERE grp=? AND member=?", (*fields.values(), *key)
    )


def funds(db, key, event, reason, silver=0, gold=0):
    if silver:
        if not db.execute(
            "UPDATE jh_players SET silver=silver+? WHERE grp=? AND member=? AND silver+?>=0",
            (silver, *key, silver),
        ).rowcount:
            raise ValueError("银两不足，这次没有成交。")
    if gold:
        if not db.execute(
            "UPDATE jh_world SET gold=gold+? WHERE grp=? AND member=? AND gold+?>=0",
            (gold, *key, gold),
        ).rowcount:
            raise ValueError("金条不足，这次没有成交。")
    db.execute(
        "INSERT INTO jh_money_log(grp,member,source,reason,silver,gold,at) VALUES(?,?,?,?,?,?,?)",
        (*key, event["event_id"], reason, silver, gold, event["arrived"]),
    )


def season(grp, member, now):
    day = datetime.fromtimestamp(now, BJ).date().isoformat()

    def roll(tag):
        return int.from_bytes(
            hashlib.sha256(f"{grp}/{day}/{tag}".encode()).digest()[:4], "big"
        )

    return ("晴", "暴雨", "瑞雪")[roll("天气") % 3], 1 + roll(member) % 10


def age(w, now):
    return 16 + max(0, int((now - w["born"]) // (96 * 3600)))


def appearance(p, w):
    score = (
        p["constitution"] + (8 if w["looks"] else 0) - (10 if p["hunger"] < 20 else 0)
    )
    thresholds = ((35, "神采奕奕"), (25, "剑眉朗目"), (15, "眉清目秀"), (5, "朴实清秀"))
    return next(
        (name for threshold, name in thresholds if score >= threshold), "风尘仆仆"
    )


def fighter(db, p, name, now):
    key = (p["grp"], p["member"])
    base = rules.fighter(p, name)
    w = world(db, key)
    if not w:
        return base
    item = db.execute(
        "SELECT power,guard FROM jh_goods WHERE grp=? AND member=? AND equipped=1", key
    ).fetchone()
    years = min(5, age(w, now) - 16)
    attack = base.attack + years * 10 + w["outer_level"] * 6 + (item[0] if item else 0)
    guard = base.defense + (item[1] if item else 0) + w["inner_level"] * 2
    if (
        w["outer_level"]
        and w["inner_level"]
        and abs(w["outer_level"] - w["inner_level"]) <= 10
    ):
        attack += 5
    weather, _ = season(*key, now)
    return replace(
        base,
        agility=max(1, base.agility - 3) if weather == "暴雨" else base.agility,
        hp=base.hp + 100 * years,
        attack=attack,
        defense=guard,
    )


def duelist(db, p, name, now):
    from .jianghu_martial import Duelist

    w = world(db, (p["grp"], p["member"]))
    f = fighter(db, p, name, now)
    if not w:
        return Duelist(f)
    return Duelist(
        f,
        w["outer_art"],
        w["inner_art"],
        w["outer_level"],
        w["inner_level"],
        30 + p["constitution"] * 2,
    )


def battle(db, p, name, opponent, rng, now):
    from .jianghu_martial import Duelist, resolve

    return resolve(duelist(db, p, name, now), Duelist(opponent), rng)


PERSONAL = {
    "江湖身世",
    "江湖天气",
    "运镖",
    "交镖",
    "除恶",
    "取回账册",
    "决战黑木崖",
    "转生",
    "确认转生",
    "夜市",
    "胭脂铺",
    "修整仪容",
    "江湖天赋",
    "兑换江湖天赋",
    *FACTIONS,
}


def handle(db, key, p, w, event, cmd, prefix, rng):
    now = event["arrived"]
    weather, luck = season(*key, now)
    if cmd in ("主线", "第二章", "第三章"):
        if w["stage"] == 0:
            return f"📜 第二章 · 渡口失镖\n昨夜那枚燕印又出现了。船夫递来一本浸湿的账册，三路人马都在等你表态。\n正道护镖，魔教追查内鬼，散人替船夫讨个公道。选一条路：\n{prefix}投身正道\n{prefix}加入魔教\n{prefix}独行江湖"
        if w["stage"] == 1:
            return (
                f"📜 渡口的旧账\n账册最后一页被撕走了。运一次镖，顺着水印去找失页。\n{prefix}交镖"
                if w["escort"]
                else f"📜 渡口的旧账\n跟下一趟镖去渡口，找回账册的最后一页。\n{prefix}运镖"
            )
        if w["stage"] == 2:
            return (
                f"📜 镖货里夹着失页。拼好账册，就知道谁劫了那趟镖。\n{prefix}取回账册"
            )
        if w["stage"] == 3:
            return f"⛰ 第三章 · 黑木崖\n账册上的燕印属于当年的老乞丐。上崖与他对质。\n{prefix}决战黑木崖"
        return f"🏮 黑木崖风波已平。你如今是{w['faction']}中人，可赴武馆、论剑或结交同伴。\n{prefix}江湖天下"
    if cmd in FACTIONS:
        if w["stage"] != 0:
            return f"你已选定{w['faction']}。\n{prefix}主线"
        if cmd != "独行江湖":
            karma = (
                max(20, p["karma"] + 10)
                if cmd == "投身正道"
                else min(-20, p["karma"] - 10)
            )
            db.execute(
                "UPDATE jh_players SET karma=? WHERE grp=? AND member=?", (karma, *key)
            )
        change(db, key, stage=1, faction=FACTIONS[cmd])
        return f"🏮 你选择了{FACTIONS[cmd]}。渡口缺一位押镖人，正好借路查案。\n{prefix}运镖"
    if cmd in ("运镖", "交镖"):
        if w["escort"] is None:
            if cmd == "交镖":
                return f"你还没有接镖。\n{prefix}运镖"
            change(db, key, escort=now + ESCORT_SECONDS)
            return f"🐎 已接镖，三分钟后到渡口，交镖可得 20 两。\n{prefix}交镖"
        if now < w["escort"] or cmd == "运镖":
            ready = datetime.fromtimestamp(w["escort"], BJ)
            return (
                f"🐎 镖货{ready:%H:%M:%S}到渡口（北京时间），到时交镖。\n{prefix}交镖"
            )
        funds(db, key, event, "运镖", silver=20)
        change(db, key, escort=None, stage=2 if w["stage"] == 1 else w["stage"])
        return f"🐎 镖货交妥，到账 20 两。\n{prefix}" + (
            "取回账册" if w["stage"] == 1 else "江湖天下"
        )
    if cmd == "取回账册":
        if w["stage"] != 2:
            return f"查看你手上这趟差事。\n{prefix}主线"
        change(db, key, stage=3)
        return f"📜 第二章已完成。失页指向黑木崖，燕印之谜只差最后一问。\n{prefix}决战黑木崖"
    if cmd in ("除恶", "决战黑木崖"):
        finale = cmd == "决战黑木崖"
        if finale and w["stage"] != 3:
            return f"查看目前的主线进度。\n{prefix}主线"
        if (
            not finale
            and w["patrol"] is not None
            and now < w["patrol"] + PATROL_SECONDS
        ):
            return f"巡街还未遇到新的案子，两分钟一趟。\n{prefix}江湖装备"
        enemy = rules.Fighter(
            "守崖人" if finale else "山贼",
            200 if finale else 80,
            40 if finale else 20,
            10,
            12,
        )
        win, report = battle(db, p, "你", enemy, rng, now)
        if not finale:
            change(db, key, patrol=now)
        if win <= 0 and not (finale and w["mercy"]):
            if finale:
                change(db, key, mercy=1)
            return report + (
                f"\n你退下石阶。老船夫愿带着账册来作证，再上崖便能与他当面对质。\n{prefix}决战黑木崖"
                if finale
                else f"\n山贼逃进林中。去武馆学一招再来。\n{prefix}武馆"
            )
        loot = "屠龙刀" if finale else rng.choice(("青锋剑", "柳叶刀", "铁护腕"))
        cur = db.execute(
            "INSERT INTO jh_goods(grp,member,name,power,guard) VALUES(?,?,?,?,?)",
            (*key, loot, 24 if finale else 4, 5 if finale else 2),
        )
        funds(
            db, key, event, "黑木崖" if finale else "除恶", silver=30 if finale else 8
        )
        if finale:
            change(db, key, stage=4)
        else:
            db.execute(
                "UPDATE jh_players SET karma=karma+5 WHERE grp=? AND member=?", key
            )
        return (
            report
            + (
                "\n🏮 第三章已完成。老乞丐交出旧镖与信物。"
                if finale
                else "\n巡街得胜。"
            )
            + f"\n获得{loot} #{cur.lastrowid}，到账 {30 if finale else 8} 两。\n{prefix}装备#{cur.lastrowid}"
        )
    if cmd == "历练":
        if w["patrol"] is not None and now < w["patrol"] + PATROL_SECONDS:
            return f"刚走过这段山路，两分钟后再来。\n{prefix}江湖天下"
        if p["karma"] < -100:
            change(db, key, patrol=now)
            result, report = battle(
                db, p, "你", rules.Fighter("巡城捕快", 180, 60, 18, 30), rng, now
            )
            outcome = (
                "你避开了盘查。"
                if result > 0
                else "捕快认出你的通缉画像，把你赶出了城。"
            )
            return f"城门上贴着你的画像。\n{report}\n{outcome}\n{prefix}江湖天下"
        if rng.randrange(200) == 0:
            change(db, key, patrol=now)
            db.execute(
                "INSERT INTO jh_packets(grp,sender,remaining) VALUES(?,?,5)",
                (
                    key[0],
                    "",
                ),
            )
            return (
                f"🧧 镖队庆功，撒下五份江湖红封。每位群友可领5两。\n{prefix}领江湖红包"
            )
        if rng.randrange(100) < luck + 10:
            change(db, key, patrol=now)
            funds(db, key, event, "历练奇遇", silver=6)
            return f"🍀 你在渡口认出遗落的镖旗，失主答谢了6两。\n{prefix}江湖天下"
        if p["agility"] < 10 and rng.randrange(4) == 0:
            change(db, key, patrol=now)
            return (
                f"🌿 山道青苔湿滑，你脚下趔趄，幸好被挑担的樵夫扶住了。\n{prefix}镖局"
            )
        return handle(db, key, p, w, event, "除恶", prefix, rng)
    if cmd == "江湖天气":
        return f"🌦 今日{weather}，你的福缘为 {luck}。暴雨使历练出手变慢，瑞雪利于修习。"
    if cmd == "江湖身世":
        f = fighter(db, p, "你", now)
        return (
            f"👤 {w['faction'] or '尚未选阵营'} · {age(w, now)}岁 · 转生{w['cycles']}次\n"
            f"攻击 {f.attack}　防御 {f.defense}　气血 {f.hp}\n"
            f"内力上限 {30 + p['constitution'] * 2}　名声 {'大侠' if p['karma'] > 200 else '穷凶极恶' if p['karma'] < -100 else '初入江湖'}\n"
            f"外功 {w['outer_art'] or '未习'} {w['outer_level']}级　内功 {w['inner_art'] or '未习'} {w['inner_level']}级\n"
            f"仪容 {appearance(p, w)} · 今日福缘 {luck} · {w['training'] or '江湖客'}\n{prefix}武馆"
        )
    match = LEARN.fullmatch(cmd)
    if match:
        name = match[1]
        slot = "outer" if name in OUTER else "inner"
        level = w[slot + "_level"] if w[slot + "_art"] == name else 0
        if level >= MAX_SKILL:
            return "这门武学已臻圆满。"
        if w[slot + "_art"] not in ("", name):
            return "这一栏已有武学。转生后可重新择艺。"
        cost = max(1, 8 + 4 * level - int(weather == "瑞雪") - p["insight"] // 20)
        if p["potential"] < cost:
            return f"修习{name}需要 {cost} 潜能，还差 {cost - p['potential']} 点。\n{prefix}打坐"
        db.execute(
            "UPDATE jh_players SET potential=potential-? WHERE grp=? AND member=?",
            (cost, *key),
        )
        change(db, key, **{slot + "_art": name, slot + "_level": level + 1})
        from .jianghu_society import mentor_reward

        mentor_reward(db, key)
        return (
            f"🥋 你把{name}练到 {level + 1} 级，消耗 {cost} 点潜能。\n{prefix}江湖身世"
        )
    if cmd in ("转生", "确认转生"):
        if w["stage"] < 4 or min(w["inner_level"], w["outer_level"]) < MAX_SKILL:
            return f"黑木崖结案、内外功均达五级后可转生。\n{prefix}武馆"
        if cmd == "转生":
            return f"🌙 转生将重开第二章、清空进阶内外功和未交的镖，保留财物及第一章经历；每次可重修武学。转生后可将80点先天属性重配为100点。\n{prefix}确认转生"
        change(
            db,
            key,
            stage=0,
            faction="",
            cycles=w["cycles"] + 1,
            inner_art="",
            outer_art="",
            inner_level=0,
            outer_level=0,
            mercy=0,
            escort=None,
            born=now,
        )
        change(db, key, respec=w["respec"] + 1)
        return f"🌙 你洗髓归来，有100点属性可重新分配。\n{prefix}江湖洗点"
    if cmd == "夜市":
        return f"🎭 戏台正演燕印失镖记。台上的小二把错送的信塞进了自己袖子。\n{prefix}江湖天下"
    if cmd in ("胭脂铺", "修整仪容"):
        if cmd == "胭脂铺":
            return f"🌸 修整仪容需 8 两，可提升仪容评分。\n{prefix}修整仪容"
        if w["looks"]:
            return "你已经整好了衣冠。"
        funds(db, key, event, "修整仪容", silver=-8)
        change(db, key, looks=1)
        return "🌸 已修整仪容，花去 8 两。"
    if cmd in ("江湖天赋", "兑换江湖天赋"):
        if w["training"]:
            return "📜 你已获说书人身份。"
        if cmd == "江湖天赋":
            return f"📜 用本群 5 积分换说书人身份，永久解锁个人称号。\n{prefix}兑换江湖天赋"
        total = db.execute(
            "SELECT COALESCE(sum(points),0) FROM ledger WHERE grp=? AND member=?", key
        ).fetchone()[0]
        if total < 5:
            return f"还差 {5 - total} 积分。\n{prefix}积分"
        db.execute(
            "INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason) VALUES(?,?,0,'江湖身份',-5,'1',?,?,'说书人')",
            (*key, event["event_id"], now),
        )
        change(db, key, training="说书人")
        return "📜 已扣本群 5 积分，获得说书人身份。"
