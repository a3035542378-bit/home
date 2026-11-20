"""单尾鱼获的品级、首次突破奖励和本群喜报。"""
from random import Random
from typing import NamedTuple

from .display_names import labels
from .fishing_waters import SPECIES, giant_max, giant_min, size_grade, weight

GRADES = ("普通", "优良", "稀有", "史诗", "传说", "神话")
TIERS = ("小型", "标准", "大型", "巨物")
BASE = {
    "普通": (0, 0, 1, 2), "稀有": (0, 1, 2, 3), "珍品": (1, 2, 3, 4),
    "史诗": (2, 3, 3, 4), "传说": (3, 3, 4, 4),
}
TICKETS = {
    "小型": (8888, 1000, 100, 10, 2), "标准": (8950, 900, 130, 18, 2),
    "大型": (8400, 1400, 170, 28, 2), "巨物": (9700, 290, 10, 0, 0),
}
POINTS = (0, 5, 20, 100, 500, 1000)
PRICE_TENTHS = (10, 16, 26, 45, 75, 120)
GIANT_PREMIUM_PERCENT = 50


class Grade(NamedTuple):
    base: int
    final: int

    @property
    def upgraded(self):
        return self.final > self.base


def base_grade(fish, grams):
    if fish not in SPECIES:
        return None
    return BASE[SPECIES[fish][-1]][TIERS.index(size_grade(fish, grams))]


def roll_upgrade(tier, rng):
    ticket = rng.randrange(10000)
    for levels, count in enumerate(TICKETS[tier]):
        if ticket < count:
            return levels
        ticket -= count
    raise ValueError("升品签数应为一万")


def final_grade(fish, grams, event_id, event_fish=False, rng=None):
    tier = "巨物" if event_fish else size_grade(fish, grams)
    base = BASE[SPECIES[fish][-1]][TIERS.index(tier)]
    levels = roll_upgrade(tier, rng if rng is not None else Random("fish-grade:" + event_id))
    return Grade(base, min(5 if event_fish else 4, base + int(event_fish) + levels))


def price(fish, grams, grade, appearance=0):
    _, low, high, base, _, _ = SPECIES[fish]
    span = high - low
    offset = max(0, min(span, grams - low))
    numerator = base * (8 * span + 7 * offset) * PRICE_TENTHS[grade]
    denominator = 100 * span
    species = SPECIES[fish]
    threshold = giant_min(species)
    if grams > threshold:
        spread = max(1, giant_max(species) - threshold)
        numerator *= 100 * spread + GIANT_PREMIUM_PERCENT * min(grams - threshold, spread)
        denominator *= 100 * spread
    numerator *= 100 + appearance
    denominator *= 100
    return max(1, (numerator + denominator // 2) // denominator)


def label(grade, upgraded):
    if grade is None:
        return ""
    return GRADES[grade] + (" ✨升品" if upgraded else "")


def award_first_grade_points(db, key, fish, grams, grade, event):
    previous = db.execute("SELECT best_grade FROM fishing_species WHERE grp=? AND member=? AND fish=?",
                          (*key, fish)).fetchone()
    improved = previous is None or previous[0] is None or grade.final > previous[0]
    db.execute("""INSERT INTO fishing_species(grp,member,fish,best_grams,best_grade,best_grade_upgraded)
                  VALUES(?,?,?,?,?,?) ON CONFLICT(grp,member,fish) DO UPDATE SET
                  best_grams=max(best_grams,excluded.best_grams),
                  best_grade_upgraded=CASE WHEN best_grade IS NULL OR excluded.best_grade>best_grade
                      THEN excluded.best_grade_upgraded ELSE best_grade_upgraded END,
                  best_grade=max(coalesce(best_grade,-1),excluded.best_grade)""",
               (*key, fish, grams, grade.final, grade.upgraded))
    points = POINTS[grade.final] if improved else 0
    if points:
        db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                      VALUES(?,?,0,'钓鱼品级',?,'fishing-grade/1',?,?,?)""",
                   (*key, points, event["event_id"], event["arrived"], fish + " · " + GRADES[grade.final]))
    return points


def announcement(db, key, fish, grams, grade, event_fish):
    if grade.final < 3:
        return ""
    if grade.final >= 4:
        db.execute("""INSERT INTO fishing_grade_news(grp,member,fish,grams,grade,upgraded,legends)
                      VALUES(?,?,?,?,?,?,?) ON CONFLICT(grp) DO UPDATE SET
                      member=excluded.member,fish=excluded.fish,grams=excluded.grams,grade=excluded.grade,
                      upgraded=excluded.upgraded,legends=legends+excluded.legends""",
                   (*key, fish, grams, grade.final, grade.upgraded, grade.final == 4 and grade.upgraded))
    if grade.final > grade.base + int(event_fish):
        return "✨ 欧皇！升品到" + GRADES[grade.final] + "！"
    title = "🌊 活动升品！" if grade.upgraded else "🏅 恭喜钓到"
    return title + GRADES[grade.final] + "！"


def honors(db, group):
    row = db.execute("SELECT * FROM fishing_grade_news WHERE grp=?", (group,)).fetchone()
    if not row:
        return "🌟 本群升品传说鱼　0 条"
    name = labels(db, group)(row["member"])
    return (f"🌟 本群升品传说鱼　{row['legends']} 条\n"
            f"📌 最近喜报　{name}\n　{row['fish']} · {weight(row['grams'])} · {label(row['grade'], row['upgraded'])}")
