"""群内社交、双方自愿的江湖恩怨与悬赏托管。"""

import json
import re
from datetime import datetime

from . import roles
from .db import BJ
from .display_names import labels
from .jianghu_adventure import change, duelist, fighter, funds, world
from .jianghu_martial import resolve

RELATIONS = {"拜师": "师徒", "结拜": "结拜", "结为道侣": "道侣"}
TARGET = re.compile(
    r"(拜师|结拜|结为道侣|师门援手|暗杀|悬赏|赐金条)\s*[@＠](.+?)(?:\s+([1-9][0-9]{0,5})(?:两|根)?)?\s*"
)
ANSWER = re.compile(r"(接受|谢绝|解除)(师徒|结拜|道侣)")
EXACT = {"加入恩怨", "退出恩怨", "悬赏榜", "撤回悬赏", "我的羁绊", "江湖保护"}


def ties(db, grp, member, kind):
    return db.execute(
        """SELECT * FROM jh_relations WHERE grp=? AND kind=? AND (inviter=? OR invitee=?)""",
        (grp, kind, member, member),
    ).fetchone()


def mentor_reward(db, key):
    # 拜师的发起人是徒弟，受邀人是师傅。
    db.execute(
        """UPDATE jh_players SET potential=potential+1 WHERE grp=? AND member IN
               (SELECT invitee FROM jh_relations WHERE grp=? AND kind='师徒' AND inviter=? AND accepted=1)""",
        (key[0], *key),
    )


def refund(db, event, contracts):
    for c in contracts:
        funds(db, (c["grp"], c["member"]), event, "退回悬赏", silver=c["amount"])
        db.execute("DELETE FROM jh_contracts WHERE id=?", (c["id"],))


def grant(db, key, event, cmd):
    grp, member = key
    roles.require(db, event["account"], grp, member, 4)
    target = json.loads(event["payload"]).get("duel_target")
    amount = TARGET.fullmatch(cmd)[3]
    if not target or not amount:
        return "请在微信选中群友，再填写正整数金条数量。"
    db.execute(
        """INSERT OR IGNORE INTO jh_world(grp,member,born)
               SELECT grp,member,first_win_at FROM jh_players WHERE grp=? AND member=? AND completed_at IS NOT NULL""",
        (grp, target),
    )
    if not world(db, (grp, target)):
        return "对方还没完成第一章。"
    funds(db, (grp, target), event, "群主赐金", gold=int(amount))
    return f"🪙 已向{labels(db, grp)(target)}发放 {amount} 根江湖金条。"


