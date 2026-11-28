"""鱼包和鱼塘共用鱼获编号，所有变更随入站消息一起提交。"""
import math
import re
import time

from . import breed_metrics, breeding, exhibit_batch, exhibit_rewards, fish_grades, pond_growth, pond_view, storage_batch
from .fish_receipts import grid, mass
from .fishing_waters import HABITAT, size_grade, weight


BAG_CAPACITY = 5
# 每级鱼塘容量、由上一级升到该级的鱼币费用。
POND_TIERS = ((1, 0), (4, 20), (10, 60), (20, 150), (30, 300))
NAMES = {"bag": "鱼包", "pond": "鱼塘"}
PAGE = re.compile(r"(?:查看)?(鱼包|鱼塘)(?: (重量))?(?: ([1-9][0-9]{0,5}))?")
ITEM = re.compile(r"(放入鱼塘|放入图鉴|点亮图鉴|卖鱼)\s*[#＃]([1-9][0-9]{0,17})")
CHOOSERS = {"投喂","查看鱼","换入成长位","设为招牌鱼"}
COMMANDS = CHOOSERS | {"鱼塘操作", "升级鱼包", "升级鱼塘", "卖出鱼包", "一键卖鱼", "放入图鉴", "放入鱼塘", "卖鱼"}


def matches(cmd):
    return storage_batch.match(cmd) or pond_view.DETAIL.fullmatch(cmd) or pond_growth.ACTION.fullmatch(cmd) or cmd in COMMANDS or PAGE.fullmatch(cmd) or ITEM.fullmatch(cmd)


def pond_level(db, key):
    row = db.execute("SELECT level FROM fishing_storage_levels WHERE grp=? AND member=? AND storage='pond'",key).fetchone()
    return row[0] if row else 1


def occupancy(db, key, storage):
    count = db.execute("SELECT count(*) FROM fishing_pond WHERE grp=? AND member=? AND storage=?",
                       (*key, storage)).fetchone()[0]
    if storage == "bag":
        return count, BAG_CAPACITY, 1
    level = pond_level(db, key)
    return count, POND_TIERS[level-1][0], level


def inventory(db, key, storage, page, by_weight, prefix, now=None, changes=None):
    if storage=="pond":
        return pond_view.home(db,key,page,by_weight,prefix,changes or {},now)
    count, capacity, _ = occupancy(db, key, "bag")
    if not count:
        from .fishing_cards import sheet
        step=cast_step(db,key,prefix,now)
        return sheet(f"🎒 鱼包是空的（0/{capacity} 条）。\n{step}",prefix,"鱼包手记","空鱼包",
                     f"已占 0/{capacity} 格",lines=[step])
    order="grams DESC,id DESC" if by_weight else "id DESC"
    rows=db.execute(f"""SELECT * FROM fishing_pond WHERE grp=? AND member=? AND storage='bag'
                        ORDER BY {order}""",key).fetchall()
    sample=rows[0]
    item=sample["id"]
    pond_used,pond_capacity,_=occupancy(db,key,"pond")
    if pond_used<pond_capacity:
        step=f"{prefix}放入鱼塘#{item}"
        purpose=f"可把 #{item} {sample['fish']} 存塘"
    else:
        step=prefix+"鱼塘操作"
        purpose="鱼塘已满，先查看塘位"
    lines=[f"🎒 鱼包 {count}/{capacity} 条"]
    if count > capacity:
        lines.append(f"原有 {count} 条都在，移出 {count-capacity+1} 条就能继续钓。")
    lines.append("")
    lines.extend(grid((f"编号: {r['id']}",r["fish"],mass(r["grams"]),f"{r['price']} 鱼币",fish_grades.label(r["grade"],r["grade_upgraded"]) or "历史鱼") for r in rows))
    for row in rows:
        child=breeding.fry(db,row["id"])
        if child:
            lines.append(f"🐣 编号 {row['id']} · "+breeding.source(child,key[1]))
    lines.extend(["","🎒 处理鱼获","【放入图鉴】查看可展出的鱼",f"【卖鱼#{item}】立即出售，到账 {sample['price']} 鱼币"])
    if count>1:
        lines.extend(["【批量放入鱼塘】选鱼入塘", "【批量卖出鱼包】选鱼出售"])
        total=db.execute("SELECT sum(price) FROM fishing_pond WHERE grp=? AND member=? AND storage='bag'",key).fetchone()[0]
        lines.append(f"【卖出鱼包】清空 {count} 条，共 {total} 鱼币")
    lines.extend(["", "💬 "+purpose,step])
    from .fishing_cards import JournalReply
    entries = [(r["fish"], f"#{r['id']}  ·  {mass(r['grams'])}  ·  {r['price']} 鱼币  ·  " +
                (fish_grades.label(r["grade"], r["grade_upgraded"]).replace("✨","").strip() or "历史鱼"))
               for r in rows]
    receipt=JournalReply("\n".join(lines), heading="鱼包手记", title="我的鱼包",
                        subtitle=f"已占 {count}/{capacity} 格", entries=entries,
                        notes=[line for line in lines if line.startswith(("原有", "🐣", "💬"))],
                        commands=[step, prefix+"放入图鉴", prefix+f"卖鱼#{item}",
                                  *([prefix+"批量卖出鱼包"] if count>1 else [])])
    receipt.snapshot=dict(kind="bag",journal=receipt.card,title=f"我的鱼包   {count}/{capacity}",step=step,
                     rows=[dict(id=r["id"],fish=r["fish"],grams=r["grams"],price=r["price"],
                                quality=fish_grades.label(r["grade"],r["grade_upgraded"]) or "历史鱼") for r in rows])
    if count>5:
        pages=(count+4)//5
        current=min(page,pages)
        receipt.card["entries"]=entries[(current-1)*5:current*5]
        route=prefix+"鱼包"+(" 重量" if by_weight else "")
        receipt.card["subtitle"]+=f"  /  第 {current}/{pages} 页"
        receipt.card["commands"]=[route+" "+str(n) for n in (current-1,current+1) if 1<=n<=pages]+[prefix+"批量卖出鱼包"]
    return receipt


