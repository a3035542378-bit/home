"""按群、本人及来源库存处理用户选定的鱼号。"""
import re

from . import exhibit_batch, pond_growth, pond_view


SOURCES = {"批量放入鱼塘": "bag", "批量卖出鱼包": "bag", "批量收回鱼包": "pond",
           "批量卖出塘鱼": "pond", "批量投喂": "pond"}
COMMAND = re.compile("(" + "|".join(SOURCES) + r")\s*(.*)", re.S)


def match(cmd):
    return COMMAND.fullmatch(cmd.strip().translate(exhibit_batch.WIDTH))


def handle(db, key, request, prefix, now):
    from . import fish_storage
    action, value = request.groups()
    source = SOURCES[action]
    place = fish_storage.NAMES[source]
    ids = exhibit_batch.parse_numbers(value) if value else None
    limit = exhibit_batch.LIMIT
    if ids == () or (ids and len(ids) > limit):
        return f"请填写 1 至 {limit} 个不同鱼号，用顿号隔开。本次未执行。\n{prefix}{action}"
    stock = {r["id"]: r for r in db.execute(pond_view.STOCK+" AND p.storage=? ORDER BY p.id", (*key, source))}
    pair = db.execute("SELECT p1,p2 FROM breed_pairs WHERE grp=? AND member=? AND state='active'", key).fetchone()
    parents = set(pair or ())
    moving = {"批量放入鱼塘":"pond", "批量收回鱼包":"bag"}.get(action)
    selling = action in ("批量卖出鱼包", "批量卖出塘鱼")
    if moving:
        used, capacity, _ = fish_storage.occupancy(db, key, moving)
        spaces = max(0, capacity-used)
    preview = ids is None
    selected, skipped = [], []
    balance = next(iter(stock.values()))["coins"] if stock else 0
    total = 0
    for item in stock if preview else ids:
        row = stock.get(item)
        reason = ""
        price = 0
        if row is None:
            reason = f"不在你的{place}"
        elif source == "pond" and action != "批量投喂" and (item in parents or row["flagship"]):
            reason = "配对亲鱼或招牌鱼受保护"
        elif moving and len(selected) >= spaces:
            reason = fish_storage.NAMES[moving]+"已满"
        elif action == "批量投喂":
            meal = pond_view.feed(row)
            if meal is None:
                reason = "当前无需投喂"
            elif total + meal[1] > balance:
                reason = "鱼币不足"
            else:
                price = meal[1]
        elif selling:
            price = row["price"]
        if reason:
            skipped.append(f"#{item} {reason}")
            continue
        selected.append(item)
        total += price
        if preview and len(selected) == limit:
            break
        if preview:
            continue
        if selling:
            fish_storage.sell(db, key, "id", item, prefix, now)
        elif moving == "pond":
            fish_storage.move_to_pond(db, key, item, prefix, now)
        elif moving == "bag":
            pond_growth.leave(db, item, now)
            db.execute("UPDATE fishing_pond SET storage='bag' WHERE grp=? AND member=? AND id=? AND storage='pond'", (*key,item))
        else:
            pond_growth.act(db, key, "投喂", item, now, prefix)
    numbers = "、".join(f"#{i}" for i in selected)
    lines = [f"{action}{'预览' if preview else '结果'} · {'可处理' if preview else '已处理'} {len(selected)} 条"]
    if selected:
        lines.append(numbers)
        if selling or action == "批量投喂":
            lines.append(("售价合计" if selling else "饲料费合计")+f" {total} 鱼币")
        if preview:
            lines.extend(["可删掉不想处理的鱼号，再发送", f"{prefix}{action} {numbers}"])
    if skipped and (not preview or not selected):
        lines.append("跳过："+"；".join(skipped[:limit]))
    if not stock and preview:
        lines.append(f"你的{place}是空的。")
    return "\n".join(lines)
