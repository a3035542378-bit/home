"""鱼塘列表、单鱼详情及本人的可执行操作。"""
import re

from . import breeding, fish_grades, pond_growth
from .fish_receipts import grid, mass, single
from .fishing_waters import SPECIES, size_grade

DETAIL = re.compile(r"查看鱼\s*[#＃]([1-9][0-9]{0,17})")
STOCK = """SELECT p.*,coalesce(g.original_grams,p.grams) original_grams,
    coalesce(g.original_price,p.price) original_price,coalesce(g.rounds,0) rounds,
    coalesce(g.appearance,0) appearance,g.next_at,coalesce(g.food,0) food,
    coalesce(g.flagship,0) flagship,f.adult,f.breeder,f.firstborn,w.coins,e.grams shown,e.grade shown_grade,e.item_id old_id
    FROM fishing_pond p LEFT JOIN pond_growth g ON g.item=p.id
    LEFT JOIN breed_fry f ON f.item=p.id JOIN fishing_wallets w USING(grp,member)
    LEFT JOIN fishing_exhibits e USING(grp,member,fish) WHERE p.grp=? AND p.member=?"""


def limit(row):
    return row["adult"] or pond_growth.cap(row["fish"],row["original_grams"])


def finished(row):
    return row["grade"] is None or row["rounds"]>=pond_growth.ROUNDS or row["grams"]>=limit(row)


def feed(row):
    if finished(row) or row["adult"] or row["food"] or row["next_at"] is None:
        return None
    return (min(pond_growth.FEED_ROUNDS,pond_growth.ROUNDS-row["rounds"]),
            pond_growth.feed_cost(row["original_price"],row["rounds"]))


def quality(row):
    return fish_grades.label(row["grade"],row["grade_upgraded"]) or "未记录"


