"""鱼塘列表、单鱼详情及本人的可执行操作。"""
import re

from . import breeding, fish_grades, pond_growth
from .fishing_waters import SPECIES

DETAIL = re.compile(r"查看鱼\s*[#＃]([1-9][0-9]{0,17})")
STOCK = """SELECT p.*,coalesce(g.original_grams,p.grams) original_grams,
    coalesce(g.original_price,p.price) original_price,coalesce(g.rounds,0) rounds,
    coalesce(g.appearance,0) appearance,g.next_at,coalesce(g.food,0) food,
    coalesce(g.flagship,0) flagship,f.adult,f.breeder,f.firstborn,w.coins,e.grams shown
    FROM fishing_pond p LEFT JOIN pond_growth g ON g.item=p.id
    LEFT JOIN breed_fry f ON f.item=p.id JOIN fishing_wallets w USING(grp,member)
    LEFT JOIN fishing_exhibits e USING(grp,member,fish) WHERE p.grp=? AND p.member=?"""


def mass(grams):
    if grams>=1_000_000:
        return f"{grams/1_000_000:.3f} 吨"
    return f"{grams/1000:.3f} 公斤" if grams>=1000 else f"{grams} 克"


def limit(row):
    return row["adult"] or pond_growth.cap(row["fish"],row["original_grams"])


def finished(row):
    return row["grade"] is None or row["rounds"]>=pond_growth.ROUNDS or row["grams"]>=limit(row)


def feed(row):
    if finished(row) or row["adult"] or row["food"] or row["next_at"] is None:
        return None
    return (min(pond_growth.FEED_ROUNDS,pond_growth.ROUNDS-row["rounds"]),
            pond_growth.feed_cost(row["original_price"],row["rounds"]))


def title(row):
    grade = fish_grades.label(row["grade"],row["grade_upgraded"]) or "品级未记录"
    return f"#{row['id']} {row['fish']} · {grade}"


def card(row, prefix, gain):
    price=f"现价 {row['price']} 鱼币"
    if finished(row):
        lines=[f"🏁 {title(row)} · 已定型",f"{mass(row['grams'])}｜{price}"]
    else:
        state="成长" if row["next_at"] is not None else "暂停"
        lines=[f"🌱 {title(row)}",f"{mass(row['grams'])} → 上限 {mass(limit(row))}",
               f"{state} {row['rounds']}/{pond_growth.ROUNDS} 轮｜{price}"]
    if row["adult"]:
        lines.append("🐣 "+breeding.source(row,row["member"]))
    elif not finished(row) and row["food"]:
        lines.append(f"🍤 饲料还够 {row['food']} 轮")
    elif (meal:=feed(row)) and row["coins"]>=meal[1]:
        lines[-1]+=f"｜喂 {meal[0]} 轮 {meal[1]} 币"
        lines.append(f"{prefix}投喂#{row['id']}")
    if gain:
        lines[0]+=f" · 这次长了 {mass(gain)}"
    return lines


def home(db,key,page,by_weight,prefix,changes,now):
    from .fish_storage import occupancy, cast_step
    used,capacity,level=occupancy(db,key,"pond")
    pending=breeding.banner(breeding.state(db,key),prefix) if breeding.enabled(db,key[0]) else ""
    if not used and not pending:
        bag=db.execute("SELECT id,fish FROM fishing_pond WHERE grp=? AND member=? AND storage='bag' ORDER BY id DESC LIMIT 1",key).fetchone()
        if bag:
            return f"🐟 鱼塘是空的。把鱼包里的 #{bag[0]} {bag[1]} 放进来吧。\n{prefix}放入鱼塘#{bag[0]}"
        return f"🐟 鱼塘是空的。先钓一条，再从鱼包放入鱼塘。\n{cast_step(db,key,prefix,now)}"
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
    for row in db.execute(STOCK+f" AND p.storage='pond' ORDER BY {order} LIMIT 2 OFFSET ?",(*key,2*(page-1))):
        lines.extend(["",*card(row,prefix,changes.get(row["id"],(0,))[0])])
    if pages>1:
        target=page+1 if page<pages else page-1
        direction="下一页" if page<pages else "上一页"
        lines.extend(["",f"第 {page}/{pages} 页 · {direction}",f"{base} {target}"])
    lines.extend(["","看单鱼、出售或扩容",prefix+"鱼塘帮助"])
    return "\n".join(lines)


def detail(db,key,item,prefix):
    from .fish_storage import occupancy,breeding_sale_note
    row=db.execute(STOCK+" AND p.id=?",(*key,item)).fetchone()
    if not row:
        return f"你的本群鱼塘和鱼包里没有这条鱼。\n{prefix}鱼塘"
    pond=row["storage"]=="pond"
    lines=[f"🐟 {title(row)} · {'鱼塘' if pond else '鱼包'}",
           f"原重 {mass(row['original_grams'])} → 现重 {mass(row['grams'])}",
           f"上限 {mass(limit(row))}｜品相加价 {row['appearance']}%",
           f"原价 {row['original_price']} → 现价 {row['price']} 鱼币"]
    if row["adult"]:
        lines.append("🐣 "+breeding.source(row,key[1]))
    if finished(row):
        lines.append("🏁 已定型")
    if (meal:=feed(row)) and row["coins"]>=meal[1]:
        lines.extend([f"投喂 {meal[0]} 轮 · 扣 {meal[1]} 鱼币",f"{prefix}投喂#{item}"])
    if pond and not finished(row) and row["next_at"] is None:
        lines.extend(["恢复成长（位满时替换一尾）",f"{prefix}换入成长位#{item}"])
    if pond and not row["flagship"]:
        lines.extend(["设为招牌鱼，免于被偷",f"{prefix}设为招牌鱼#{item}"])
    if not pond:
        used,cap,_=occupancy(db,key,"pond")
        if used<cap:
            lines.extend(["移入鱼塘",f"{prefix}放入鱼塘#{item}"])
    note=breeding_sale_note(db,key,item) if pond else ""
    used,cap,_=occupancy(db,key,"bag")
    if not note and row["fish"] in SPECIES and (row["shown"] is None or
            (row["grams"]>row["shown"] and (not pond or used<cap))):
        lines.extend(["展入图鉴，换下的鱼回包",f"{prefix}放入图鉴#{item}"])
    lines.extend([f"立即出售 · {row['price']} 鱼币。{note}",f"{prefix}卖鱼#{item}"])
    return "\n".join(lines)
