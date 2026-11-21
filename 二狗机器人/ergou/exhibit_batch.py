"""同一消息事务内选择展品、分配换展位置，再按计划移动鱼获。"""
import re

from .fishing_waters import HABITAT
from .fish_receipts import grid, mass

LIMIT = 10
NUMBER = r"[1-9][0-9]{0,17}"
VERB = re.compile(r"(批量点亮图鉴|点亮图鉴|收入图鉴|放入图鉴)\s*(.*)", re.S)
WIDTH = str.maketrans("＃０１２３４５６７８９，；　", "#0123456789,; ")
TOKEN = re.compile(rf"(?:(?:编号|序号)\s*(?:为\s*)?)?(?:#\s*)?({NUMBER})(?![0-9])")
SEPARATOR = re.compile(r"[\s,、;]+|(?=#)")


def parse(text):
    match = VERB.fullmatch(text.strip().translate(WIDTH))
    if not match or not match[2]:
        return None
    value = match[2]
    if re.fullmatch("#"+NUMBER,value) and match[1]!="批量点亮图鉴":
        return None  # 已有的显式单鱼指令沿用原路由。
    if not re.match(r"[#0-9]|编号|序号",value):
        return None
    return parse_numbers(value)


def parse_numbers(value):
    numbers={}
    pos=0
    while True:
        token=TOKEN.match(value,pos)
        if not token:
            return ()
        numbers[int(token[1])]=None
        if token.end()==len(value):
            return tuple(numbers)
        separator=SEPARATOR.match(value,token.end())
        if not separator:
            return ()
        pos=separator.end()



def plan(db, key, ids=None):
    from .fish_storage import occupancy
    rows = db.execute("""SELECT p.id,p.fish,p.grams,p.storage,e.grams AS old,e.item_id AS old_id
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
    alternates = {}
    for row in rows:
        item,fish,grams,storage,old,_ = row
        if item in parents:
            skipped[item]="亲鱼正在配对"
        elif fish not in HABITAT:
            skipped[item]="图鉴未收录"
        elif old is not None and grams<=old:
            skipped[item]="未超过现有展品重量"
        elif fish in species:
            skipped[item]="同种只展一尾，已优先选可展出的最重鱼"
            if storage=="bag":
                alternates.setdefault(fish,row)
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
            alternate=alternates.get(row["fish"])
            if alternate is not None:
                selected.append(alternate)
                del skipped[alternate["id"]]
        else:
            used+=change
            selected.append(row)
    return selected,skipped


def render(db,key,prefix,now,ids=None):
    from .fish_storage import exhibit
    if ids==():
        return f"请逐个填写编号，例如：{prefix}点亮图鉴 编号98、99、100"
    if ids is not None and len(ids)>LIMIT:
        return f"一次最多选 {LIMIT} 个不同鱼号，本次未移动。\n{prefix}放入图鉴"
    selected,skipped=plan(db,key,ids)
    preview=ids is None
    if preview and not selected:
        reason=next(iter(skipped.values()), "鱼包和鱼塘里还没有鱼")
        return f"📖 暂无可展出的鱼 · {reason}\n{prefix}鱼塘" if skipped else f"📖 鱼包和鱼塘里还没有鱼\n{prefix}查看鱼包"
    batch=selected[:LIMIT]
    report=[]
    first=[]
    swaps=[]
    rewards=[]
    for row in batch:
        if not preview:
            moved,reason=exhibit(db,key,row["id"],prefix,now,rewards)
            if not moved:
                skipped[row["id"]]=reason
                continue
        report.append(row)
    report.sort(key=lambda r:r["id"],reverse=True)
    for row in report:
        cells=(f"编号: {row['id']}",row["fish"],mass(row["grams"]))
        if row["old"] is None:
            first.append(cells)
        else:
            swaps.append((*cells, f"回包: {row['old_id']}"))
    if preview:
        lines=["📖 图鉴展出预览",f"可展出 {len(selected)} 种，本次已选 {len(batch)} 种"]
    else:
        lit=db.execute("SELECT count(*) FROM fishing_exhibits WHERE grp=? AND member=?",key).fetchone()[0]
        outcomes=[]
        if first:
            outcomes.append(f"已点亮 {len(first)} 种")
        if swaps:
            outcomes.append(f"换展 {len(swaps)} 种")
        lines=["📖 "+(" · ".join(outcomes) or "本次没有移动鱼获"),f"本群图鉴 {lit}/{len(HABITAT)}"]
    for title,rows in (("✨ 首次点亮",first),("🔄 换展 · 旧展品回包",swaps)):
        if rows:
            lines.extend(["",title,*grid(rows)])
    if not preview and skipped:
        lines.extend(["","↪ 跳过",*grid((f"编号: {i}",skipped[i]) for i in sorted(skipped))])
    if preview:
        if len(selected)>LIMIT:
            lines.append(f"还有 {len(selected)-LIMIT} 种可在下一批展出。")
        action="展出" if swaps else "点亮"
        numbers="、".join(str(row["id"]) for row in report)
        lines.extend(["",f"👇 发送这句，{action}这 {len(batch)} 种鱼",f"{prefix}点亮图鉴 编号{numbers}"])
    else:
        lines.extend([*rewards,"","查看收藏",prefix+"图鉴"])
    return "\n".join(lines)
