"""微信群本地江湖玩法。所有写入共用 engine.step 的写事务及事件去重。"""

import json
import random
import re
from datetime import datetime, time, timedelta
from math import ceil

from . import jianghu_rules as rules
from . import roles
from .db import BJ
from .display_names import labels, mention_sender

SWITCHES = ("开启江湖", "关闭江湖")
COMMANDS = {
    "闯江湖",
    "面板",
    "江湖面板",
    "江湖故事",
    "主线",
    "历练",
    "再战",
    "确认加点",
    "打坐",
    "练拳",
    "练剑",
    "客栈",
    "吃包子",
    "应战",
    "拒绝",
    "了结追索",
    *SWITCHES,
}
CHOICE = re.compile(r"选\s*([12])")
STATS_ONLY = re.compile(rf"(?:{rules.FIELD.pattern}\s*){{4}}")
DUEL = re.compile(r"切磋(?:\s*[@＠].+)?", re.S)
ENDINGS = {
    "解围": "引路人出手制敌，你与这段恩怨就此了结。",
    "自胜": "你击退了蒙面人，客栈终于能安心开门。",
    "加入": "你归还了镖信，镖局名册上有了你的名字。",
    "婉拒": "你婉拒了镖头相邀，提着那柄铁剑，自己上路。",
}


def matches(cmd):
    return cmd in COMMANDS or cmd.startswith("加点") or CHOICE.fullmatch(cmd) or DUEL.fullmatch(cmd) or STATS_ONLY.fullmatch(cmd)


def enabled(db, grp):
    return db.execute(
        "SELECT version FROM jh_group_config WHERE grp=? AND enabled=1", (grp,)
    ).fetchone()


def reply_valid(db, task):
    return not db.execute(
        """SELECT 1 FROM jh_replies r JOIN outbox o ON o.id=r.task
        LEFT JOIN jh_group_config c ON c.grp=o.grp
        WHERE r.task=? AND (c.enabled IS NOT 1 OR c.version IS NOT r.version)""",
        (task,),
    ).fetchone()


def switch(db, event, on):
    group = event["grp"]
    roles.require(db, event["account"], group, event["member"], 4)
    changed = db.execute(
        """INSERT INTO jh_group_config VALUES(?,?,1) ON CONFLICT(grp)
        DO UPDATE SET enabled=excluded.enabled,version=version+1 WHERE enabled<>excluded.enabled""",
        (group, on),
    )
    if not on and changed.rowcount:
        db.execute("DELETE FROM jh_invites WHERE grp=?", (group,))
        db.execute(
            """UPDATE outbox SET state='CANCELLED',body='',detail='本群已关闭江湖'
            WHERE grp=? AND state IN ('PENDING','RETRY_WAIT') AND id IN (SELECT task FROM jh_replies)""",
            (group,),
        )
    return "🏮 本群江湖已开启" if on else "🏮 本群江湖已关闭，角色进度已保存"


def player(db, key):
    return db.execute("SELECT * FROM jh_players WHERE grp=? AND member=?", key).fetchone()


def update(db, key, **fields):
    # 字段名仅由本模块的固定关键字参数给出。
    setters = ",".join(f"{name}=?" for name in fields)
    db.execute(
        f"UPDATE jh_players SET {setters} WHERE grp=? AND member=?", (*fields.values(), *key)
    )


def chapter_opens_at(p):
    next_day = datetime.fromtimestamp(p["first_win_at"], BJ).date() + timedelta(days=1)
    return datetime.combine(next_day, time.min, tzinfo=BJ)


def instruction(p, prefix):
    if not p["route"]:
        return f"掌柜递给你一封错送的镖信。封口印着半枚燕子，柜台旁有个生客一直盯着它。\n选 1 拆开查看，学拳；选 2 原封退还，学剑。\n{prefix}选 1\n{prefix}选 2"
    if p["first_win_at"] is None:
        return f"老镖头会助你再战。\n{prefix}再战"
    if p["completed_at"] is not None:
        return f"想邀群友切磋，可以查看江湖玩法。\n{prefix}江湖录帮助"
    if p["next_state"] == "fight":
        return f"准备好就迎战，二狗会一次报完这场比试。\n{prefix}历练"
    if p["next_state"] == "resolve":
        return f"把封信交给引路人，请他替你解围。\n{prefix}了结追索"
    if p["next_state"] == "offer":
        return f"镖头在等你的答复。\n{prefix}主线"
    if p["level"] < 3:
        if p["potential"] < price(p):
            return f"升到 Lv.{p['level'] + 1} 还差 {price(p) - p['potential']} 潜能。" + meditation_tip(p, prefix)
        return f"{prefix}练{p['route']}"
    return f"镖信续章从北京时间 {chapter_opens_at(p):%Y-%m-%d %H:%M:%S} 起开放。\n{prefix}主线"


