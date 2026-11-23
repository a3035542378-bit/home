"""江湖装备、玩家交易、宅院和金条特权。"""

import re
from datetime import datetime

from .db import BJ
from .jianghu_adventure import change, funds

GOODS = re.compile(
    r"(装备|卸下|洗练|确认洗练|出售装备|上架|下架|购买装备)\s*[#＃]([1-9][0-9]{0,12})(?:\s+([1-9][0-9]{0,6}))?"
)
EXACT = {
    "江湖装备",
    "坊市",
    "家园",
    "购买宅院",
    "家园收功",
    "江湖账本",
    "金条商店",
    "兑换免死金牌",
    "兑换大还丹",
    "服大还丹",
    "兑换洗点",
    "发江湖红包",
    "确认发江湖红包",
    "领江湖红包",
    "江湖洗点",
}
PAGE = re.compile(r"(坊市|江湖装备)\s+([1-9][0-9]{0,4})")
RESPEC = re.compile(r"重配天赋\s+(.+)")
REFORGE_PRICE = 5000
HOME_PRICE = 80


def statement(db, key, p):
    row = db.execute(
        "SELECT gold FROM jh_world WHERE grp=? AND member=?", key
    ).fetchone()
    rows = db.execute(
        """SELECT reason,silver,gold FROM jh_money_log WHERE grp=? AND member=?
                     ORDER BY id DESC LIMIT 5""",
        key,
    )
    lines = [f"🪙 银两 {p['silver']}　金条 {row[0] if row else 0}"]
    for reason, silver, gold in rows:
        amount = "、".join(
            filter(
                None,
                (f"{silver:+} 两" if silver else "", f"{gold:+} 金条" if gold else ""),
            )
        )
        if amount:
            lines.append(f"{reason}　{amount}")
    if len(lines) == 1:
        lines.append("还没有可展示的流水。")
    return "\n".join(lines)


