"""按北京时间轮换的限时鱼群，每位钓手每窗可收获一尾活动鱼。"""
from datetime import datetime, timedelta
from random import Random

from .db import BJ
from .fishing_waters import WATERS, giant_min

AREAS = tuple(area for area,school in WATERS.items()
              if {"传说","史诗"} <= {fish[-1] for fish in school})
EPIC_PER_THOUSAND = 30
LEGEND_PER_THOUSAND = 6


def assisted_load(grams):
    """活动遛鱼协助只影响装备拉力，实物重量照常入库。"""
    return min(15000, (grams+9)//10)


def area_at(local):
    slot = local.date().toordinal()*8 + local.hour//3
    return AREAS[slot % len(AREAS)]


def claimed(db,key,hour):
    return db.execute("SELECT 1 FROM fishing_hotspot_catch WHERE grp=? AND member=? AND hour>=?",
                      (*key,hour)).fetchone() is not None


def guide(db,key,area,now,prefix):
    local = datetime.fromtimestamp(now,BJ)
    hour = local.replace(minute=0,second=0,microsecond=0)
    start = hour if local.minute<20 else hour+timedelta(hours=1)
    site = area_at(start)
    fishes = [f"{fish[-1]} · {fish[0]}" for fish in WATERS[site] if fish[-1] in ("史诗","传说")]
    label = "开放中" if start==hour else "已关闭，下次开放"
    end = start+timedelta(minutes=20)
    lines = [f"🌊 传说热点 · {label}", f"{site}｜北京时间 {start:%m-%d %H:%M}～{end:%H:%M}",
             *fishes, "常规抛竿未遇史诗、传说或巨物活动时，另有 3% 转为史诗鱼、0.6% 转为传说鱼。每人每窗最多收获一尾活动鱼，跑鱼可再试。",
             "钓场协助遛鱼：活动鱼按实重一成拉扯装备，最多 15 公斤。请留意竿线耐久。"]
    if start==hour and claimed(db,key,int(start.timestamp())):
        lines.append("你本场的活动鱼已入包，还可正常抛竿。")
    if area!=site:
        lines.append(prefix+"切换钓场 "+site)
    elif start==hour:
        lines.append(prefix+"抛竿")
    else:
        lines.append("你已在下场热点，开窗后可直接抛竿。")
    return "\n".join(lines)


def encounter(db,key,area,now,event_id,bait):
    local = datetime.fromtimestamp(now,BJ)
    if local.minute>=20 or area!=area_at(local):
        return None
    hour = int(local.replace(minute=0,second=0,microsecond=0).timestamp())
    if claimed(db,key,hour):
        return None
    rng = Random("hotspot/"+event_id)
    roll = rng.randrange(1000)
    if roll >= LEGEND_PER_THOUSAND+EPIC_PER_THOUSAND:
        return None
    rarity = "传说" if roll<LEGEND_PER_THOUSAND else "史诗"
    fish = rng.choice([f for f in WATERS[area] if f[-1]==rarity])
    low,high = fish[1],giant_min(fish)-1
    grams = round(rng.triangular(low, high, low+(high-low)*bait.weight_mode))
    return hour,fish,grams


def land(db,key,hour):
    db.execute("""INSERT INTO fishing_hotspot_catch(grp,member,hour) VALUES(?,?,?)
                  ON CONFLICT(grp,member) DO UPDATE SET hour=max(hour,excluded.hour)""",(*key,hour))
