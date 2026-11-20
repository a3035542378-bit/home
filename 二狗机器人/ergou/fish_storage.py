"""鱼包和鱼塘共用鱼获编号，所有变更随入站消息一起提交。"""
import re
import time

from . import breed_metrics, breeding, fish_grades, pond_growth
from .fishing_waters import HABITAT, size_grade, weight


# 每级的容量、由上一级升到该级的鱼币费用
TIERS = {
    "bag": ((5, 0), (8, 25), (12, 65), (16, 140), (20, 260)),
    "pond": ((1, 0), (4, 20), (10, 60), (20, 150), (30, 300)),
}
NAMES = {"bag": "鱼包", "pond": "鱼塘"}
PAGE = re.compile(r"(?:查看)?(鱼包|鱼塘)(?: (重量))?(?: ([1-9][0-9]{0,5}))?")
ITEM = re.compile(r"(放入鱼塘|放入图鉴|点亮图鉴|卖鱼)\s*[#＃]([1-9][0-9]{0,17})")
COMMANDS = {"升级鱼包", "升级鱼塘", "卖出鱼包", "一键卖鱼", "放入图鉴", "放入鱼塘", "卖鱼"}


def matches(cmd):
    return pond_growth.ACTION.fullmatch(cmd) or cmd in COMMANDS or PAGE.fullmatch(cmd) or ITEM.fullmatch(cmd)


def level_for(db, key, storage):
    row = db.execute("SELECT level FROM fishing_storage_levels WHERE grp=? AND member=? AND storage=?",
                     (*key, storage)).fetchone()
    return row[0] if row else 1


def occupancy(db, key, storage):
    level = level_for(db, key, storage)
    count = db.execute("SELECT count(*) FROM fishing_pond WHERE grp=? AND member=? AND storage=?",
                       (*key, storage)).fetchone()[0]
    return count, TIERS[storage][level-1][0], level


