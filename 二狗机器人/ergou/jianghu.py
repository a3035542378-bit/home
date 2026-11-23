"""微信群本地江湖玩法。所有写入共用 engine.step 的写事务及事件去重。"""

import json
import random
import re
from datetime import datetime
from math import ceil

from . import jianghu_rules as rules
from . import jianghu_world, jianghu_adventure
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
    *jianghu_world.COMMANDS,
}
CHOICE = re.compile(r"选\s*([12])")
STATS_ONLY = re.compile(rf"(?:{rules.FIELD.pattern}\s*){{4}}")
DUEL = re.compile(r"切磋(?:\s*[@＠].+)?", re.S)
ENDINGS = {
    "解围": "引路人出手制敌，你与这段恩怨就此了结。",
    "自胜": "你击退了蒙面人，带着镖信平安回到了客栈。",
    "加入": "老镖头把你的名字写进了名册。从今天起，你也能跟着镖队上路了。",
    "婉拒": "你婉拒了镖头相邀，提着那柄铁剑，自己上路。",
}


def matches(cmd):
    return cmd in COMMANDS or jianghu_world.matches(cmd) or cmd.startswith("加点") or CHOICE.fullmatch(cmd) or DUEL.fullmatch(cmd) or STATS_ONLY.fullmatch(cmd)


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
        db.execute("DELETE FROM jh_relations WHERE grp=? AND accepted=0",(group,))
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
    return datetime.fromtimestamp(p["first_win_at"] + rules.CHAPTER_WAIT_MINUTES * 60, BJ)


def instruction(p, prefix, now):
    if not p["route"]:
        return f"掌柜递给你一封错送的镖信。封口的印记像半只燕子。柜台旁的生客一直盯着你手里的信。\n选 1 拆开查看，学拳；选 2 原封退还，学剑。\n{prefix}选 1\n{prefix}选 2"
    if p["first_win_at"] is None:
        return f"老镖头守在一旁。准备好了，就再试一次。\n{prefix}再战"
    if p["completed_at"] is not None:
        return f"渡口的镖队还等着你。回主线继续闯荡。\n{prefix}主线"
    if p["next_state"] == "fight":
        return f"准备好就迎战，二狗会一次报完这场比试。\n{prefix}历练"
    if p["next_state"] == "resolve":
        return f"把镖信交给引路人，请他帮你解围。\n{prefix}了结追索"
    if p["next_state"] == "offer":
        return f"镖头在等你的答复。\n{prefix}主线"
    if p["level"] < 3:
        if p["potential"] < price(p):
            return meditation_tip(p, prefix, now)
        return f"潜能已经攒够了，可以继续练{p['route']}了。\n{prefix}练{p['route']}"
    opens = chapter_opens_at(p)
    if now >= opens.timestamp():
        return f"客栈里有了镖信的新消息，回去看看吧。\n{prefix}主线"
    ready = datetime.fromtimestamp(ceil(opens.timestamp()), BJ)
    return f"镖信还在路上。北京时间 {ready:%Y-%m-%d %H:%M:%S} 起，回客栈看看：\n{prefix}主线"