def shortfall(db,key,cost,prefix,now,reason):
    wallet=db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()
    coins=wallet[0] if wallet else 30
    stock=db.execute("SELECT 1 FROM fishing_pond WHERE grp=? AND member=? LIMIT 1",key).fetchone()
    step=f"先查一条鱼的售价\n{prefix}卖鱼" if stock else cast_step(db,key,prefix,now)
    return f"{reason}需要 {cost} 鱼币，余额不足。\n当前 {coins} 币，还差 {cost-coins} 币。\n{step}"


def upgrade_pond(db, key, prefix, now):
    level = pond_level(db, key)
    if level >= len(POND_TIERS):
        return f"鱼塘已满级，最多 {POND_TIERS[-1][0]} 条。"
    capacity, cost = POND_TIERS[level]
    db.execute("INSERT OR IGNORE INTO fishing_wallets(grp,member) VALUES(?,?)", key)
    paid = db.execute("UPDATE fishing_wallets SET coins=coins-? WHERE grp=? AND member=? AND coins>=?",
                      (cost, *key, cost))
    if not paid.rowcount:
        return shortfall(db,key,cost,prefix,now,"升级鱼塘")
    db.execute("""INSERT INTO fishing_storage_levels(grp,member,storage,level) VALUES(?,?,'pond',?)
                  ON CONFLICT(grp,member,storage) DO UPDATE SET level=excluded.level""",
               (*key, level+1))
    return f"鱼塘已升到 {level+1} 级，可放 {capacity} 条鱼，消耗 {cost} 鱼币。"


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
    return f"已将 #{item} {fish[0]} 放入鱼塘（{count+1}/{capacity} 条）。\n{status}\n{prefix}鱼塘"


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
    return (f"🪙 已卖出 {count} 条鱼\n到账 {total} 枚鱼币，当前余额　{coins} 鱼币。")