def handle(db, key, p, w, event, cmd, prefix, rng):
    grp, member = key
    now = event["arrived"]
    show = labels(db, grp)
    db.execute(
        "DELETE FROM jh_relations WHERE grp=? AND accepted=0 AND expires<=?", (grp, now)
    )
    if cmd == "我的羁绊":
        msgs = ["🤝 你的江湖羁绊"]
        for kind in RELATIONS.values():
            r = ties(db, grp, member, kind)
            if r:
                other = r["inviter"] if r["invitee"] == member else r["invitee"]
                msgs.append(
                    f"{kind} · {show(other)} · "
                    + ("已结缘" if r["accepted"] else "等待答复")
                )
                if not r["accepted"] and r["invitee"] == member:
                    msgs.extend([prefix + "接受" + kind, prefix + "谢绝" + kind])
        if len(msgs) == 1:
            msgs.extend(["还没有羁绊。", prefix + "江湖结缘"])
        return "\n".join(msgs)
    answer = ANSWER.fullmatch(cmd)
    if answer:
        action, kind = answer.groups()
        r = ties(db, grp, member, kind)
        if not r or (action != "解除" and (r["invitee"] != member or r["accepted"])):
            return "没有可处理的这份邀请。"
        if action == "接受":
            db.execute(
                "UPDATE jh_relations SET accepted=1 WHERE grp=? AND kind=? AND invitee=?",
                (grp, kind, member),
            )
            return f"🤝 你与{show(r['inviter'])}结下{kind}之缘。"
        db.execute(
            "DELETE FROM jh_relations WHERE grp=? AND kind=? AND invitee=?",
            (grp, kind, r["invitee"]),
        )
        return f"已{action}这份{kind}关系。"
    if cmd in ("加入恩怨", "退出恩怨", "江湖保护"):
        if cmd == "退出恩怨":
            change(db, key, pvp=0)
            cs = db.execute(
                "SELECT * FROM jh_contracts WHERE grp=? AND (member=? OR target=?)",
                (*key, member),
            ).fetchall()
            refund(db, event, cs)
            return "🕊 已退出恩怨，相关悬赏均已原路退回。"
        if cmd == "加入恩怨":
            change(db, key, pvp=1)
        expiry = max(p["first_win_at"] + 7 * 86400, w["protected"])
        until = datetime.fromtimestamp(expiry, BJ)
        return (
            (
                "⚔️ 已加入江湖恩怨。"
                if cmd == "加入恩怨" or w["pvp"]
                else "🕊 你尚未加入江湖恩怨。"
            )
            + (
                f"保护至北京时间 {until:%m-%d %H:%M}。"
                if now < expiry
                else "当前已过保护期。"
            )
            + f"落败会失去一成银两，遇袭后保护24小时。\n{prefix}江湖恩怨"
        )
    if cmd == "撤回悬赏":
        cs = db.execute(
            "SELECT * FROM jh_contracts WHERE grp=? AND member=?", key
        ).fetchall()
        refund(db, event, cs)
        return f"退回托管银两 {sum(c['amount'] for c in cs)} 两。"
    if cmd == "悬赏榜":
        rows = db.execute(
            "SELECT * FROM jh_contracts WHERE grp=? ORDER BY amount DESC,id LIMIT 10",
            (grp,),
        ).fetchall()
        return (
            "📜 本群悬赏榜\n"
            + (
                "\n".join(f"{show(r['target'])}　{r['amount']} 两" for r in rows)
                or "暂无悬赏。"
            )
            + f"\n收回自己的托管款\n{prefix}撤回悬赏"
        )
    match = TARGET.fullmatch(cmd)
    if not match:
        return
    action, _, amount = match.groups()
    target = json.loads(event["payload"]).get("duel_target")
    if not target or member == target:
        return "请从微信成员列表选中另一位本群江湖玩家。"
    other_key = (grp, target)
    db.execute(
        """INSERT OR IGNORE INTO jh_world(grp,member,born)
               SELECT grp,member,first_win_at FROM jh_players WHERE grp=? AND member=? AND completed_at IS NOT NULL""",
        other_key,
    )
    other = world(db, other_key)
    if not other:
        return "对方还没有进入本群江湖天下。"
    if action in RELATIONS:
        kind = RELATIONS[action]
        if ties(db, grp, member, kind) or ties(db, grp, target, kind):
            return f"双方各自只能保留一份{kind}关系或邀请。"
        db.execute(
            "INSERT INTO jh_relations VALUES(?,?,?,?,0,?)",
            (grp, kind, member, target, now + 300),
        )
        db.execute(
            """INSERT OR IGNORE INTO jh_invite_mentions(biz,invitee)
                   SELECT biz,? FROM fishing_reply_mentions WHERE biz=?""",
            (target, event["event_id"]),
        )
        return f"🤝 {show(target)}，{show(member)}想与你结下{kind}之缘。五分钟内可以答复。\n{prefix}接受{kind}\n{prefix}谢绝{kind}"
    if not w["pvp"] or not other["pvp"]:
        return f"双方都要自愿加入恩怨。\n{prefix}江湖保护"
    opponent = db.execute(
        "SELECT * FROM jh_players WHERE grp=? AND member=?", other_key
    ).fetchone()
    if now < max(
        p["first_win_at"] + 7 * 86400,
        opponent["first_win_at"] + 7 * 86400,
        other["protected"],
        w["protected"],
    ):
        return "双方中有人仍受保护，这次没有发生交手或扣款。"
    left, right = (
        fighter(db, p, show(member), now),
        fighter(db, opponent, show(target), now),
    )
    if (
        abs(
            (left.hp + left.attack + left.defense)
            - (right.hp + right.attack + right.defense)
        )
        > 2000
    ):
        return "双方战力相差超过2000，不能交手。"
    if action == "悬赏":
        if not amount or int(amount) > p["silver"]:
            return f"请在真实 @群友 后填写可托管的银两，当前有 {p['silver']} 两。"
        if db.execute(
            "SELECT 1 FROM jh_contracts WHERE grp=? AND member=?", key
        ).fetchone():
            return f"已有悬赏托管，先撤回旧单。\n{prefix}撤回悬赏"
        funds(db, key, event, "托管悬赏", silver=-int(amount))
        db.execute(
            "INSERT INTO jh_contracts(grp,member,target,amount,created) VALUES(?,?,?,?,?)",
            (*key, target, int(amount), now),
        )
        return (
            f"📜 已托管 {amount} 两悬赏{show(target)}，撤单全额退回。\n{prefix}撤回悬赏"
        )
    if (
        action == "师门援手"
        and not db.execute(
            """SELECT 1 FROM jh_relations r JOIN jh_strikes s ON s.grp=r.grp AND s.victim=r.inviter
                   WHERE r.grp=? AND r.invitee=? AND r.kind='师徒' AND r.accepted=1 AND s.won=1 AND s.attacker=? AND s.at>?""",
            (*key, target, now - 86400),
        ).fetchone()
    ):
        return "过去一天，对方没有击败过你的徒弟。"
    last = db.execute(
        "SELECT at FROM jh_strikes WHERE grp=? AND attacker=? AND victim=?",
        (*key, target),
    ).fetchone()
    if last and now - last[0] < 86400:
        return "今天你已经挑战过这位对手。"
    win, report = resolve(
        duelist(db, p, show(member), now), duelist(db, opponent, show(target), now), rng
    )
    db.execute(
        """INSERT INTO jh_strikes VALUES(?,?,?,?,?) ON CONFLICT(grp,attacker,victim)
               DO UPDATE SET at=excluded.at,won=excluded.won""",
        (*key, target, now, int(win > 0)),
    )
    if win <= 0:
        return report + "\n对方脱身，双方银两没有变化。"
    change(db, other_key, protected=now + 86400)
    amount = opponent["silver"] // 10
    if other["ward"]:
        change(db, other_key, ward=other["ward"] - 1)
        return report + "\n对方使用免死金牌，银两保住了，保护期24小时。"
    funds(db, other_key, event, "遇袭", silver=-amount)
    funds(db, key, event, "江湖胜利", silver=amount)
    cs = db.execute(
        "SELECT * FROM jh_contracts WHERE grp=? AND target=?", other_key
    ).fetchall()
    prize = 0
    for c in cs:
        if c["member"] == member:
            refund(db, event, [c])
        else:
            prize += c["amount"]
            db.execute("DELETE FROM jh_contracts WHERE id=?", (c["id"],))
    if prize:
        funds(db, key, event, "领取悬赏", silver=prize)
    db.execute("UPDATE jh_players SET karma=karma-10 WHERE grp=? AND member=?", key)
    return (
        report + f"\n胜出，获得 {amount} 两，另领悬赏 {prize} 两。对方进入24小时保护。"
    )