def inventory(db, key, storage, page, by_weight, prefix, now=None, changes=None):
    name = NAMES[storage]
    count, capacity, level = occupancy(db, key, storage)
    page_size = 2 if storage == "pond" else 6
    pages = max(1, (count+page_size-1)//page_size)
    if page > pages:
        return f"{name}只有 {pages} 页。"
    is_pond = storage == "pond"
    icon = "🐟" if is_pond else "🎒"
    lines = [f"{icon} 我的{name}　{level} 级", f"容量 {count}/{capacity} 条", ""]
    if is_pond and count:
        active = db.execute(pond_growth.SELECT+" AND p.member=? AND g.next_at IS NOT NULL",key).fetchall()
        lines.insert(2,f"🌱 成长位 {len(active)}/{pond_growth.SLOTS[level-1]}")
    if is_pond and breeding.enabled(db,key[0]):
        pending=breeding.banner(breeding.state(db,key),prefix)
        if pending:
            lines[1:1]=[pending]
        else:
            lines.append(f"🥚 选亲鱼　{prefix}繁育配对")
    if count:
        order = "grams DESC,id DESC" if by_weight else "id DESC"
        rows = db.execute(f"""SELECT id,fish,grams,price,grade,grade_upgraded FROM fishing_pond
                              WHERE grp=? AND member=? AND storage=? ORDER BY {order} LIMIT ? OFFSET ?""",
                          (*key, storage, page_size, (page-1)*page_size)).fetchall()
        for row in rows:
            if is_pond:
                detail = pond_growth.panel(db,key,row["id"],changes or {},prefix,now if now is not None else time.time())
                if detail:
                    lines.extend([*detail,""])
                    continue
            grade=size_grade(row["fish"],row["grams"])
            label=f" · {grade}" if grade else ""
            quality = fish_grades.label(row["grade"], row["grade_upgraded"])
            lines.append(f"#{row['id']} {row['fish']}　{weight(row['grams'])}{label}　{row['price']} 鱼币")
            child = breeding.fry(db,row["id"])
            if child:
                lines.append("　🐣 "+breeding.source(child,key[1]))
            if quality:
                lines.append("　🏷️ " + quality)
        if page < pages:
            lines.append(f"翻页　{prefix}{name}{' 重量' if by_weight else ''} {page+1}")
        sample = rows[0]["id"]
        lines.append("")
        if count > 1:
            lines.append(f"选鱼操作（以 #{sample} 为例）")
        if is_pond:
            lines.append(f"招牌免偷　{prefix}设为招牌鱼#{sample}")
        if not is_pond:
            lines.append(f"移入鱼塘　{prefix}放入鱼塘#{sample}")
        lines.extend([f"点亮图鉴　{prefix}放入图鉴#{sample}", f"卖这一条　{prefix}卖鱼#{sample}"])
        if count > 1:
            lines.append(f"卖整塘　　{prefix}一键卖鱼" if is_pond else f"卖整包　　{prefix}卖出鱼包")
    else:
        lines.append(f"鱼塘是空的。发「{prefix}查看鱼包」选鱼放入。" if is_pond else f"鱼包是空的。发「{prefix}抛竿」试试手气。")
    if count > capacity:
        lines.append("原有鱼获已保留，腾出位置或扩容后可继续存鱼。")
    if level < len(TIERS[storage]):
        next_capacity, cost = TIERS[storage][level]
        lines.extend(["", f"扩到 {next_capacity} 条需 {cost} 鱼币", f"{prefix}升级{name}"])
    return "\n".join(lines)


def upgrade(db, key, storage):
    name = NAMES[storage]
    level = level_for(db, key, storage)
    tiers = TIERS[storage]
    if level >= len(tiers):
        return f"{name}已满级，最多 {tiers[-1][0]} 条。"
    capacity, cost = tiers[level]
    db.execute("INSERT OR IGNORE INTO fishing_wallets(grp,member) VALUES(?,?)", key)
    paid = db.execute("UPDATE fishing_wallets SET coins=coins-? WHERE grp=? AND member=? AND coins>=?",
                      (cost, *key, cost))
    if not paid.rowcount:
        return f"升级{name}需要 {cost} 鱼币。"
    db.execute("""INSERT INTO fishing_storage_levels(grp,member,storage,level) VALUES(?,?,?,?)
                  ON CONFLICT(grp,member,storage) DO UPDATE SET level=excluded.level""",
               (*key, storage, level+1))
    return f"{name}已升到 {level+1} 级，可放 {capacity} 条鱼，消耗 {cost} 鱼币。"


def move_to_pond(db, key, item, prefix, now):
    fish = db.execute("SELECT fish FROM fishing_pond WHERE grp=? AND member=? AND id=? AND storage='bag'",
                      (*key, item)).fetchone()
    if not fish:
        return "你的鱼包里没有这条鱼。"
    count, capacity, _ = occupancy(db, key, "pond")
    if count >= capacity:
        hint = "可卖出塘里的鱼。" if capacity == TIERS["pond"][-1][0] else "可卖鱼或升级鱼塘。"
        return f"鱼塘已满（{count}/{capacity} 条），鱼仍在鱼包里。{hint}"
    db.execute("UPDATE fishing_pond SET storage='pond' WHERE grp=? AND member=? AND id=?", (*key, item))
    status = pond_growth.install(db,key,item,now)
    if status.startswith("成长位已满"):
        status += f"\n{prefix}换入成长位#{item}"
    pond_growth.mark(db,key,now,"store")
    return f"已将 #{item} {fish[0]} 放入鱼塘（{count+1}/{capacity} 条）。\n{status}\n🛡️ 查看护塘　{prefix}鱼塘保护"


def sell(db, key, column, value, prefix, now):
    # column 由指令分派固定为 id 或 storage。
    where = f"grp=? AND member=? AND {column}=?"
    params = (*key, value)
    count, total = db.execute("SELECT count(*),sum(price) FROM fishing_pond WHERE "+where, params).fetchone()
    if not count:
        return "你的鱼包和鱼塘里没有这条鱼。" if column == "id" else f"{NAMES[value]}是空的。"
    breed_metrics.sale(db,where,params,now)
    db.execute("DELETE FROM pond_growth WHERE item IN (SELECT id FROM fishing_pond WHERE "+where+")",params)
    db.execute("DELETE FROM fishing_pond WHERE "+where, params)
    coins = db.execute("UPDATE fishing_wallets SET coins=coins+? WHERE grp=? AND member=? RETURNING coins",
                       (total, *key)).fetchone()[0]
    return (f"🪙 卖出 {count} 条鱼\n到账 {total} 枚鱼币\n当前余额　{coins} 鱼币\n\n"
            f"📋 个人档案　{prefix}钓鱼信息")


def exhibit(db, key, item, prefix, now):
    catch = db.execute("""SELECT fish,grams,price,storage,grade,grade_upgraded FROM fishing_pond
                          WHERE grp=? AND member=? AND id=?""", (*key, item)).fetchone()
    if not catch:
        return "你的鱼包和鱼塘里没有这条鱼。"
    fish = catch["fish"]
    if fish not in HABITAT:
        return "当前图鉴还没有这个鱼种，鱼仍在原处。"
    slot = (*key, fish)
    old = db.execute("SELECT item_id,grams,price,grade,grade_upgraded FROM fishing_exhibits WHERE grp=? AND member=? AND fish=?",
                     slot).fetchone()
    if old and catch["grams"] <= old["grams"]:
        return f"📖 图鉴已有{fish}　{weight(old['grams'])}\n只接受更重的同种鱼。\n#{item} 仍在{NAMES[catch['storage']]}。"
    if old and catch["storage"] == "pond":
        used, capacity, _ = occupancy(db, key, "bag")
        if used >= capacity:
            return f"旧展品需要放回鱼包。请先发「{prefix}查看鱼包」腾出一格，再换入这条鱼。"

    pond_growth.register(db,item)
    pond_growth.leave(db,item,now)
    if not old:
        pond_growth.mark(db,key,now,"light")
    # 入站事务中转移实物，替换时保留旧鱼的编号、重量和售价。
    db.execute("DELETE FROM fishing_pond WHERE grp=? AND member=? AND id=?", (*key, item))
    db.execute("""INSERT INTO fishing_exhibits(grp,member,fish,item_id,grams,price,grade,grade_upgraded) VALUES(?,?,?,?,?,?,?,?)
                  ON CONFLICT(grp,member,fish) DO UPDATE SET
                  item_id=excluded.item_id,grams=excluded.grams,price=excluded.price,
                  grade=excluded.grade,grade_upgraded=excluded.grade_upgraded""",
               (*slot, item, catch["grams"], catch["price"], catch["grade"], catch["grade_upgraded"]))
    if not old:
        return f"✨ 已点亮　{fish}\n展品 #{item}　{weight(catch['grams'])}\n\n展出期间受保护。\n可用更重的同种鱼替换。"
    db.execute("""INSERT INTO fishing_pond(grp,member,fish,id,grams,price,grade,grade_upgraded,storage)
                  VALUES(?,?,?,?,?,?,?,?,'bag')""", (*slot, old["item_id"], old["grams"], old["price"], old["grade"], old["grade_upgraded"]))
    return (f"✨ 已换入 #{item} {fish} · {weight(catch['grams'])}。\n"
            f"原展品 #{old['item_id']} · {weight(old['grams'])} 已放回鱼包。")


def handle(db, key, cmd, prefix, now=None):
    now = time.time() if now is None else now
    changes = pond_growth.settle(db,key[0],now,key[1])
    action = pond_growth.ACTION.fullmatch(cmd)
    if action:
        return pond_growth.act(db,key,action[1],int(action[2]),now,prefix)
    if cmd == "卖鱼":
        return f"🎒 你想卖哪条鱼？发送「{prefix}鱼包」查看鱼的编号。\n例如　{prefix}卖鱼#17"
    if cmd in ("放入图鉴", "放入鱼塘"):
        return (f"🐟 想选哪条鱼？请带上鱼的编号。\n例如　{prefix}{cmd}#17\n"
                f"查看编号　{prefix}查看鱼包" + ("" if cmd == "放入鱼塘" else f" / {prefix}查看鱼塘"))
    page = PAGE.fullmatch(cmd)
    if page:
        storage = "bag" if page[1] == "鱼包" else "pond"
        return inventory(db, key, storage, int(page[3] or 1), bool(page[2]), prefix, now, changes)
    item = ITEM.fullmatch(cmd)
    if item:
        number = int(item[2])
        if item[1] == "放入鱼塘":
            return move_to_pond(db, key, number, prefix, now)
        if item[1] in ("放入图鉴", "点亮图鉴"):
            return exhibit(db, key, number, prefix, now)
        return sell(db, key, "id", number, prefix, now)
    if cmd in ("升级鱼包", "升级鱼塘"):
        return upgrade(db, key, "bag" if cmd == "升级鱼包" else "pond")
    if cmd in ("卖出鱼包", "一键卖鱼"):
        return sell(db, key, "storage", "bag" if cmd == "卖出鱼包" else "pond", prefix, now)
    raise ValueError("未识别的鱼获指令")