def exhibit(db, key, item, prefix, now, batch_rewards=None):
    catch = db.execute("""SELECT fish,grams,price,storage,grade,grade_upgraded FROM fishing_pond
                          WHERE grp=? AND member=? AND id=?""", (*key, item)).fetchone()
    if not catch:
        return False, f"你的鱼包和鱼塘里没有这条鱼。查看可展出的鱼\n{prefix}放入图鉴"
    fish = catch["fish"]
    if fish not in HABITAT:
        return False, "当前图鉴还没有这个鱼种，鱼仍在原处。"
    slot = (*key, fish)
    old = db.execute("SELECT item_id,grams,price,grade,grade_upgraded FROM fishing_exhibits WHERE grp=? AND member=? AND fish=?",
                     slot).fetchone()
    rank = fish_grades.exhibit_rank(fish,catch["grade"],catch["grams"])
    quality = fish_grades.GRADES[rank[0]]
    if old:
        old_rank = fish_grades.exhibit_rank(fish,old["grade"],old["grams"])
        old_quality = fish_grades.GRADES[old_rank[0]]
    if old and rank <= old_rank:
        reason = f"这条是{quality}，品质低于展品。" if rank[0]<old_rank[0] else "同品质只接受更重的鱼。"
        return False, f"📖 图鉴已有{fish} · {old_quality} · {weight(old['grams'])}\n{reason}\n#{item} 仍在{NAMES[catch['storage']]}。"
    if old and catch["storage"] == "pond":
        used, capacity, _ = occupancy(db, key, "bag")
        if used >= capacity:
            return False, f"旧展品需要放回鱼包。请先发「{prefix}查看鱼包」腾出一格，再换入这条鱼。"

    if not old:
        exhibit_rewards.settle(db,key[0],now,True)
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
        rewards = exhibit_rewards.regions(db,key,(HABITAT[fish],),now)
        if batch_rewards is not None:
            batch_rewards.extend(rewards)
        receipt = f"✨ 已点亮　{fish}\n展品 #{item} · {quality} · {weight(catch['grams'])}\n\n展出期间受保护。\n品质优先，同品质选更重的鱼。"
        return True, "\n".join([receipt,*rewards])
    db.execute("""INSERT INTO fishing_pond(grp,member,fish,id,grams,price,grade,grade_upgraded,storage)
                  VALUES(?,?,?,?,?,?,?,?,'bag')""", (*slot, old["item_id"], old["grams"], old["price"], old["grade"], old["grade_upgraded"]))
    return True, (f"✨ 已换入 #{item} {fish} · {quality} · {weight(catch['grams'])}。\n"
            f"原展品 #{old['item_id']} · {old_quality} · {weight(old['grams'])} 已放回鱼包。")


def handle(db, key, cmd, prefix, now=None):
    now = time.time() if now is None else now
    if cmd=="升级鱼包":
        return f"🎒 鱼包固定放 {BAG_CAPACITY} 条。想多留鱼，可以升级鱼塘。\n{prefix}鱼塘操作"
    changes = pond_growth.settle(db,key[0],now,key[1])
    if batch := storage_batch.match(cmd):
        return storage_batch.handle(db, key, batch, prefix, now)
    action = pond_growth.ACTION.fullmatch(cmd)
    if action:
        return pond_growth.act(db,key,action[1],int(action[2]),now,prefix)
    if cmd in CHOOSERS:
        return pond_view.choose(db,key,cmd,prefix,now)
    if cmd=="鱼塘操作":
        return pond_view.actions(db,key,prefix)
    if cmd=="放入图鉴":
        return exhibit_batch.render(db,key,prefix,now)
    if detail:=pond_view.DETAIL.fullmatch(cmd):
        return pond_view.detail(db,key,int(detail[1]),prefix)
    if cmd in ("卖鱼","放入鱼塘"):
        rows=db.execute("""SELECT * FROM fishing_pond WHERE grp=? AND member=?
                           ORDER BY storage='bag' DESC,price,id""",key).fetchall()
        if cmd=="放入鱼塘":
            rows=[r for r in rows if r["storage"]=="bag"]
            used,capacity,_=occupancy(db,key,"pond")
            if rows and used>=capacity:
                return pond_full(used,capacity,prefix)
        if not rows:
            return f"🎒 还没有可选的鱼获编号。先钓一条，鱼获会收入鱼包。\n{cast_step(db,key,prefix,now)}"
        row=rows[0]
        label=f"#{row['id']} {row['fish']}"
        if cmd=="卖鱼":
            detail="🪙 售鱼报价 · 未出售\n"+grid([(f"编号: {row['id']}",row["fish"],f"售价: {row['price']} 鱼币")])[0]+"\n发送即卖出。"
            detail+=breeding_sale_note(db,key,row["id"]) if row["storage"]=="pond" else ""
        else:
            detail=f"🐟 {label} 在鱼包里，发送即可入塘（{used}/{capacity} 条）。"
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
            _,reply=exhibit(db, key, number, prefix, now)
            return reply
        return sell(db, key, "id", number, prefix, now)
    if cmd=="升级鱼塘":
        return upgrade_pond(db,key,prefix,now)
    if cmd in ("卖出鱼包", "一键卖鱼"):
        return sell(db, key, "storage", "bag" if cmd == "卖出鱼包" else "pond", prefix, now)
    raise ValueError("未识别的鱼获指令")