def create(db, key, cmd, prefix, rng):
    draft = db.execute("SELECT * FROM jh_drafts WHERE grp=? AND member=?", key).fetchone()
    if not draft:
        if cmd != "闯江湖":
            return f"🏮 你在本群还没有角色。先到悦来客栈报个名\n{prefix}闯江湖"
        db.execute("INSERT INTO jh_drafts(grp,member) VALUES(?,?)", key)
    if not draft or not draft["identity"]:
        choice = CHOICE.fullmatch(cmd)
        if not choice:
            return f"🏮 第一章 · 客栈风云\n雨打着悦来客栈的灯笼。掌柜正要落闩，一名镖师把封信塞进门缝，转眼就走了。\n你为何在客栈？两种出身各带 30 两，选一句发：\n平民出身\n{prefix}选 1\n镖局学徒\n{prefix}选 2"
        identity = "平民" if choice[1] == "1" else "镖局学徒"
        db.execute("UPDATE jh_drafts SET identity=? WHERE grp=? AND member=?", (identity, *key))
    else:
        identity = draft["identity"]
    suggestion = (
        f"📜 {identity} · 分配 80 点，每项 0～40。\n"
        "臂力加伤害和气血，身法抢先手；根骨减伤、打坐更快。\n"
        "悟性到 20，升三级省 5 潜能。可以照发，也可以改数字：\n"
        f"{prefix}加点 臂力20 身法10 根骨30 悟性20"
    )
    if cmd.startswith("加点"):
        try:
            stats = rules.allocation(cmd[2:].strip())
        except ValueError as exc:
            return f"{exc}。这次没有保存。\n{suggestion}"
        db.execute(
            "UPDATE jh_drafts SET stats=? WHERE grp=? AND member=?", (json.dumps(stats), *key)
        )
        summary = "　".join(f"{k}{v}" for k, v in zip(rules.ATTRIBUTES, stats))
        discount = (f"悟性 {stats[3]}，升三级花 15 潜能；超过 20 的部分暂无额外减耗。"
                    if stats[3] >= 20 else f"悟性 {stats[3]}，升三级花 20 潜能；调到 20 可省 5 点。")
        return (
            f"📜 加点草稿 · {rules.title(*stats)}\n{summary}\n气血上限 {100 + stats[0] * 10}。"
            f"{discount}\n满意就发下面这句，确认后锁定属性；想改可重发加点。\n{prefix}确认加点"
        )
    if cmd == "确认加点" and draft and draft["stats"]:
        stats = json.loads(draft["stats"])
        db.execute(
            """INSERT INTO jh_players(grp,member,identity,strength,agility,constitution,insight,luck,title)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (*key, draft["identity"], *stats, rng.randint(1, 10), rules.title(*stats)),
        )
        db.execute("DELETE FROM jh_drafts WHERE grp=? AND member=?", key)
        stats_line = "　".join(f"{name}{value}" for name, value in zip(rules.ATTRIBUTES, stats))
        return (
            f"🏮 16 岁 · {draft['identity']} · {rules.title(*stats)}\n{stats_line}\n"
            + instruction(player(db, key), prefix)
        )
    if cmd == "闯江湖" and draft and draft["stats"]:
        return f"📜 上次加点草稿仍在，可重新加点或确认。\n{prefix}确认加点"
    return suggestion


def price(p):
    return 10 if p["level"] == 1 else (15 if p["insight"] >= 20 else 20)


def meditation_tip(p, prefix):
    if p["meditate_at"] is None:
        return f"先开始打坐，离线也会计时。\n{prefix}打坐"
    rate = 2 + p["constitution"] // 5
    hours = ceil((price(p) - p["potential"]) / rate)
    ready = datetime.fromtimestamp(ceil(p["meditate_at"] + hours * 3600), BJ)
    return f"打坐每小时得 {rate} 点，北京时间 {ready:%m-%d %H:%M:%S} 起领够升级。\n{prefix}打坐"


def record(db, event, kind):
    return db.execute(
        """INSERT OR IGNORE INTO jh_events VALUES(?,?,1,?,?,?)""",
        (event["grp"], event["member"], kind, event["event_id"], event["arrived"]),
    ).rowcount


def conclude(db, key, event, prefix):
    p = player(db, key)
    if not p["ending"] or p["level"] < 3 or not record(db, event, "chapter_done"):
        return instruction(p, prefix)
    update(db, key, completed_at=event["arrived"])
    result = f"🏮 第一章·客栈风云 已完成\n{ENDINGS[p['ending']]}\n【切磋 @群友】邀一位朋友试试身手"
    if p["ending"] == "加入" and record(db, event, "join_broadcast"):
        # 同一条定向群回执承载入门恭贺，继承原事件的微信发送授权。
        result += (
            f"\n🎉 恭喜{labels(db, key[0])(key[1])}正式成为镖局弟子！江湖人称【{p['title']}】。"
        )
    return result


def encounter(db, key, p, enemy, rng):
    result, report = rules.fight(
        rules.fighter(p, "你"),
        rules.ENEMIES[enemy],
        rng,
        assisted=bool(p["first_defeat"] and p["first_win_at"] is None),
    )
    update(db, key, hunger=max(0, p["hunger"] - 10 - p["strength"]))
    return result, f"⚔️ 迎战{enemy}\n{report}"


def first_battle(db, key, event, prefix, rng):
    p = player(db, key)
    result, report = encounter(db, key, p, "假镖师" if p["route"] == "拳" else "野狗", rng)
    if result <= 0 and not p["first_defeat"]:
        update(db, key, first_defeat=1)
        return report + f"\n老镖头救下了你，歇口气再上。\n{prefix}再战"
    if record(db, event, "first_win"):
        update(
            db,
            key,
            first_win_at=event["arrived"],
            silver=p["silver"] + 20,
            potential=p["potential"] + 10,
        )
    outcome = "老镖头出手解围" if result <= 0 else "你赢了"
    return report + f"\n{outcome}！到账 20 两、10 潜能。镖信明日零点有后续。\n现在可以升一级武学\n{prefix}练{p['route']}"


def meditate(db, key, p, now, prefix, rng):
    if p["meditate_at"] is None:
        update(db, key, meditate_at=now)
        rate = 2 + p["constitution"] // 5
        ready = datetime.fromtimestamp(ceil(now + 3600), BJ)
        return (f"🧘 已开始打坐，离线也会攒潜能。每小时 {rate} 点。\n"
                f"首次领取（北京时间）{ready:%m-%d %H:%M:%S}，到点再发：\n{prefix}打坐")
    hours, gain, cursor = rules.meditation(p["meditate_at"], now, p["constitution"])
    if not hours:
        ready = datetime.fromtimestamp(ceil(cursor + 3600), BJ)
        return f"🧘 尚未满一小时，进度已保留。\n北京时间 {ready:%Y-%m-%d %H:%M:%S} 起可领。\n{prefix}打坐"
    hunger = max(0, p["hunger"] - hours * (5 + p["strength"]))
    # 原型候选值：每有效小时福缘/100 的机会，单次至多拾得一两。
    extra = int(any(rng.randrange(100) < p["luck"] for _ in range(hours)))
    update(
        db,
        key,
        meditate_at=cursor,
        hunger=hunger,
        potential=p["potential"] + gain,
        silver=p["silver"] + extra,
    )
    text = f"🧘 出关 · {hours} 小时，常规潜能 +{gain}\n潜能 {p['potential'] + gain}　饥饿 {p['hunger']} → {hunger}"
    if extra:
        text += "\n🍀 奇遇：蒲团下拾得 1 两"
    if hunger < 20:
        return text + f"\n下场伤害减半，去客栈看看。\n{prefix}客栈"
    return text + "\n" + instruction(player(db, key), prefix)


def duel(db, key, event, p, cmd, prefix, rng):
    group, member = key
    now = event["arrived"]
    db.execute("DELETE FROM jh_invites WHERE grp=? AND expires<=?", (group, now))
    if cmd in ("拒绝", "应战"):
        invite = db.execute(
            "SELECT inviter FROM jh_invites WHERE grp=? AND invitee=?", key
        ).fetchone()
        if not invite:
            return "当前没有待回应的切磋。"
        db.execute("DELETE FROM jh_invites WHERE grp=? AND invitee=?", key)
        if cmd == "拒绝":
            return "已婉拒这场切磋。"
        opponent = player(db, (group, invite[0]))
        show = labels(db, group)
        result, report = rules.fight(
            rules.fighter(p, show(member)), rules.fighter(opponent, show(invite[0])), rng
        )
        winner = "平手" if result == 0 else f"{show(member if result > 0 else invite[0])}胜"
        return f"⚔️ 无损切磋\n{report}\n{winner}，点到为止。"
    target = json.loads(event["payload"]).get("duel_target")
    if not target or target == member:
        return "请在微信里选中一位群友，再发切磋邀请。"
    other = player(db, (group, target))
    if not other or other["first_win_at"] is None:
        return "这位群友还没完成首战。"
    busy = db.execute(
        """SELECT 1 FROM jh_invites WHERE grp=? AND
        (inviter IN (?,?) OR invitee IN (?,?))""",
        (group, member, target, member, target),
    ).fetchone()
    if busy:
        return "已有一场切磋待回应，五分钟后邀请到期。"
    db.execute("INSERT INTO jh_invites VALUES(?,?,?,?)", (group, member, target, now + 300))
    db.execute("""INSERT OR IGNORE INTO jh_invite_mentions(biz,invitee)
                  SELECT biz,? FROM fishing_reply_mentions WHERE biz=?""", (target, event["event_id"]))
    name = labels(db, group)
    return (f"⚔️ {name(target)}收到了{name(member)}的切磋邀请。\n"
            f"受邀者五分钟内任选一句，切磋不扣气血或银两。\n{prefix}应战\n{prefix}拒绝")


def handle(db, event, cmd, prefix):
    mention_sender(db, event)
    key = (event["grp"], event["member"])
    now = event["arrived"]
    rng = random.Random(event["event_id"])
    p = player(db, key)
    if STATS_ONLY.fullmatch(cmd):
        cmd = "加点 " + cmd
    if p is None:
        return create(db, key, cmd, prefix, rng)
    if cmd.startswith("加点") or cmd == "确认加点":
        return f"📜 你的{p['identity']}已建好，属性已锁定。查看当前角色：\n{prefix}面板"
    if cmd == "江湖故事":
        lines = ["📜 你的江湖故事", f"十六岁那年，你以{p['identity']}的身份来到悦来客栈。雨夜，有人送错了一封镖信。"]
        if p["route"] == "拳":
            lines.append("你拆了信，看见渡口之约。假镖师来抢，老镖头教了你第一招拳。")
        elif p["route"] == "剑":
            lines.append("你将镖信完璧奉还。老镖头的半枚燕印对上了封口，他留下铁剑，教你用剑。")
        if p["ending"]:
            lines.append(ENDINGS[p["ending"]])
        elif p["next_state"] in ("fight", "resolve"):
            lines.append("渡口的蒙面人认出了信封，他是替假镖师来追这封信的。")
        elif p["next_state"] == "offer":
            lines.append("老镖头回客栈谢你，还给你留了个镖局的位置。")
        lines.append(instruction(p, prefix))
        return "\n".join(lines)
    if cmd in ("面板", "江湖面板", "闯江湖"):
        history = "老镖头曾助你脱险。\n" if p["first_defeat"] else ""
        ending = ENDINGS.get(p["ending"], "")
        if ending:
            history += ending + "\n"
        route = (
            ("基础拳法" if p["route"] == "拳" else "铁剑 · 基础剑法") + f" Lv.{p['level']}"
            if p["route"]
            else "待选镖信路线"
        )
        stats = "　".join(
            f"{a}{p[k]}"
            for a, k in zip(rules.ATTRIBUTES, ("strength", "agility", "constitution", "insight"))
        )
        return (
            f"👤 {p['identity']} · 16岁 · {p['title']}\n{stats}　福缘{p['luck']}\n"
            f"{route}　气血上限 {100 + 10 * p['strength']}　善恶 {p['karma']}\n"
            f"饥饿 {p['hunger']}　银两 {p['silver']}　潜能 {p['potential']}\n{history}"
            + instruction(p, prefix)
        )
    if not p["route"]:
        choice = CHOICE.fullmatch(cmd)
        if not choice:
            return instruction(p, prefix)
        fist = choice[1] == "1"
        update(db, key, route="拳" if fist else "剑", karma=-10 if fist else 10, level=1)
        intro = "你拆开镖信，里面只写着“明早，渡口见”。柜台边的假镖师探手夺信！老镖头喊你收肘出拳，你学会了基础拳法。" if fist else "你送还镖信。老镖头亮出另半枚燕印，正好合上。他赠你铁剑，才教完基础剑法，门口的野狗就叼走了他的肉包！"
        return intro + "\n" + first_battle(db, key, event, prefix, rng)
    if p["first_win_at"] is None:
        return (
            first_battle(db, key, event, prefix, rng) if cmd == "再战" else instruction(p, prefix)
        )
    if cmd == "打坐":
        return meditate(db, key, p, now, prefix, rng)
    if cmd in ("练拳", "练剑"):
        if cmd != "练" + p["route"] or p["level"] >= 3:
            return f"当前武学 Lv.{p['level']}。\n" + instruction(p, prefix)
        cost = price(p)
        if p["potential"] < cost:
            return f"还差 {cost - p['potential']} 潜能。" + meditation_tip(p, prefix)
        update(db, key, level=p["level"] + 1, potential=p["potential"] - cost)
        return f"🥋 基础{p['route']}法 Lv.{p['level'] + 1}，已用 {cost} 潜能。\n" + conclude(
            db, key, event, prefix
        )
    if cmd in ("吃包子", "客栈"):
        cost = min(5, p["silver"])
        gain = min(100 - p["hunger"], cost * 10)
        if not gain:
            return f"饥饿 {p['hunger']}，余额 {p['silver']} 两，本次未扣费。\n{prefix}面板"
        if cmd == "客栈":
            return f"🥟 吃一份花 {cost} 两，饥饿 {p['hunger']} → {p['hunger'] + gain}。\n{prefix}吃包子"
        update(db, key, silver=p["silver"] - cost, hunger=p["hunger"] + gain)
        return (
            f"🥟 已吃包子，花 {cost} 两。饥饿 {p['hunger'] + gain}，余额 {p['silver'] - cost} 两。\n"
            + instruction(player(db, key), prefix)
        )
    if DUEL.fullmatch(cmd) or cmd in ("拒绝", "应战"):
        return duel(db, key, event, p, cmd, prefix, rng)
    return chapter(db, key, event, p, cmd, prefix, rng)


def chapter(db, key, event, p, cmd, prefix, rng):
    now = event["arrived"]
    state = p["next_state"]
    if cmd == "主线" and state == "unopened":
        if now < chapter_opens_at(p).timestamp():
            return f"镖信有了下落，北京时间明日零点后再来。\n{prefix}主线"
        state = "fight" if p["route"] == "拳" else "offer"
        update(db, key, next_state=state, stage_at=now)
    if cmd == "主线" and state == "offer":
        return f"收下镖信的镖头赶来道谢。他把两枚燕印拼在桌上：“送信最难的是守信。愿意跟我走一趟镖吗？”\n选 1 加入镖局，选 2 婉拒邀请。\n{prefix}选 1\n{prefix}选 2"
    if cmd == "历练" and state == "fight":
        if p["defeated"]:
            update(db, key, next_state="resolve", stage_at=now)
            return f"蒙面人拦住去路。亮出信物，请引路人了结追索。\n{prefix}了结追索"
        result, report = encounter(db, key, p, "蒙面人", rng)
        if result <= 0:
            update(db, key, defeated=1)
            return report + f"\n你没能击退蒙面人。再来客栈，找引路人解围。\n{prefix}历练"
        ending = "自胜"
    elif cmd == "了结追索" and state == "resolve":
        ending = "解围"
    elif CHOICE.fullmatch(cmd) and state == "offer":
        ending = "加入" if CHOICE.fullmatch(cmd)[1] == "1" else "婉拒"
    else:
        intro = {
            "fight": "那封镖信招来了蒙面人。他堵在渡口，手里攥着半枚燕印：“昨日拆信的是你？我替我兄弟取信来了。”",
            "resolve": "引路人认出了你的信物。",
            "done": ENDINGS.get(p["ending"], ""),
        }.get(state, "")
        if state == "unopened" and cmd == "历练":
            _, report = encounter(db, key, p, "野狗", rng)
            return report + "\n" + instruction(p, prefix)
        return intro + "\n" + instruction(player(db, key), prefix)
    update(db, key, ending=ending, next_state="done", stage_at=now)
    text = ENDINGS[ending]
    if ending == "自胜":
        text = report + "\n" + text
    result = conclude(db, key, event, prefix)
    if p["level"] == 3:
        return report + "\n" + result if ending == "自胜" else result
    return text + "\n" + result
