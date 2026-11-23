"""按北京时间开放的群内大会。每次行动与奖励均随入站事务落盘。"""

from datetime import datetime, timedelta

from .db import BJ
from .display_names import labels
from .jianghu_adventure import battle, duelist, fighter, funds
from .jianghu_martial import resolve
from .jianghu_rules import Fighter

BOSS_HP = 800
ACTIONS = {"围攻", "首领榜", "阵营战", "华山论剑", "大会领奖", "论剑榜"}
TYPES = {"围攻": "首领", "阵营战": "阵营", "华山论剑": "论剑"}


def period(activity, time):
    day = time.date()
    if activity == "论剑":
        day -= timedelta(days=day.weekday())
    return day.isoformat()


def rankings(db, grp, act, when):
    return db.execute(
        """SELECT member,score,side FROM jh_encounters WHERE grp=? AND activity=? AND period=?
                      ORDER BY score DESC,member LIMIT 10""",
        (grp, act, when),
    ).fetchall()


def handle(db, key, p, w, event, cmd, prefix, rng):
    grp, member = key
    now = event["arrived"]
    time = datetime.fromtimestamp(now, BJ)
    if cmd in ("首领榜", "论剑榜"):
        act = "首领" if cmd == "首领榜" else "论剑"
        show = labels(db, grp)
        rows = rankings(db, grp, act, period(act, time))
        return (
            "🏆 本群"
            + act
            + "榜\n"
            + (
                "\n".join(
                    f"{i}. {show(r['member'])}　{r['score']}"
                    for i, r in enumerate(rows, 1)
                )
                or "本期还没人参战。"
            )
        )
    if cmd == "大会领奖":
        messages = []
        # 奖励只查本人尚未发放的参与记录，可以分次领完离线积存。
        entries = db.execute(
            """SELECT * FROM jh_encounters WHERE grp=? AND member=? AND claimed=0
                           ORDER BY period LIMIT 20""",
            key,
        ).fetchall()
        for entry in entries:
            act, when = entry["activity"], entry["period"]
            end = datetime.strptime(when, "%Y-%m-%d").replace(tzinfo=BJ)
            end += timedelta(days=7) if act == "论剑" else timedelta(hours=22)
            same = (grp, act, when)
            if now < end.timestamp():
                continue
            gold = 0
            if act == "阵营":
                totals = db.execute(
                    """SELECT side,SUM(score) FROM jh_encounters WHERE grp=? AND activity=? AND period=?
                                   GROUP BY side ORDER BY SUM(score) DESC,side""",
                    same,
                ).fetchall()
                if totals and (len(totals) == 1 or totals[0][1] > totals[1][1]):
                    gold = int(entry["side"] == totals[0][0])
            elif act == "论剑":
                gold = 3 if rankings(db, grp, act, when)[0]["member"] == member else 0
            silver = min(30, 1 + entry["score"] // 10)
            funds(db, key, event, act + "参战奖", silver=silver, gold=gold)
            db.execute(
                "UPDATE jh_encounters SET claimed=1 WHERE grp=? AND activity=? AND period=? AND member=?",
                (*same, member),
            )
            messages.append(f"{when} {act}　{silver} 两、{gold} 金条")
        return (
            "🏆 到账\n" + "\n".join(messages)
            if messages
            else "还没有待领取的赛后奖励。首领和阵营在当晚22点结算，论剑在下周一零点结算。"
        )
    act = TYPES[cmd]
    if act == "首领" and not 20 <= time.hour < 22:
        return f"🐲 本群首领每日北京时间20:00～22:00出没。\n{prefix}首领榜"
    if act == "阵营" and (time.weekday() != 5 or not 20 <= time.hour < 22):
        return "🚩 本群阵营战每周六北京时间20:00～22:00开放。"
    if act == "阵营" and w["faction"] not in ("正道", "魔教"):
        return "🚩 正道与魔教分阵出战。散人可参加华山论剑。\n" + prefix + "华山论剑"
    when = period(act, time)
    args = (grp, act, when)
    prev = db.execute(
        "SELECT * FROM jh_encounters WHERE grp=? AND activity=? AND period=? AND member=?",
        (*args, member),
    ).fetchone()
    cooling = prev and now - prev["last_action"] < 120
    report = ""
    if act == "首领":
        used = db.execute(
            "SELECT COALESCE(sum(score),0) FROM jh_encounters WHERE grp=? AND activity=? AND period=?",
            args,
        ).fetchone()[0]
        if used >= BOSS_HP:
            return f"🐲 今晚的首领已被击退。\n{prefix}首领榜"
        if cooling:
            return "本轮已出招，两分钟后再来。"
        ally = db.execute(
            """SELECT 1 FROM jh_relations r JOIN jh_encounters e ON e.grp=r.grp AND e.activity='首领' AND e.period=?
                          AND e.member=CASE WHEN r.inviter=? THEN r.invitee ELSE r.inviter END
                          WHERE r.grp=? AND r.kind IN ('道侣','结拜') AND r.accepted=1 AND (r.inviter=? OR r.invitee=?)""",
            (when, member, grp, member, member),
        ).fetchone()
        bonus = 10 if ally else 0
        points = min(
            BOSS_HP - used,
            max(1, fighter(db, p, "你", now).attack // 2 + bonus + rng.randint(0, 8)),
        )
        if used + points == BOSS_HP:
            funds(db, key, event, "首领尾刀", gold=1)
            report = "你打出了最后一击，获得1根金条！"
        if ally:
            report += "你与同伴合击。"
        report += f"\n首领剩余气血 {BOSS_HP - used - points}/{BOSS_HP}。"
    else:
        if cooling:
            return "本轮已出招，两分钟后再来。"
        npc = Fighter("擂主" if act == "论剑" else "敌营先锋", 160, 45, 12, 22)
        # 只匹配已主动参加同期大会的本群玩家；战果不会改变被匹配者的资产。
        opponent = db.execute(
            """SELECT p.* FROM jh_encounters e JOIN jh_players p ON p.grp=e.grp AND p.member=e.member
                             WHERE e.grp=? AND e.activity=? AND e.period=? AND e.member<>? AND (?='论剑' OR e.side<>?)
                             ORDER BY e.score DESC,e.member LIMIT 1""",
            (*args, member, act, w["faction"]),
        ).fetchone()
        if opponent:
            show = labels(db, grp)
            won, report = resolve(
                duelist(db, p, show(member), now),
                duelist(db, opponent, show(opponent["member"]), now),
                rng,
            )
        else:
            won, report = battle(db, p, "你", npc, rng, now)
        points = 10 if won > 0 else 3 if won == 0 else 1
    db.execute(
        """INSERT INTO jh_encounters(grp,activity,period,member,score,last_action,side) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(grp,activity,period,member) DO UPDATE SET score=score+excluded.score,last_action=excluded.last_action""",
        (*args, member, points, now, w["faction"]),
    )
    return f"⚔️ 本次{act}贡献 {points}。\n{report}\n{prefix}" + (
        "首领榜" if act == "首领" else "论剑榜" if act == "论剑" else "大会领奖"
    )
