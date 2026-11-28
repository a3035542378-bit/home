"""图鉴榜按展出的物种计数，与单尾品级和亲钓纪录独立。"""
from .exhibit_batch import candidates
from .fish_receipts import grid
from .display_names import labels
from .exhibit_rewards import PRIZES
from .fishing_waters import SPECIES


def ranked(db, group):
    rare = [fish for fish, species in SPECIES.items() if species[-1] in ("史诗","传说")]
    fields = ",".join("?" for _ in rare)
    return db.execute(f"""WITH counts AS (
        SELECT member,count(*) lit,sum(fish IN ({fields})) rare FROM fishing_exhibits
        WHERE grp=? GROUP BY member)
        SELECT *,rank() OVER(ORDER BY lit DESC,rare DESC) place FROM counts
        ORDER BY place,member""",(*rare,group))


def board(db,key,prefix):
    names = labels(db,key[0])
    lines = ["📖 本群图鉴榜","已点亮鱼种 · 其中史诗与传说鱼种",""]
    entries=[]
    personal_slot = None
    mine = "你还未点亮图鉴。"
    for index,row in enumerate(ranked(db,key[0])):
        if index < 10:
            name=names(row['member'],'你' if row['member']==key[1] else None)
            entries.append((f"第 {row['place']} 名",name,f"{row['lit']} 种",f"{row['rare']} 种"))
        if row["member"] == key[1]:
            personal_slot = index if index < len(PRIZES) else None
            mine = f"你排第 {row['place']}，已点亮 {row['lit']} 种。"
    unlit = {}
    for fish in candidates(db,key):
        if fish["storage"]=="bag" and fish["old"] is None and fish["fish"] in SPECIES:
            unlit.setdefault(fish["fish"],fish["id"])
    ids = sorted(unlit.values())
    lines.extend([*grid(entries),"",mine,"北京时间零点结算，前十席积分依次为",
                  "、".join(map(str,PRIZES))+"。并列按榜上展示顺序分配。"])
    if personal_slot is not None:
        lines.append(f"按当前顺序，你占第 {personal_slot+1} 席，预计 +{PRIZES[personal_slot]} 分。")
    last=db.execute("""SELECT reason,points FROM ledger WHERE grp=? AND member=? AND kind='图鉴日榜'
                        ORDER BY id DESC LIMIT 1""",key).fetchone()
    if last:
        lines.append(f"最近到账：{last['reason']}，+{last['points']} 分。")
    lines.append(f"🎒 你的鱼包里还有 {len(ids)} 种未点亮。")
    if ids:
        lines.extend(["✨ 点亮其中一种",f"{prefix}收入图鉴#{ids[0]}"])
    from .fishing_cards import sheet
    return sheet("\n".join(lines),prefix,"钓鱼排行榜","本群图鉴榜","已点亮鱼种  /  史诗与传说鱼种",
                 entries=[(place+"  "+name,f"已点亮 {count}  ·  史诗与传说 {rare}") for place,name,count,rare in entries],
                 lines=lines[3+len(entries):])
