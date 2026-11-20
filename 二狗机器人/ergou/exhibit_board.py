"""图鉴榜按展出的物种计数，与单尾品级和亲钓纪录独立。"""
from .display_names import labels
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
    mine = "你还未点亮图鉴。"
    for index,row in enumerate(ranked(db,key[0])):
        if index < 10:
            lines.append(f"{row['place']}. {names(row['member'],'你' if row['member']==key[1] else None)}　{row['lit']} 种 · {row['rare']} 种")
        if row["member"] == key[1]:
            mine = f"你排第 {row['place']}，已点亮 {row['lit']} 种。"
    candidates = db.execute("""SELECT p.fish,min(p.id) id FROM fishing_pond p
        WHERE p.grp=? AND p.member=? AND p.storage='bag' AND NOT EXISTS
        (SELECT 1 FROM fishing_exhibits e WHERE e.grp=p.grp AND e.member=p.member AND e.fish=p.fish)
        GROUP BY p.fish ORDER BY id""",key)
    ids = [r["id"] for r in candidates if r["fish"] in SPECIES]
    lines.extend(["",mine,f"🎒 你的鱼包里还有 {len(ids)} 种未点亮。"])
    if ids:
        lines.append(f"✨ {prefix}收入图鉴#{ids[0]}")
    return "\n".join(lines)
