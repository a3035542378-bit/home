"""鱼包和鱼塘共用鱼获编号，所有变更随入站消息一起提交。"""
import math
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
        return f"{name}只有 {pages} 页。看最后一页请发：\n{prefix}{name}{' 重量' if by_weight else ''} {pages}"
    is_pond = storage == "pond"
    icon = "🐟" if is_pond else "🎒"
    lines = [f"{icon} 我的{name}　{level} 级", f"容量 {count}/{capacity} 条", ""]
    if is_pond and count:
        active = db.execute(pond_growth.SELECT+" AND p.member=? AND g.next_at IS NOT NULL",key).fetchall()
        lines.insert(2,f"🌱 成长位 {len(active)}/{pond_growth.SLOTS[level-1]}")
    pending=""
    show_breeding = is_pond and breeding.enabled(db,key[0])
    if show_breeding:
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
        if not is_pond:
            item=rows[0]["id"]
            pond_used,pond_capacity,_=occupancy(db,key,"pond")
            if pond_used<pond_capacity:
                lines[:3]=[f"🎒 鱼包 {count}/{capacity} 条 · 可把 #{item} {rows[0]['fish']} 存塘",
                           f"{prefix}放入鱼塘#{item}", ""]
            else:
                lines[:3]=[f"🎒 鱼包 {count}/{capacity} 条 · 塘已满，可先查单条售价",
                           f"{prefix}卖鱼", ""]
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
            lines.append(f"下一页\n{prefix}{name}{' 重量' if by_weight else ''} {page+1}")
        sample = rows[0]
        item = sample["id"]
        lines.append("")
        if is_pond:
            lines.extend(["设为招牌鱼可免偷", f"{prefix}设为招牌鱼#{item}"])
        sale_note = breeding_sale_note(db,key,item) if is_pond else ""
        lines.extend(["查看可展出的鱼", f"{prefix}放入图鉴",
                      f"立即出售 #{item} · 当前 {sample['price']} 鱼币。{sale_note}", f"{prefix}卖鱼#{item}"])
        if count > 1:
            total = db.execute("SELECT sum(price) FROM fishing_pond WHERE grp=? AND member=? AND storage=?",
                               (*key,storage)).fetchone()[0]
            cmd = "一键卖鱼" if is_pond else "卖出鱼包"
            note=breeding_sale_note(db,key) if is_pond else ""
            lines.extend([f"全部出售会清空{name} · 共 {count} 条，当前 {total} 鱼币。{note}", f"{prefix}{cmd}"])
    else:
        has_bag = is_pond and occupancy(db,key,"bag")[0]
        if pending:
            return "\n".join(lines[:3])
        hint = f"{prefix}查看鱼包" if has_bag else cast_step(db,key,prefix,now)
        navigation = f"\n🥚 查看亲鱼条件\n{prefix}繁育配对" if show_breeding else ""
        return f"{icon} {name}是空的（0/{capacity} 条）。\n{hint}{navigation}"
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


def cast_step(db, key, prefix, now):
    broken_offshore = db.execute("""SELECT 1 FROM fishing_tackle t JOIN fishing_waters w USING(grp,member)
                                    WHERE t.grp=? AND t.member=? AND t.broken=1 AND w.area!='新手池塘'""",key).fetchone()
    if broken_offshore:
        return f"鱼线已断，先免费返回新手池塘\n{prefix}切换水域 新手池塘"
    from .db import DEFAULT
    ready=db.execute("""SELECT coalesce(t.last_attempt,r.last_cast) +
                            coalesce(json_extract(g.config,'$.fishing_cooldown_seconds'),?)
                        FROM groups g LEFT JOIN fishing_tackle t ON t.grp=g.id AND t.member=?
                        LEFT JOIN fishing_records r ON r.grp=g.id AND r.member=?
                        WHERE g.id=?""",(DEFAULT["fishing_cooldown_seconds"],key[1],key[1],key[0])).fetchone()
    if ready and ready[0] is not None and now is not None and ready[0]>now:
        return f"再等 {math.ceil(ready[0]-now)} 秒即可抛竿。先看钓鱼信息\n{prefix}钓鱼信息"
    return prefix+"抛竿"


def pond_full(count, capacity, prefix):
    return f"🐟 鱼塘已满（{count}/{capacity} 条），鱼仍在鱼包里。先选塘鱼腾位。\n{prefix}查看鱼塘"


