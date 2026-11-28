"""群内同一钓场共享鱼讯，按整点生成，不依赖定时消息或进程内状态。"""
import math
from datetime import datetime
from random import Random
from typing import NamedTuple

from . import fishing_bait, rod
from .db import BJ
from .fishing_waters import SPECIES, WATERS, giant_max, giant_min

LEAD = 600
DURATION = 20 * 60
CARP_PER_THOUSAND = 1
ACTIVE_PER_THOUSAND = 20
WARNING = "⚠️ 新手塘也可能断线、折竿，请谨慎抛竿。"


def starter_hint(area, prefix=None):
    if area != "新手池塘":
        return ""
    hint = "\n" + WARNING
    if prefix is not None:
        hint += f"\n下竿\n{prefix}抛竿"
    return hint


class Sighting(NamedTuple):
    fish: str
    start: int
    taken: bool = False

    def active(self, now):
        return not self.taken and self.start <= now < self.start + DURATION

    def notice(self, now, area, *, prefix=None):
        if self.active(now):
            seconds = math.ceil(self.start + DURATION - now)
            timing = f"🌊 巨物{self.fish}正在出没\n剩 {seconds//60} 分 {seconds%60} 秒，钓走即消失。"
        else:
            clock = datetime.fromtimestamp(self.start, BJ).strftime("%H:%M")
            minutes = math.ceil((self.start - now) / 60)
            timing = f"🌊 巨物{self.fish}还有 {minutes} 分钟出没\n北京时间 {clock} 开始，只停留 {DURATION//60} 分钟。"
        return timing + f"\n活动咬钩率 {ACTIVE_PER_THOUSAND/10:g}%，先钓走先得。" + starter_hint(area, prefix)


def scheduled(group, area, hour):
    rng = Random(f"giants/v1:{group}:{area}:{hour}")
    start = hour * 3600 + rng.randint(10, 50) * 60
    school = WATERS[area]
    # 群共享目标按基础竿、免费饵的稀有度分布选种，同档鱼种机会相同。
    tier = fishing_bait.choose_rarity(rng, school, rod.weights(1, ()), fishing_bait.BAITS["免费鱼饵"],rod.trophy_bonus(1, ()))
    fish = rng.choice([row[0] for row in school if row[-1] == tier])
    return Sighting(fish, start)


def window(group, area, now):
    # 前一小时最晚在第 50 分钟开始，过整点后可能仍在场。
    hour = int(now) // 3600
    if now < (hour-1)*3600 + 50*60 + DURATION:
        previous = scheduled(group, area, hour-1)
        if previous.active(now):
            return previous
    event = scheduled(group, area, hour)
    if now < event.start + DURATION:
        return event
    return scheduled(group, area, hour+1)


def current(db, group, area, now):
    sighting = window(group, area, now)
    taken = db.execute("""SELECT 1 FROM fishing_giant_claims
                          WHERE grp=? AND area=? AND start=?""",(group,area,sighting.start)).fetchone()
    return sighting._replace(taken=bool(taken))


def departure(group, area, sighting):
    upcoming = window(group, area, sighting.start + DURATION)
    clock = datetime.fromtimestamp(upcoming.start, BJ).strftime("%H:%M")
    return f"🏁 本轮巨物已被钓走。\n下次随机出没　{clock}（北京时间）" + starter_hint(area)


def encounter(sighting, area, now, event_id):
    if sighting.taken:
        return None
    active = sighting.active(now)
    chance = CARP_PER_THOUSAND if area == "新手池塘" else 0
    if active:
        chance = ACTIVE_PER_THOUSAND
    rng = Random("giant-bite:" + event_id)
    if rng.randrange(1000) >= chance:
        return None
    fish = sighting.fish if active else "鲤鱼"
    species = SPECIES[fish]
    high = giant_max(species)
    low = giant_min(species)
    return species, round(rng.triangular(low, high, low))
