"""首次配对指引使用玩家实际拥有的鱼号，不修改资产。"""
from collections import defaultdict

from . import breeding, fish_storage, pond_growth
from .fish_receipts import grid
from .fishing_waters import HABITAT


def stock(db, key):
    rows = db.execute("""
        SELECT p.id, p.fish, p.storage, p.grams, p.price, p.grade,
               coalesce(g.original_grams,p.grams) original_grams,
               coalesce(g.rounds,0) rounds, g.next_at, f.item child
        FROM fishing_pond p LEFT JOIN pond_growth g ON g.item=p.id
        LEFT JOIN breed_fry f ON f.item=p.id
        WHERE p.grp=? AND p.member=? ORDER BY p.id""", key)
    return [dict(row, mature=breeding.adult(row, row["child"])) for row in rows
            if row["fish"] in HABITAT and (row["grade"] is not None or breeding.adult(row,row["child"]))]


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


def parent_cells(row):
    stage="成年" if row["mature"] else "幼鱼" if row["child"] else "待定型"
    return f"编号: {row['id']}", "鱼塘" if row["storage"]=="pond" else "鱼包", stage


def guide(db, key, prefix, now):
    fish=stock(db,key)
    used,capacity,level=fish_storage.occupancy(db,key,"pond")
    location=db.execute("SELECT area FROM fishing_waters WHERE grp=? AND member=?",key).fetchone()
    area=location[0] if location else "新手池塘"
    pair=closest(fish,area,capacity-used)
    species=pair[0]["fish"] if pair else ""
    bag=[r for r in pair if r["storage"]=="bag"]
    missing=f"还缺一条成年{species}，可在{HABITAT[species]}钓到。" if len(pair)==1 else ""
    def reply(status, step):
        lines=["🥚 繁育配对",status]
        if pair:
            lines.extend(["",*grid(map(parent_cells,pair))])
        return "\n".join([*lines,"",step])
    if capacity<2 or len(bag)>capacity-used:
        need=max(0,len(bag)+used-capacity)
        status=(missing or species)+(" · " if pair else "")+(
            "一级塘只能放一条鱼。" if capacity<2 else f"先腾 {need} 个塘位，保留亲鱼。")
        if capacity<2:
            cap,cost=fish_storage.POND_TIERS[level]
            wallet=db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()
            coins=wallet[0] if wallet else 30
            status+=f"当前 {used}/{capacity}，扩到 {cap} 条需 {cost} 鱼币，余额 {coins} 鱼币。"
            if coins>=cost:
                return reply(status,f"发送即升级\n{prefix}升级鱼塘")
            spare=min((r for r in fish if r not in pair),key=lambda r:r["price"],default=None)
            step=(f"卖出编号 {spare['id']} 可得 {spare['price']} 鱼币\n{prefix}卖鱼#{spare['id']}"
                  if spare else catch_step(db,key,prefix,area,area,now))
            return reply(status+f"还差 {cost-coins} 币。",step)
        wallet=db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()
        if level<len(fish_storage.POND_TIERS):
            cap,cost=fish_storage.POND_TIERS[level]
            if (wallet[0] if wallet else 30)>=cost:
                return reply(status,f"也可扣 {cost} 鱼币扩到 {cap} 格\n{prefix}升级鱼塘")
        return reply(status,prefix+"鱼塘操作")
    if bag:
        item=bag[0]["id"]
        return reply(missing or f"{species}已凑齐，编号 {item} 还在包里。",f"先将编号 {item} 放入鱼塘\n{prefix}放入鱼塘#{item}")
    if len(pair)<2:
        return reply(missing or "先留两条同种鱼，养到成年后可配对。",
                     catch_step(db,key,prefix,area,HABITAT.get(species,area),now))
    growing=[r for r in pair if not r["mature"]]
    if growing:
        row=growing[0]
        item=row["id"]
        stage="成年" if row["child"] else "定型"
        status=f"{species}已找到一对，等"+("两条鱼都成年" if len(growing)==2 else f"编号 {item} {stage}")+"后就能配对。"
        if row["next_at"] is not None:
            return reply(status,f"🌱 编号 {item} 正在成长，下轮北京时间 {breeding.clock(row['next_at'])}。\n{prefix}繁育配对")
        return reply(status,f"🌱 {pond_growth.slot_hint(db,key,item)}\n{prefix}换入成长位#{item}")
    a,b=sorted(r["id"] for r in pair)
    return reply(f"两条成年{species}可以配对。",f"免费预览，确认才扣 {breeding.FEE} 鱼币\n{prefix}繁育配对#{a} #{b}")


def catch_step(db, key, prefix, area, target, now):
    used, capacity, _ = fish_storage.occupancy(db, key, "bag")
    if used >= capacity:
        return f"鱼包已满，先选鱼腾位\n{prefix}查看鱼包"
    if area != target:
        return f"去{target}\n{prefix}切换钓场 {target}"
    tackle = db.execute("SELECT broken FROM fishing_tackle WHERE grp=? AND member=?", key).fetchone()
    if tackle and tackle[0] and area != "新手池塘":
        return f"鱼线已断，先看换线办法\n{prefix}鱼线"
    return f"🎣 在{area}钓鱼\n"+fish_storage.cast_step(db,key,prefix,now)
