"""强化属性的成长区间、历史折算和战斗系数。"""
from math import sqrt

STAGES_PER_GRADE = 20
MAX_STAGE = 5 * STAGES_PER_GRADE
FIELDS = ("quality", "toughness", "hardness", "luck")


def bounds(tier):
    return 10 * (tier - 1)**2 + 1, 10 * tier**2


def contribution(points):
    return 1 + sqrt(points) / 20


MAX_POWER = sum(contribution(bounds(tier)[1]) for tier in range(1, MAX_STAGE + 1))


def power(rows, field):
    return sum(contribution(row[field]) for row in rows) / MAX_POWER


def active_levels(grade, rows):
    return [row for row in rows if row["tier"] <= grade * STAGES_PER_GRADE]


def migrate(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(rod_enhancements)")}
    if "luck" in columns:
        return
    if columns:
        db.execute("ALTER TABLE rod_enhancements RENAME TO old_rod_enhancements")
    checks = ", ".join(f"{field} INTEGER NOT NULL CHECK({field} BETWEEN "
                       "10*(tier-1)*(tier-1)+1 AND 10*tier*tier)" for field in FIELDS)
    db.execute(f"""CREATE TABLE rod_enhancements (
        grp TEXT NOT NULL, member TEXT NOT NULL, tier INTEGER NOT NULL CHECK(tier BETWEEN 1 AND {MAX_STAGE}),
        {checks}, PRIMARY KEY(grp,member,tier),
        FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member))""")
    if columns:
        for row in db.execute("SELECT * FROM old_rod_enhancements"):
            tier = row["tier"]
            low, high = bounds(tier)
            values = [low + (row[field] - 1) * (high - low) // (tier + 1)
                      for field in ("quality", "toughness", "hardness", "quality")]
            db.execute("INSERT INTO rod_enhancements VALUES(?,?,?,?,?,?,?)",
                       (row["grp"], row["member"], tier, *values))
        db.execute("DROP TABLE old_rod_enhancements")