def home(db,key,page,by_weight,prefix,changes,now):
    from .fish_storage import occupancy, cast_step
    used,capacity,level=occupancy(db,key,"pond")
    pending=breeding.banner(breeding.state(db,key),prefix,used>=capacity) if breeding.enabled(db,key[0]) else ""
    if not used and not pending:
        bag=db.execute("SELECT id,fish FROM fishing_pond WHERE grp=? AND member=? AND storage='bag' ORDER BY id DESC LIMIT 1",key).fetchone()
        if bag:
            return f"🐟 鱼塘是空的（0/{capacity} 条）。把鱼包里的 #{bag[0]} {bag[1]} 放进来吧。\n{prefix}放入鱼塘#{bag[0]}"
        return f"🐟 鱼塘是空的（0/{capacity} 条）。先钓一条，再从鱼包放入鱼塘。\n{cast_step(db,key,prefix,now)}"
    pages=max(1,(used+1)//2)
    base=prefix+"鱼塘"+(" 重量" if by_weight else "")
    if page>pages:
        return f"鱼塘只有 {pages} 页。\n{base} {pages}"
    active=db.execute(pond_growth.SELECT+" AND p.member=? AND g.next_at IS NOT NULL",key).fetchall()
    state="已满" if used>=capacity else "容量"
    lines=[f"🐟 我的鱼塘 · {level}级",f"{state} {used}/{capacity} 条｜成长位 {len(active)}/{pond_growth.SLOTS[level-1]}"]
    if used>capacity:
        lines.append("原有鱼获已保留，腾位后可继续存鱼。")
    if pending:
        lines.extend([pending.replace("发送 ","")])
    order="p.grams DESC,p.id DESC" if by_weight else "p.id DESC"
    rows=db.execute(STOCK+f" AND p.storage='pond' ORDER BY {order} LIMIT 2 OFFSET ?",(*key,2*(page-1))).fetchall()
    lines.extend(["",*grid((f"编号: {r['id']}",r["fish"],mass(r["grams"]),f"{r['price']} 鱼币",
                             "已定型" if finished(r) else "在养" if r["next_at"] else "暂停") for r in rows)])
    for r in rows:
        item=r["id"]
        if r["adult"]:
            lines.append(f"🐣 编号 {item} · "+breeding.source(r,key[1]))
        if not finished(r) and r["next_at"]:
            gain=changes.get(item,(0,))[0]
            lines.extend(["",f"🌱 编号 {item} · 成长 {r['rounds']}/{pond_growth.ROUNDS} 轮 · 上限 {mass(limit(r))}"])
            if gain:
                lines.append("这次长了 "+mass(gain))
            if r["food"]:
                lines.append(f"饲料还够 {r['food']} 轮")
            elif (meal:=feed(r)) and r["coins"]>=meal[1]:
                lines.append(f"【投喂#{item}】喂 {meal[0]} 轮，扣 {meal[1]} 币")
    if pages>1:
        target=page+1 if page<pages else page-1
        direction="下一页" if page<pages else "上一页"
        lines.extend(["",f"【{base.removeprefix(prefix)} {target}】{direction}（{page}/{pages}）"])
    if used > 1:
        lines.extend(["【批量投喂】喂多条鱼", "【批量收回鱼包】移出塘鱼", "【批量卖出塘鱼】按编号出售"])
    lines.extend(["","【鱼塘操作】看单鱼、出售或扩容"])
    return "\n".join(lines)


def detail(db,key,item,prefix):
    from .fish_storage import occupancy,breeding_sale_note
    row=db.execute(STOCK+" AND p.id=?",(*key,item)).fetchone()
    if not row:
        return f"你的本群鱼塘和鱼包里没有这条鱼。\n{prefix}鱼塘"
    pond=row["storage"]=="pond"
    lines=[f"🐟 单鱼详情 · {'鱼塘' if pond else '鱼包'}",
           *single(item,row["fish"],quality(row),size_grade(row["fish"],row["grams"]),row["grams"],row["price"]),
           f"原重 {mass(row['original_grams'])} → 现重 {mass(row['grams'])}",
           f"上限 {mass(limit(row))}｜品相加价 {row['appearance']}%",
           f"原价 {row['original_price']} → 现价 {row['price']} 鱼币"]
    if row["adult"]:
        lines.append("🐣 "+breeding.source(row,key[1]))
    if finished(row):
        lines.append("🏁 已定型")
    if (meal:=feed(row)) and row["coins"]>=meal[1]:
        lines.append(f"【投喂#{item}】喂 {meal[0]} 轮，扣 {meal[1]} 鱼币")
    if pond and not finished(row) and row["next_at"] is None:
        lines.append(f"【换入成长位#{item}】"+pond_growth.slot_hint(db,key,item))
    if pond and not row["flagship"]:
        lines.append(f"【设为招牌鱼#{item}】保护这条鱼免偷")
    if not pond:
        used,cap,_=occupancy(db,key,"pond")
        if used<cap:
            lines.append(f"【放入鱼塘#{item}】移入鱼塘")
    note=breeding_sale_note(db,key,item) if pond else ""
    used,cap,_=occupancy(db,key,"bag")
    if not note and row["fish"] in SPECIES and (row["shown"] is None or
            (fish_grades.exhibit_rank(row["fish"],row["grade"],row["grams"]) >
             fish_grades.exhibit_rank(row["fish"],row["shown_grade"],row["shown"]) and (not pond or used<cap))):
        effect=f"换展，编号 {row['old_id']} 回包" if row["shown"] is not None else "首次点亮"
        lines.append(f"【放入图鉴#{item}】{effect}")
    lines.append(f"【卖鱼#{item}】立即出售，到账 {row['price']} 鱼币。{note}")
    return "\n".join(lines)


def actions(db,key,prefix):
    from . import fish_storage
    count,_,level=fish_storage.occupancy(db,key,"pond")
    lines=["🌱 管理塘鱼","【鱼塘】看塘和投喂费用"]
    rows=db.execute(STOCK+" AND p.storage='pond' ORDER BY p.id DESC",key).fetchall()
    if rows:
        row=rows[0]
        i=row["id"]
        lines.append(f"【查看鱼#{i}】看单鱼详情和操作")
        if any(not r["flagship"] for r in rows):
            target=next(r["id"] for r in rows if not r["flagship"])
            lines.append(f"【设为招牌鱼#{target}】免偷")
        paused=next((r for r in rows if r["next_at"] is None and not finished(r)),None)
        if paused:
            lines.append(f"【换入成长位#{paused['id']}】"+pond_growth.slot_hint(db,key,paused["id"]))
        lines.append("【卖鱼】选一尾，免费查报价")
    else:
        lines.append("【放入鱼塘】选鱼放进第一格")
    if level<len(fish_storage.POND_TIERS):
        capacity,cost=fish_storage.POND_TIERS[level]
        coins=db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()
        if (coins[0] if coins else 30)>=cost:
            lines.append(f"【升级鱼塘】扣 {cost} 鱼币，扩到 {capacity} 条")
        else:
            lines.append(f"扩到 {capacity} 条需 {cost} 鱼币，还差 {cost-(coins[0] if coins else 30)} 鱼币。")
    if rows:
        total=sum(r["price"] for r in rows)
        lines.extend(["【批量卖出塘鱼】选鱼出售", "【批量收回鱼包】按鱼号移回", "【批量投喂】查看饲料费"])
        warning=fish_storage.breeding_sale_note(db,key)
        lines.extend(["","⚠ 整塘出售",f"【一键卖鱼】清空 {count} 条，共 {total} 鱼币"])
        if warning:
            lines.append(warning)
    return "\n".join(["🐟 我的鱼塘操作",*lines])


def choose(db,key,cmd,prefix,now):
    from . import fish_storage
    rows=db.execute(STOCK+" ORDER BY p.storage='pond' DESC,p.id DESC",key).fetchall()
    if not rows:
        return f"还没有鱼，先钓第一条。\n{fish_storage.cast_step(db,key,prefix,now)}"
    if cmd=="查看鱼":
        row=rows[0]
        return f"免费查看 #{row['id']} {row['fish']} 的详情\n{prefix}查看鱼#{row['id']}"
    pond=[r for r in rows if r["storage"]=="pond"]
    if not pond:
        return f"鱼还在包里，先挑一条放进塘。\n{prefix}放入鱼塘"
    if cmd=="投喂":
        hungry=[(feed(r)[1],r["id"],r) for r in pond if feed(r)]
        if hungry:
            cost,item,row=min(hungry)
            if cost>row["coins"]:
                return fish_storage.shortfall(db,key,cost,prefix,now,"投喂")
            return f"给 #{item} {row['fish']} 投喂，发送即扣 {cost} 鱼币\n{prefix}投喂#{item}"
        return f"目前没有需要投喂的鱼。查看成长位和饲料\n{prefix}鱼塘"
    if cmd=="设为招牌鱼":
        target=next((r for r in pond if not r["flagship"]),None)
        label="改由这条鱼当招牌，免于被偷"
    else:
        target=next((r for r in pond if not finished(r) and r["next_at"] is None),None)
        label=pond_growth.slot_hint(db,key,target["id"]) if target else ""
    if target:
        return f"{label}\n#{target['id']} {target['fish']}\n{prefix}{cmd}#{target['id']}"
    return f"当前没有需要更换的塘鱼，查看塘况\n{prefix}鱼塘"
