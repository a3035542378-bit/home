"""同一消息事务内选择展品、分配换展位置，再按计划移动鱼获。"""
import re

from .fishing_waters import HABITAT

LIMIT = 10
NUMBER = r"#[1-9][0-9]{0,17}"
BATCH = re.compile(rf"(批量点亮图鉴|点亮图鉴|收入图鉴|放入图鉴)\s*({NUMBER}(?:(?:\s*[,、]\s*|\s+){NUMBER})*)")
WIDTH = str.maketrans("＃０１２３４５６７８９，　", "#0123456789, ")


def parse(text):
    match = BATCH.fullmatch(text.strip().translate(WIDTH))
    if not match:
        return None
    numbers = re.findall(NUMBER, match[2])
    if len(numbers)==1 and match[1]!="批量点亮图鉴":
        return None
    return tuple(dict.fromkeys(int(num[1:]) for num in numbers))


def plan(db, key, ids=None):
    from .fish_storage import occupancy
    rows = db.execute("""SELECT p.id,p.fish,p.grams,p.storage,e.grams AS old
                         FROM fishing_pond p LEFT JOIN fishing_exhibits e USING(grp,member,fish)
                         WHERE p.grp=? AND p.member=?
                         ORDER BY p.grams DESC,p.storage='bag' DESC,p.id""",key).fetchall()
    pair = db.execute("SELECT p1,p2 FROM breed_pairs WHERE grp=? AND member=? AND state='active'",key).fetchone()
    parents = set(pair or ())
    skipped = {}
    if ids is not None:
        known = {r["id"] for r in rows}
        skipped.update((i,"不在你的本群鱼包或鱼塘") for i in ids if i not in known)
        rows = [r for r in rows if r["id"] in ids]
    species = {}
    for row in rows:
        item,fish,grams,storage,old = row
        if item in parents:
            skipped[item]="亲鱼正在配对"
        elif fish not in HABITAT:
            skipped[item]="图鉴未收录"
        elif old is not None and grams<=old:
            skipped[item]="未超过现有展品重量"
        elif fish in species:
            skipped[item]="同种只展一尾，已优先选最重的鱼"
        else:
            species[fish]=row
    def delta(row):
        return int(row["old"] is not None)-int(row["storage"]=="bag")
    used,capacity,_=occupancy(db,key,"bag")
    selected=[]
    for row in sorted(species.values(),key=lambda r:(delta(r),-r["id"])):
        change=delta(row)
        if change>0 and used+change>capacity:
            skipped[row["id"]]="鱼包没有空位接回旧展品"
        else:
            used+=change
            selected.append(row)
    return selected,skipped


def render(db,key,prefix,now,ids=None):
    from .fish_storage import exhibit
    from .pond_view import mass
    if ids is not None and len(ids)>LIMIT:
        return f"一次最多选 {LIMIT} 个不同鱼号。查看可展出的鱼\n{prefix}放入图鉴"
    selected,skipped=plan(db,key,ids)
    if ids is None:
        if not selected:
            reason=next(iter(skipped.values()), "鱼包和鱼塘里还没有鱼")
            return f"📖 暂无可点亮或换展的鱼 · {reason}\n{prefix}全图鉴"
        batch=selected[:LIMIT]
        lines=[f"📖 可展出 {len(selected)} 种 · 本次选 {len(batch)} 种"]
        for row in batch:
            action="换展" if row["old"] is not None else "点亮"
            lines.append(f"#{row['id']} {row['fish']}　{mass(row['grams'])} · {action}")
        if len(selected)>LIMIT:
            lines.append(f"还有 {len(selected)-LIMIT} 种，完成后发「{prefix}放入图鉴」看下一批。")
        verb="点亮图鉴" if len(batch)>1 else "批量点亮图鉴"
        return "\n".join([*lines,"发送即展出，换下的鱼回包",prefix+verb+" ".join(f"#{r['id']}" for r in batch)])
    lines=[]
    new=swaps=0
    for row in selected:
        moved,reason=exhibit(db,key,row["id"],prefix,now)
        if not moved:
            skipped[row["id"]]=reason
            continue
        if row["old"] is None:
            new+=1
        else:
            swaps+=1
        suffix=" · 换展，原展品已回包" if row["old"] is not None else ""
        lines.append(f"✨ #{row['id']} {row['fish']}{suffix}")
    lit=db.execute("SELECT count(*) FROM fishing_exhibits WHERE grp=? AND member=?",key).fetchone()[0]
    heading=f"📖 已点亮 {new} 种"
    if swaps:
        heading+=f" · 换展 {swaps} 种"
    lines.extend(f"↪ #{i} 跳过 · {skipped[i]}" for i in sorted(skipped))
    return "\n".join([f"{heading} · 本群图鉴 {lit}/{len(HABITAT)}",*lines,"查看收藏",prefix+"图鉴"])
