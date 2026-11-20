"""鱼线和鱼竿共用一次拉扯的实际重量，损耗跟随本群玩家的装备。"""
from dataclasses import dataclass
from math import ceil

from .fishing_waters import FISH, giant_max


def strain(grams):
    return 1 + (grams + 999) // 1000


MAX_STRAIN = strain(max(giant_max(species) for species in FISH))
LINE_LIMITS = (100, 140, 180, 230, 300)
ROD_LIMITS = (500, 1100, 2000, 3800, 3 * MAX_STRAIN + ceil(MAX_STRAIN / 4))
LINE_PRICE = 3
ROD_PRICES = (3, 8, 16, 28, 40)


@dataclass(frozen=True)
class Wear:
    line: int = 0
    rod: int = 0


def read(db, key):
    row = db.execute("SELECT line_wear,rod_wear FROM fishing_wear WHERE grp=? AND member=?", key).fetchone()
    return Wear(*row) if row else Wear()


def save(db, key, wear):
    db.execute("""INSERT INTO fishing_wear(grp,member,line_wear,rod_wear) VALUES(?,?,?,?)
                  ON CONFLICT(grp,member) DO UPDATE SET line_wear=excluded.line_wear,rod_wear=excluded.rod_wear""",
               (*key, wear.line, wear.rod))


def percent(spent, limit):
    remaining = limit - spent
    if remaining <= 0:
        return 0
    return max(1, remaining * 100 // limit)


def line_load(grams, line_level):
    # 满耐久线能承受一次极重拉扯；抗过载和脱钩仍独立判定。
    return min(strain(grams), LINE_LIMITS[line_level-1] * 2 // 3)


def pull_load(grams, line_level, toughness, rounding):
    # 双方使用同一次取整；小鱼也能按长期比例节省磨损。
    factor = 1 - .5 * toughness
    def adjusted(raw):
        return max(1, int(raw * factor + rounding))
    return Wear(adjusted(line_load(grams, line_level)), adjusted(strain(grams)))


def fatigue(spent, limit):
    # 剩余 30% 以下开始增加断裂概率，磨损越深风险越高。
    return min(.85, max(0., (spent / limit - .70) * 3))


def after_pull(wear, load, line_level, rod, damage, broken):
    line_limit = LINE_LIMITS[line_level-1]
    if broken or damage == "线":
        line = line_limit
    else:
        line = min(line_limit-1, wear.line + load.line)
    rod_wear = 0 if damage == "竿" else min(ROD_LIMITS[rod-1]-1, wear.rod + load.rod)
    return Wear(line, rod_wear)


def condition(spent, limit):
    return f"耐久 {percent(spent,limit)}%（{max(0,limit-spent)}/{limit}）"
