"""首条亲钓史诗鱼的进度；历史亲钓纪录也算完成。"""
from datetime import datetime
from random import Random

from .db import BJ
from .fishing_waters import WATERS

LIMIT = 50
EPICS = {area: tuple(f for f in school if f[-1] == "史诗") for area,school in WATERS.items()}
STARTERS = ("新手池塘","山涧溪流","近海码头")


def state(db, key):
    row = db.execute("SELECT casts,landed FROM fishing_first_epic WHERE grp=? AND member=?",key).fetchone()
    if row is not None:
        return tuple(row)
    history = db.execute("SELECT fish FROM fishing_species WHERE grp=? AND member=?",key)
    names = {f[0] for school in EPICS.values() for f in school}
    legacy = next((r[0] for r in history if r[0] in names), None)
    return 0, legacy


def begin(db,key,area):
    if not EPICS[area]:
        return 0
    casts, landed = state(db,key)
    if landed:
        return 0
    casts = min(LIMIT, casts+1)
    db.execute("""INSERT INTO fishing_first_epic(grp,member,casts) VALUES(?,?,?)
                  ON CONFLICT(grp,member) DO UPDATE SET casts=excluded.casts""",(*key,casts))
    return casts


def promoted(casts,event_id):
    if casts <= 20:
        return False
    return casts == LIMIT or Random("epic-trail/"+event_id).random() < (casts-20)/100


def status(db,key):
    casts, landed = state(db,key)
    return f"🏅 已亲钓史诗鱼：{landed}" if landed else f"🔮 史诗首获进度 {casts}/{LIMIT} 竿"


def guide(db,key,area,prefix):
    local = "、".join(f[0] for f in EPICS[area])
    lines = [status(db,key),f"📍 {area} · "+(f"可遇 {local}" if local else "这里没有史诗鱼，首获进度暂停"),
             "含史诗的钓场共享进度。第 21 竿起机会增加，第 50 竿必遇史诗；跑鱼后保留进度，满进度持续到入包。",
             "普通装备也能尝试的小型史诗："]
    lines.extend(f"{site} · {EPICS[site][0][0]}" for site in STARTERS)
    target = area if area in STARTERS else STARTERS[0]
    lines.append(prefix+("抛竿" if area==target else "切换钓场 "+target))
    return "\n".join(lines)


def record(db,key,area,now,bite=False,landed=False,cast=False):
    day = datetime.fromtimestamp(now,BJ).date().isoformat()
    db.execute("""INSERT INTO fishing_area_attempts(grp,day,area,casts,epic_bites,epic_landed)
                  VALUES(?,?,?,?,?,?) ON CONFLICT(grp,day,area) DO UPDATE SET
                  casts=casts+excluded.casts,epic_bites=epic_bites+excluded.epic_bites,
                  epic_landed=epic_landed+excluded.epic_landed""",(key[0],day,area,cast,bite,landed))
