"""首次配对指引使用玩家实际拥有的鱼号，不修改资产。"""
from collections import defaultdict

from . import breeding, fish_storage
from .fishing_waters import HABITAT


def stock(db, key):
    rows = db.execute("""
        SELECT p.id, p.fish, p.storage, p.grams, p.price,
               coalesce(g.original_grams,p.grams) original_grams,
               coalesce(g.rounds,0) rounds, g.next_at, f.item child
        FROM fishing_pond p LEFT JOIN pond_growth g ON g.item=p.id
        LEFT JOIN breed_fry f ON f.item=p.id
        WHERE p.grp=? AND p.member=? ORDER BY p.id""", key)
    return [dict(row, mature=breeding.adult(row, row["child"])) for row in rows
            if row["fish"] in HABITAT]


def readiness_order(row):
    return (not row["mature"], row["storage"] == "bag", row["next_at"] is None,
            -row["rounds"], row["id"])


def closest(fish, area, free):
    species = defaultdict(list)
    for row in fish:
        species[row["fish"]].append(row)
    pairs = [sorted(school, key=readiness_order)[:2] for school in species.values()]
    def priority(pair):
        in_bag = sum(r["storage"] == "bag" for r in pair)
        return (-len(pair), max(0, in_bag-free), sum(not r["mature"] for r in pair),
                in_bag, sum(not r["mature"] and r["next_at"] is None for r in pair),
                HABITAT[pair[0]["fish"]] != area, readiness_order(pair[0]))
    return min(pairs, key=priority, default=[])


def describe(row):
    age = "成年" if row["mature"] else ("幼鱼" if row["child"] else "待定型")
    place = "塘里" if row["storage"] == "pond" else "包里"
    return f"{place} #{row['id']}（{age}）"


def guide(db, key, prefix):
    fish = stock(db, key)
    used, capacity, level = fish_storage.occupancy(db, key, "pond")
    location = db.execute("SELECT area FROM fishing_waters WHERE grp=? AND member=?", key).fetchone()
    area = location[0] if location else "新手池塘"
    pair = closest(fish, area, capacity-used)
    species = pair[0]["fish"] if pair else ""
    bag = [row for row in pair if row["storage"] == "bag"]
    if len(pair) == 2 and not bag and all(r["mature"] for r in pair):
        a, b = sorted(r["id"] for r in pair)
        return f"🐟 塘里有一对成年{species}　#{a}、#{b}\n免费预览，确认才扣 {breeding.FEE} 鱼币\n{prefix}繁育配对#{a} #{b}"

    lines = [f"🐟 {species}　" + "、".join(map(describe, pair))] if pair else []
    if len(pair) == 1:
        lines.append(f"还缺一条同种鱼 · 可钓水域：{HABITAT[species]}")
    if capacity < 2 or (bag and len(bag) > capacity-used):
        if level < len(fish_storage.TIERS["pond"]):
            next_capacity, cost = fish_storage.TIERS["pond"][level]
            wallet = db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?", key).fetchone()
            coins = wallet[0] if wallet else 30  # 新玩家首次升级时使用的钱包初始余额。
            lines.append(f"🏡 {level} 级塘 {used}/{capacity} 条 · 扩到 {next_capacity} 条需 {cost} 鱼币")
            if coins >= cost:
                return "\n".join([*lines, f"余额 {coins} 鱼币，发指令升级", prefix+"升级鱼塘"])
            if capacity < 2:
                lines.append(f"余额 {coins} 鱼币，还差 {cost-coins} 币")
        if capacity >= 2:
            need = used + len(bag) - capacity
            return "\n".join([*lines, f"先腾 {need} 个塘位，保留上面的亲鱼", prefix+"查看鱼塘"])
        spare = min((r for r in fish if r not in pair), key=lambda r: r["price"], default=None)
        if spare:
            return "\n".join([*lines, f"可卖其他鱼筹币：{prefix}卖鱼#{spare['id']}"])
        return "\n".join([*lines, catch_step(db, key, prefix, area, area)])

    if bag:
        return "\n".join([*lines, "先将这条鱼放入鱼塘", f"{prefix}放入鱼塘#{bag[0]['id']}"])
    growing = [r for r in pair if not r["mature"]]
    if growing:
        active = next((r for r in growing if r["next_at"] is not None), None)
        if active and len(pair) == 1:
            return "\n".join([*lines, f"🌱 #{active['id']} 正在成长，可以先去找另一条",
                              catch_step(db, key, prefix, area, HABITAT[species])])
        if active:
            return "\n".join([*lines, f"🌱 #{active['id']} 正在成长，下轮 {breeding.clock(active['next_at'])[-8:]}",
                              f"等它成年再选亲鱼：{prefix}繁育配对"])
        return "\n".join([*lines, "🌱 先让这条鱼在成长位养到成年", f"{prefix}换入成长位#{growing[0]['id']}"])
    if not pair:
        lines.append("🎣 先钓一条鱼，再留一条同种鱼养成亲鱼。")
    return "\n".join([*lines, catch_step(db, key, prefix, area, HABITAT.get(species, area))])


def catch_step(db, key, prefix, area, target):
    used, capacity, _ = fish_storage.occupancy(db, key, "bag")
    if used >= capacity:
        return f"鱼包已满，先选鱼腾位：{prefix}查看鱼包"
    if area != target:
        return f"去{target}：{prefix}切换钓场 {target}"
    tackle = db.execute("SELECT broken FROM fishing_tackle WHERE grp=? AND member=?", key).fetchone()
    if tackle and tackle[0] and area != "新手池塘":
        return f"鱼线已断，先看换线办法：{prefix}鱼线"
    return f"🎣 在{area}下竿：{prefix}抛竿"