def create(db, key, cmd, prefix, rng, now):
    draft = db.execute("SELECT * FROM jh_drafts WHERE grp=? AND member=?", key).fetchone()
    if not draft:
        if cmd != "闯江湖":
            return f"🏮 你在本群还没有角色。先到悦来客栈报个名\n{prefix}闯江湖"
        db.execute("INSERT INTO jh_drafts(grp,member) VALUES(?,?)", key)
    if not draft or not draft["identity"]:
        choice = CHOICE.fullmatch(cmd)
        if not choice:
            return f"🏮 第一章 · 客栈风云\n雨打着悦来客栈的灯笼。掌柜正要落闩，一名镖师把信从门缝塞进来，转身就消失在雨里。\n先选你的出身。无论选哪一种，都有 30 两盘缠。\n平民出身\n{prefix}选 1\n镖局学徒\n{prefix}选 2"
        identity = "平民" if choice[1] == "1" else "镖局学徒"
        db.execute("UPDATE jh_drafts SET identity=? WHERE grp=? AND member=?", (identity, *key))
    else:
        identity = draft["identity"]
    suggestion = (
        f"📜 {identity} · 分配 80 点，每项 0～40。\n"
        "臂力越高，出招越重，气血也越多。身法决定谁先出手。\n根骨越高，挨打越轻，打坐攒潜能也越快。\n"
        "悟性达到 20，武学升到三级时能省 5 点潜能。下面这组可以照发，也可以改。\n"
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
        discount = (f"悟性 {stats[3]}，升三级要花 15 点潜能。悟性再高，这次也只省 5 点。"
                    if stats[3] >= 20 else f"悟性 {stats[3]}，升三级要花 20 点潜能。把悟性调到 20，就能省 5 点。")
        return (
            f"📜 加点草稿 · {rules.title(*stats)}\n{summary}\n气血上限 {100 + stats[0] * 10}。"
            f"{discount}\n想调整就再发一次加点。确认后，这组属性就定下来了。\n{prefix}确认加点"
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
            + instruction(player(db, key), prefix, now)
        )
    if cmd == "闯江湖" and draft and draft["stats"]:
        return f"📜 上次加点草稿仍在，可重新加点或确认。\n{prefix}确认加点"
    return suggestion


def price(p):
    return 10 if p["level"] == 1 else (15 if p["insight"] >= 20 else 20)


def meditation_tip(p, prefix, now):
    level = "二" if p["level"] == 1 else "三"
    missing = price(p) - p["potential"]
    goal = f"{p['route']}法升到{level}级还差 {missing} 点潜能。"
    cursor = p["meditate_at"]
    if cursor is None:
        return f"{goal}先打坐攒些潜能，离线也算时间。\n{prefix}打坐"
    rate = 2 + p["constitution"] // 5
    _, available, _ = rules.meditation(cursor, now, p["constitution"])
    if available >= missing:
        return f"这次打坐已攒下 {available} 点潜能。现在领取，就够把{p['route']}法升到{level}级了。\n{prefix}打坐"
    ready = datetime.fromtimestamp(ceil(cursor + ceil(missing / rate) * rules.MEDITATION_SECONDS), BJ)
    today = datetime.fromtimestamp(now, BJ).date()
    day = {0: "今天", 1: "明天"}.get((ready.date() - today).days, f"{ready.month}月{ready.day}日")
    return (f"{goal}你正在打坐，每 {rules.MEDITATION_MINUTES} 分钟能攒 {rate} 点。\n"
            f"{day} {ready:%H:%M:%S}（北京时间）就能攒够，到时发这句领取：\n{prefix}打坐")


def panel_status(p, now):
    if not p["route"]:
        return "📜 当前状态：等你决定拆信还是还信"
    if p["first_win_at"] is None:
        return "⚔️ 当前状态：首战失利，可以再战"

    cursor = p["meditate_at"]
    if cursor is None:
        activity = "🍵 当前状态：未开始打坐"
    else:
        rounds, gain, _ = rules.meditation(cursor, now, p["constitution"])
        activity = "🧘 当前状态：打坐中"
        if rounds:
            activity += f" · 可领 {gain} 潜能"
        else:
            activity += f" · 这一轮还没满 {rules.MEDITATION_MINUTES} 分钟"

    stage = {
        "fight": "可再去渡口找引路人" if p["defeated"] else "待迎战蒙面人",
        "resolve": "待了结追索",
        "offer": "待答复镖头",
        "done": "第一章已完成" if p["completed_at"] is not None else "镖信的事已经办妥，还要把武学练到三级",
    }.get(p["next_state"])
    if not stage and now >= chapter_opens_at(p).timestamp():
        stage = "镖信续章已开放"
    return activity + (f"\n📜 主线：{stage}" if stage else "")


def record(db, event, kind):
    return db.execute(
        """INSERT OR IGNORE INTO jh_events VALUES(?,?,1,?,?,?)""",
        (event["grp"], event["member"], kind, event["event_id"], event["arrived"]),
    ).rowcount


def conclude(db, key, event, prefix):
    now = event["arrived"]
    p = player(db, key)
    if not p["ending"] or p["level"] < 3 or not record(db, event, "chapter_done"):
        return instruction(p, prefix, now)
    update(db, key, completed_at=event["arrived"])
    result = f"🏮 第一章·客栈风云 已完成\n{ENDINGS[p['ending']]}\n【切磋 @群友】邀一位朋友试试身手"
    if p["ending"] == "加入" and record(db, event, "join_broadcast"):
        # 同一条定向群回执承载入门恭贺，继承原事件的微信发送授权。
        result += (
            f"\n🎉 恭喜{labels(db, key[0])(key[1])}正式成为镖局弟子！江湖人称【{p['title']}】。"
        )
    return result + f"\n去渡口听听下一章的消息\n{prefix}主线"


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
    return report + f"\n{outcome}！首胜奖励已到账：20 两银子和 10 点潜能。\n{rules.CHAPTER_WAIT_MINUTES} 分钟后可以发【主线】回客栈听下文。现在可以先提升武学：\n{prefix}练{p['route']}"


def meditate(db, key, p, now, prefix, rng):
    if p["meditate_at"] is None:
        update(db, key, meditate_at=now)
        rate = 2 + p["constitution"] // 5
        ready = datetime.fromtimestamp(ceil(now + rules.MEDITATION_SECONDS), BJ)
        return (f"🧘 已开始打坐，离线也会攒潜能。每 {rules.MEDITATION_MINUTES} 分钟攒 {rate} 点。\n"
                f"北京时间 {ready:%m月%d日 %H:%M:%S} 就能领第一份潜能。到时发：\n{prefix}打坐")
    rounds, gain, cursor = rules.meditation(p["meditate_at"], now, p["constitution"])
    if not rounds:
        ready = datetime.fromtimestamp(ceil(cursor + rules.MEDITATION_SECONDS), BJ)
        return f"🧘 这轮还没满 {rules.MEDITATION_MINUTES} 分钟，进度已保留。\n北京时间 {ready:%Y-%m-%d %H:%M:%S} 起可领。\n{prefix}打坐"
    hunger = max(0, p["hunger"] - rounds * (5 + p["strength"]))
    # 原型候选值：每个结算轮次福缘/100 的机会，单次至多拾得一两。
    luck = p["luck"]
    if p["completed_at"] is not None:
        _,luck = jianghu_adventure.season(*key,now)
        if db.execute("""SELECT 1 FROM jh_relations WHERE grp=? AND accepted=1 AND kind IN ('结拜','道侣')
                      AND (inviter=? OR invitee=?)""",(*key,key[1])).fetchone():
            gain=min(rules.POTENTIAL_CAP,gain+rounds)
    extra = int(any(rng.randrange(100) < luck for _ in range(rounds)))
    update(
        db,
        key,
        meditate_at=cursor,
        hunger=hunger,
        potential=p["potential"] + gain,
        silver=p["silver"] + extra,
    )
    text = f"🧘 出关 · {rounds} 轮，这次打坐获得 {gain} 点潜能。\n现有潜能 {p['potential'] + gain} 点　饱腹值 {p['hunger']} → {hunger}"
    if extra:
        text += "\n🍀 奇遇：蒲团下拾得 1 两"
    if hunger < 20:
        return text + f"\n你饿得使不上劲了。下场出招伤害减半，先去客栈看看包子吧。\n{prefix}客栈"
    return text + "\n" + instruction(player(db, key), prefix, now)


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
        if jianghu_adventure.world(db,key) or jianghu_adventure.world(db,(group,invite[0])):
            from .jianghu_martial import resolve
            result,report=resolve(jianghu_adventure.duelist(db,p,show(member),now),
                                  jianghu_adventure.duelist(db,opponent,show(invite[0]),now),rng)
        else:
            result,report=rules.fight(rules.fighter(p,show(member)),rules.fighter(opponent,show(invite[0])),rng)
        winner = "平手" if result == 0 else f"{show(member if result > 0 else invite[0])}胜"
        return f"⚔️ 无损切磋\n{report}\n{winner}，点到为止。"
    target = json.loads(event["payload"]).get("duel_target")
    if not target or target == member:
        return "请在微信里选中一位群友，再发切磋邀请。"
    other = player(db, (group, target))
    if not other or other["first_win_at"] is None:
        return "这位群友还没打完第一场。等对方过了首战，就能切磋了。"
    busy = db.execute(
        """SELECT 1 FROM jh_invites WHERE grp=? AND
        (inviter IN (?,?) OR invitee IN (?,?))""",
        (group, member, target, member, target),
    ).fetchone()
    if busy:
        return "还有一份切磋邀请待回应。等那场切磋结束，或邀请到期，再约吧。"
    db.execute("INSERT INTO jh_invites VALUES(?,?,?,?)", (group, member, target, now + 300))
    db.execute("""INSERT OR IGNORE INTO jh_invite_mentions(biz,invitee)
                  SELECT biz,? FROM fishing_reply_mentions WHERE biz=?""", (target, event["event_id"]))
    name = labels(db, group)
    return (f"⚔️ {name(target)}收到了{name(member)}的切磋邀请。\n"
            f"请受邀的群友在五分钟内回复。切磋点到为止，双方都不会损失气血或银两。\n{prefix}应战\n{prefix}拒绝")


def handle(db, event, cmd, prefix):
    mention_sender(db, event)
    key = (event["grp"], event["member"])
    now = event["arrived"]
    rng = random.Random(event["event_id"])
    p = player(db, key)
    if STATS_ONLY.fullmatch(cmd):
        cmd = "加点 " + cmd
    if cmd.startswith("赐金条") and jianghu_world.society.TARGET.fullmatch(cmd):
        return jianghu_world.society.grant(db,key,event,cmd)
    if cmd in jianghu_adventure.GUIDES:
        return jianghu_world.handle(db,key,p,event,cmd,prefix,rng)
    if p is None:
        return create(db, key, cmd, prefix, rng, now)
    if jianghu_world.matches(cmd) or (cmd in ("主线","历练") and p["completed_at"] is not None):
        return jianghu_world.handle(db,key,p,event,cmd,prefix,rng)
    if cmd.startswith("加点") or cmd == "确认加点":
        return f"📜 你已经选好出身（{p['identity']}），属性已锁定。想看看自己的本事，可以发：\n{prefix}面板"
    if cmd == "江湖故事":
        opening = ("十六岁那年，你刚进镖局当学徒。" if p["identity"] == "镖局学徒"
                   else "十六岁那年，你还是镇上的一个普通少年。")
        lines = ["📜 你的江湖故事", opening + "那晚，你正帮悦来客栈的掌柜关门，一封信从门缝里滑了进来。信封上写着“老镖头亲启”。"]
        if p["route"] == "拳":
            lines.append("你拆开信，里面只有一句：“渡口相见。”柜台边的假镖师伸手来抢，老镖头在你身后喊：“收肘，出拳！”你照着他的口令，挥出了第一拳。")
        elif p["route"] == "剑":
            lines.append("你把信原封不动地还给了老镖头。他取出半枚燕印，和信封上的印记一对，果然合得上。为了谢你，他送了你一把铁剑，还教了你第一招剑法。")
        if p["ending"]:
            lines.append(ENDINGS[p["ending"]])
        elif p["next_state"] in ("fight", "resolve"):
            lines.append("渡口的蒙面人认出了信封，他是替假镖师来追这封信的。")
        elif p["next_state"] == "offer":
            lines.append("老镖头回客栈谢你，还给你留了个镖局的位置。")
        extended=jianghu_adventure.world(db,key)
        if extended and extended["stage"]:
            lines.append(f"你以{extended['faction']}身份追查失镖。" + ("黑木崖的旧案已了，神兵由你保管。" if extended["stage"]==4 else "渡口的人还记得那枚燕印。"))
        lines.extend(("", "👇 接下来", instruction(p, prefix, now)))
        return "\n".join(lines)
    if cmd in ("面板", "江湖面板", "闯江湖"):
        extended = jianghu_adventure.world(db,key)
        history = "老镖头曾助你脱险。\n" if p["first_defeat"] else ""
        ending = ENDINGS.get(p["ending"], "")
        if ending:
            history += ending + "\n"
        age = 16
        if extended:
            age = jianghu_adventure.age(extended,now)
            history += f"🏮 {extended['faction'] or '未选阵营'} · 金条 {extended['gold']} · {extended['training'] or '江湖客'}\n"
        route = (
            ("基础拳法" if p["route"] == "拳" else "铁剑 · 基础剑法") + f" Lv.{p['level']}"
            if p["route"]
            else "尚未习武"
        )
        stats = "　".join(
            f"{a}{p[k]}"
            for a, k in zip(rules.ATTRIBUTES, ("strength", "agility", "constitution", "insight"))
        )
        return (
            f"👤 {p['identity']} · {age}岁 · {p['title']}\n{panel_status(p, now)}\n"
            f"{stats}　福缘{p['luck']}\n"
            f"{route}　气血上限 {jianghu_adventure.fighter(db,p,'你',now).hp}　善恶 {p['karma']}\n"
            f"饱腹值 {p['hunger']}/100　银两 {p['silver']}　潜能 {p['potential']}\n{history}"
            + instruction(p, prefix, now)
        )
    if not p["route"]:
        choice = CHOICE.fullmatch(cmd)
        if not choice:
            return instruction(p, prefix, now)
        fist = choice[1] == "1"
        update(db, key, route="拳" if fist else "剑", karma=-10 if fist else 10, level=1)
        intro = "你拆开镖信，里面只写着“渡口相见”。柜台边的假镖师劈手来夺。老镖头喝道：“收肘，出拳！”你照着他的招式打出了第一拳。" if fist else "你把信还给老镖头。他拿出半枚燕印，正好和封口的印记合上。他送你一把铁剑，刚教完第一招，门口的野狗就叼走了他的肉包！"
        return intro + "\n" + first_battle(db, key, event, prefix, rng)
    if p["first_win_at"] is None:
        return (
            first_battle(db, key, event, prefix, rng) if cmd == "再战" else instruction(p, prefix, now)
        )
    if cmd == "打坐":
        return meditate(db, key, p, now, prefix, rng)
    if cmd in ("练拳", "练剑"):
        if p["level"] >= 3:
            return f"你的{p['route']}法已练到本章最高的三级。\n" + instruction(p, prefix, now)
        if cmd != "练" + p["route"]:
            return f"你学的是基础{p['route']}法。\n" + instruction(p, prefix, now)
        cost = price(p)
        if p["potential"] < cost:
            return meditation_tip(p, prefix, now)
        update(db, key, level=p["level"] + 1, potential=p["potential"] - cost)
        return f"🥋 你的基础{p['route']}法升到了 Lv.{p['level'] + 1}，用去 {cost} 点潜能。\n" + conclude(
            db, key, event, prefix
        )
    if cmd in ("吃包子", "客栈"):
        cost = min(5, p["silver"])
        gain = min(100 - p["hunger"], cost * 10)
        if not gain:
            return ("你已经吃饱了。" if p["hunger"] == 100 else "你身上没有银两买包子。") + f"这次没扣钱。\n{prefix}面板"
        if cmd == "客栈":
            return f"🥟 吃一份花 {cost} 两。吃完后，饱腹值 {p['hunger']} → {p['hunger'] + gain}。\n{prefix}吃包子"
        update(db, key, silver=p["silver"] - cost, hunger=p["hunger"] + gain)
        return (
            f"🥟 你吃了包子，花了 {cost} 两银子。饱腹值回到 {p['hunger'] + gain}，身上还剩 {p['silver'] - cost} 两。\n"
            + instruction(player(db, key), prefix, now)
        )
    if DUEL.fullmatch(cmd) or cmd in ("拒绝", "应战"):
        return duel(db, key, event, p, cmd, prefix, rng)
    return chapter(db, key, event, p, cmd, prefix, rng)


def chapter(db, key, event, p, cmd, prefix, rng):
    now = event["arrived"]
    state = p["next_state"]
    if cmd == "主线" and state == "unopened":
        if now < chapter_opens_at(p).timestamp():
            ready = datetime.fromtimestamp(ceil(chapter_opens_at(p).timestamp()), BJ)
            return f"客栈里暂时还没有新消息。北京时间 {ready:%Y-%m-%d %H:%M:%S} 起，再来看看吧。\n{prefix}主线"
        state = "fight" if p["route"] == "拳" else "offer"
        update(db, key, next_state=state, stage_at=now)
    if cmd == "主线" and state == "offer":
        return f"收下镖信的镖头赶来道谢。他给你倒了碗茶：“那封信能原封不动地到我手上，多亏了你。下趟镖，愿意跟我一起走吗？”\n选 1 加入镖局，选 2 婉拒邀请。\n{prefix}选 1\n{prefix}选 2"
    if cmd == "历练" and state == "fight":
        if p["defeated"]:
            update(db, key, next_state="resolve", stage_at=now)
            return f"引路人指了指你手里的镖信：“我认得这封信，让我跟他谈。”亮出信物，请他帮你解围。\n{prefix}了结追索"
        result, report = encounter(db, key, p, "蒙面人", rng)
        if result <= 0:
            update(db, key, defeated=1)
            return report + f"\n你没能击退蒙面人。渡口的引路人冲你招了招手，过去问问他。\n{prefix}历练"
        ending = "自胜"
    elif cmd == "了结追索" and state == "resolve":
        ending = "解围"
    elif CHOICE.fullmatch(cmd) and state == "offer":
        ending = "加入" if CHOICE.fullmatch(cmd)[1] == "1" else "婉拒"
    else:
        intro = {
            "fight": "那封镖信招来了蒙面人。他堵在渡口，伸手拦住了你：“那天拆信的是你？我替我兄弟取信来了。”",
            "resolve": "引路人认出了你的信物。",
            "done": ENDINGS.get(p["ending"], ""),
        }.get(state, "")
        if state == "unopened" and cmd == "历练":
            _, report = encounter(db, key, p, "野狗", rng)
            return report + "\n" + instruction(p, prefix, now)
        return "\n".join(filter(None, (intro, instruction(player(db, key), prefix, now))))
    update(db, key, ending=ending, next_state="done", stage_at=now)
    text = ENDINGS[ending]
    if ending == "自胜":
        text = report + "\n" + text
    result = conclude(db, key, event, prefix)
    if p["level"] == 3:
        return report + "\n" + result if ending == "自胜" else result
    return text + "\n" + result