def handle(db, key, p, w, event, cmd, prefix, rng):
    grp, member = key
    now = event["arrived"]
    match = GOODS.fullmatch(cmd)
    paged = PAGE.fullmatch(cmd)
    page = int(paged[2]) if paged else 1
    if paged:
        cmd = paged[1]
    offset = (page - 1) * 10
    if cmd == "江湖装备":
        rows = db.execute(
            "SELECT * FROM jh_goods WHERE grp=? AND member=? ORDER BY equipped DESC,id DESC LIMIT 11 OFFSET ?",
            (*key, offset),
        ).fetchall()
        if not rows:
            return f"🎒 行囊里还没装备，除恶获胜可以拾得一件。\n{prefix}除恶"
        more = f"\n下一页\n{prefix}江湖装备 {page + 1}" if len(rows) > 10 else ""
        rows = rows[:10]
        rows_text = [
            f"#{r['id']} {r['name']}　攻+{r['power']} 防+{r['guard']} "
            + (
                "已装备"
                if r["equipped"]
                else f"寄售 {r['price']} 两"
                if r["price"]
                else ""
            )
            for r in rows
        ]
        item = rows[0]["id"]
        return (
            f"🎒 我的装备 · 第{page}页\n"
            + "\n".join(rows_text)
            + f"\n【洗练#{item}】先看报价\n【上架#{item} 30】以30两寄售未穿戴装备\n【出售装备#{item}】立即以5两售给铁匠\n"
            + prefix
            + (
                "卸下"
                if rows[0]["equipped"]
                else "下架"
                if rows[0]["price"]
                else "装备"
            )
            + f"#{item}"
            + more
        )
    if cmd == "坊市":
        rows = db.execute(
            "SELECT * FROM jh_goods WHERE grp=? AND price>0 ORDER BY price,id LIMIT 11 OFFSET ?",
            (grp, offset),
        ).fetchall()
        more = f"\n下一页\n{prefix}坊市 {page + 1}" if len(rows) > 10 else ""
        rows = rows[:10]
        items = [
            f"#{r['id']} {r['name']}　{r['price']} 两　攻+{r['power']} 防+{r['guard']}"
            for r in rows
        ]
        sale = next((r for r in rows if r["member"] != member), None)
        return (
            "🏮 本群坊市 · 成交收卖家5%交易税（向上取整）\n"
            + ("\n".join(items) or "暂时无人摆摊。")
            + (
                "\n按标价直接买入\n" + prefix + f"购买装备#{sale['id']} {sale['price']}"
                if sale
                else "\n" + prefix + "江湖装备"
            )
            + more
        )
    if match:
        op, ident, quote = match.groups()
        row = db.execute(
            "SELECT * FROM jh_goods WHERE grp=? AND id=?", (grp, int(ident))
        ).fetchone()
        if op == "购买装备":
            if (
                not row
                or not row["price"]
                or row["member"] == member
                or int(quote or 0) != row["price"]
            ):
                return f"这件装备无法按该报价购入，请重新查看。\n{prefix}坊市"
            price = row["price"]
            funds(db, key, event, "购买装备", silver=-price)
            funds(
                db,
                (grp, row["member"]),
                event,
                "出售装备（扣税）",
                silver=price - (price + 19) // 20,
            )
            db.execute(
                "UPDATE jh_goods SET member=?,price=0 WHERE id=?", (member, ident)
            )
            return f"🎒 花 {price} 两买下{row['name']}。\n{prefix}装备#{ident}"
        if not row or row["member"] != member:
            return f"你的行囊里没有这件装备。\n{prefix}江湖装备"
        if quote and op != "上架":
            return "请检查装备编号和参数。"
        if row["price"] and op != "下架":
            return f"这件装备正在寄售，先收回。\n{prefix}下架#{ident}"
        if op == "下架":
            db.execute("UPDATE jh_goods SET price=0 WHERE id=?", (ident,))
            return "已从摊位收回装备。" if row["price"] else "这件装备没有寄售。"
        if op == "上架":
            if not quote or row["equipped"]:
                return f"未穿戴的装备才能标价上架。\n{prefix}江湖装备"
            db.execute("UPDATE jh_goods SET price=? WHERE id=?", (int(quote), ident))
            return f"🏮 {row['name']}已挂出，标价 {quote} 两。\n{prefix}坊市"
        if op in ("装备", "卸下"):
            if op == "装备":
                db.execute(
                    "UPDATE jh_goods SET equipped=0 WHERE grp=? AND member=? AND equipped=1",
                    key,
                )
            db.execute(
                "UPDATE jh_goods SET equipped=? WHERE id=?", (op == "装备", ident)
            )
            return f"🎒 已{op}{row['name']}。\n{prefix}江湖身世"
        if op == "出售装备":
            if row["equipped"]:
                return f"请先卸下这件装备。\n{prefix}卸下#{ident}"
            db.execute("DELETE FROM jh_goods WHERE id=?", (ident,))
            funds(db, key, event, "铁匠收购", silver=5)
            return "🪙 装备已卖给铁匠，到账 5 两。"
        if op == "洗练":
            return f"🛠 {row['name']} · 攻{row['power']} 防{row['guard']}\n花 {REFORGE_PRICE} 两重抽两项属性，各为1～30，可能变低。\n{prefix}确认洗练#{ident}"
        funds(db, key, event, "装备洗练", silver=-REFORGE_PRICE)
        attack, guard = rng.randint(1, 30), rng.randint(1, 30)
        db.execute(
            "UPDATE jh_goods SET power=?,guard=? WHERE id=?", (attack, guard, ident)
        )
        return f"🛠 洗练花去 {REFORGE_PRICE} 两。攻击 {row['power']} → {attack}，防御 {row['guard']} → {guard}。"
    if cmd in ("家园", "购买宅院", "家园收功"):
        day = datetime.fromtimestamp(now, BJ).date().isoformat()
        if not w["house"]:
            if cmd != "购买宅院":
                return f"🏡 置宅需 {HOME_PRICE} 两，每个北京时间自然日可得 5 潜能。\n{prefix}购买宅院"
            funds(db, key, event, "置宅", silver=-HOME_PRICE)
            change(db, key, house=1)
            return f"🏡 院门钥匙交到你手里了。\n{prefix}家园收功"
        if w["house_day"] and w["house_day"] >= day:
            return "🏡 今天已在家园收过功。"
        if cmd != "家园收功":
            return f"🏡 今日可领 5 潜能。\n{prefix}家园收功"
        change(db, key, house_day=day)
        db.execute(
            "UPDATE jh_players SET potential=potential+5 WHERE grp=? AND member=?", key
        )
        return "🏡 庭院修习，到账 5 潜能。"
    if cmd == "金条商店":
        return (
            "🪙 每项花 1 金条\n【兑换免死金牌】抵一次遇袭损失\n【兑换大还丹】换一颗回满饱腹的丹药\n"
            f"【兑换洗点】换一次重新分配先天属性的机会\n{prefix}江湖账本"
        )
    tokens = {"兑换免死金牌": "ward", "兑换大还丹": "pill", "兑换洗点": "respec"}
    if cmd in tokens:
        funds(db, key, event, cmd, gold=-1)
        field = tokens[cmd]
        change(db, key, **{field: w[field] + 1})
        return (
            "🪙 已扣 1 金条。"
            + {
                "ward": "遇袭时将自动使用免死金牌。",
                "pill": f"需要时服用。\n{prefix}服大还丹",
                "respec": f"查看重配指令。\n{prefix}江湖洗点",
            }[field]
        )
    if cmd == "服大还丹":
        if not w["pill"] or p["hunger"] == 100:
            return "当前无需服药或没有大还丹。"
        change(db, key, pill=w["pill"] - 1)
        db.execute("UPDATE jh_players SET hunger=100 WHERE grp=? AND member=?", key)
        return "🍵 服下大还丹，饱腹值恢复到100。"
    if cmd == "江湖洗点" or RESPEC.fullmatch(cmd):
        if not w["respec"]:
            return f"重配先天属性需要一张洗点券。\n{prefix}金条商店"
        budget, limit = (100, 60) if w["cycles"] else (80, 40)
        if cmd == "江湖洗点":
            return f"📜 发送后消耗1张洗点券，四项合计{budget}，每项最多{limit}。\n{prefix}重配天赋 臂力{budget - 60} 身法20 根骨20 悟性20"
        from . import jianghu_rules as rules

        stats = rules.allocation(RESPEC.fullmatch(cmd)[1], budget=budget, limit=limit)
        change(db, key, respec=w["respec"] - 1)
        db.execute(
            "UPDATE jh_players SET strength=?,agility=?,constitution=?,insight=?,title=? WHERE grp=? AND member=?",
            (*stats, rules.title(*stats), *key),
        )
        return f"📜 天赋已重配，花去1张洗点券。\n{prefix}面板"
    if cmd == "发江湖红包":
        return f"🧧 花 1 金条发五份游戏红包，每位群友限领一份，每份 5 两。\n{prefix}确认发江湖红包"
    if cmd == "确认发江湖红包":
        funds(db, key, event, "江湖红包", gold=-1)
        db.execute("INSERT INTO jh_packets(grp,sender,remaining) VALUES(?,?,5)", key)
        return f"🧧 五份江湖红包已备好。群友可发\n{prefix}领江湖红包"
    if cmd == "领江湖红包":
        row = db.execute(
            """SELECT id FROM jh_packets WHERE grp=? AND sender<>? AND remaining>0 AND NOT EXISTS
                          (SELECT 1 FROM jh_packet_claims WHERE packet=id AND member=?) ORDER BY id LIMIT 1""",
            (*key, member),
        ).fetchone()
        if not row:
            return "🧧 本群暂时没有你可领的红包。"
        db.execute("INSERT INTO jh_packet_claims VALUES(?,?)", (row[0], member))
        db.execute("UPDATE jh_packets SET remaining=remaining-1 WHERE id=?", row)
        funds(db, key, event, "领取红包", silver=5)
        return "🧧 你从红包里领到 5 两银子。"