def move_to_pond(db, key, item, prefix, now):
    fish = db.execute("SELECT fish FROM fishing_pond WHERE grp=? AND member=? AND id=? AND storage='bag'",
                      (*key, item)).fetchone()
    if not fish:
        return f"你的鱼包里没有这条鱼。查看可入塘的鱼\n{prefix}放入鱼塘"
    count, capacity, _ = occupancy(db, key, "pond")
    if count >= capacity:
        return pond_full(count,capacity,prefix)
    db.execute("UPDATE fishing_pond SET storage='pond' WHERE grp=? AND member=? AND id=?", (*key, item))
    status = pond_growth.install(db,key,item,now)
    pond_growth.mark(db,key,now,"store")
    return f"已将 #{item} {fish[0]} 放入鱼塘（{count+1}/{capacity} 条）。\n{prefix}鱼塘\n{status}"


def breeding_sale_note(db, key, item=None):
    pair = db.execute("SELECT p1,p2 FROM breed_pairs WHERE grp=? AND member=? AND state='active'",key).fetchone()
    if pair and (item is None or item in tuple(pair)):
        return "配对会中止，费用不退。"
    return ""


def sell(db, key, column, value, prefix, now):
    # column 由指令分派固定为 id 或 storage。
    where = f"grp=? AND member=? AND {column}=?"
    params = (*key, value)
    count, total = db.execute("SELECT count(*),sum(price) FROM fishing_pond WHERE "+where, params).fetchone()
    if not count:
        if column=="id":
            return f"你的鱼包和鱼塘里没有这条鱼。查看可售的鱼\n{prefix}卖鱼"
        return f"{NAMES[value]}是空的。查看库存\n{prefix}查看{NAMES[value]}"
    breed_metrics.sale(db,where,params,now)
    db.execute("DELETE FROM pond_growth WHERE item IN (SELECT id FROM fishing_pond WHERE "+where+")",params)
    db.execute("DELETE FROM fishing_pond WHERE "+where, params)
    coins = db.execute("UPDATE fishing_wallets SET coins=coins+? WHERE grp=? AND member=? RETURNING coins",
                       (total, *key)).fetchone()[0]
    return (f"🪙 卖出 {count} 条鱼\n到账 {total} 枚鱼币\n当前余额　{coins} 鱼币\n"
            f"{prefix}钓鱼信息")


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
    if cmd in ("卖鱼", "放入图鉴", "放入鱼塘"):
        rows = db.execute("""SELECT p.id,p.fish,p.price,p.storage,p.grams,e.grams exhibited FROM fishing_pond p
                             LEFT JOIN fishing_exhibits e USING(grp,member,fish)
                             WHERE p.grp=? AND p.member=? ORDER BY p.storage='bag' DESC,p.price,p.id""",key).fetchall()
        if cmd=="放入鱼塘":
            rows=[r for r in rows if r["storage"]=="bag"]
            used,capacity,_=occupancy(db,key,"pond")
            if rows and used>=capacity:
                return pond_full(used,capacity,prefix)
        if cmd=="放入图鉴" and rows:
            used,capacity,_=occupancy(db,key,"bag")
            rows=[r for r in rows if r["fish"] in HABITAT and
                  (r["exhibited"] is None or (r["grams"]>r["exhibited"] and (r["storage"]=="bag" or used<capacity)))]
            if not rows:
                return f"📖 暂无可直接展出的鱼。查看图鉴里的鱼种和展品重量\n{prefix}全图鉴"
        if not rows:
            return f"🎒 还没有可选的鱼获编号。先钓一条，鱼获会收入鱼包。\n{cast_step(db,key,prefix,now)}"
        row=rows[0]
        label=f"#{row['id']} {row['fish']}"
        if cmd=="卖鱼":
            detail=f"🪙 #{row['id']} {row['fish']} · {row['price']} 鱼币，发送即卖出。"
            detail+=breeding_sale_note(db,key,row["id"]) if row["storage"]=="pond" else ""
        elif cmd=="放入鱼塘":
            detail=f"🐟 {label} 在鱼包里，发送即可入塘（{used}/{capacity} 条）。"
        else:
            detail=f"📖 发送即可展出编号 {label}。" + ("原展品将退回鱼包。" if row["exhibited"] is not None else "")
        return f"{detail}\n{prefix}{cmd}#{row['id']}"
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
