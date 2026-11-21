"""图鉴奖励随结算事务入账，积分流水同时保留永久领奖凭证。"""
from datetime import datetime, timedelta

from .db import BJ
from .fishing_waters import WATERS


PRIZES = (100, 40, 20, 12, 8, 6, 5, 4, 3, 2)
REGIONS = {area: frozenset(row[0] for row in school) for area, school in WATERS.items()}


def credit(db, key, kind, event, points, reason, now):
    return db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
        VALUES(?,?,0,?,?,'exhibit/1',?,?,?) ON CONFLICT DO NOTHING""",
        (*key, kind, points, event, now, reason)).rowcount


def regions(db, key, areas, now):
    lit = {r[0] for r in db.execute("SELECT fish FROM fishing_exhibits WHERE grp=? AND member=?", key)}
    receipts = []
    for area in areas:
        species = REGIONS[area]
        if not species.issubset(lit):
            continue
        coins = len(species)
        if credit(db, key, "区域图鉴", area, 2*coins, f"首次集齐{area} · 鱼币 +{coins}", now):
            db.execute("INSERT OR IGNORE INTO fishing_wallets(grp,member) VALUES(?,?)", key)
            db.execute("UPDATE fishing_wallets SET coins=coins+? WHERE grp=? AND member=?", (coins,*key))
            receipts.append(f"🏅 集齐{area}！+{2*coins} 积分，+{coins} 鱼币。")
    return receipts


def settle(db, group, now, enabled):
    """每日首次维护或点亮前结算，停服跨多天只补最近一个已结束的榜期。"""
    from .exhibit_board import ranked
    today = datetime.fromtimestamp(now, BJ).date()
    day = today.isoformat()
    db.execute("INSERT OR IGNORE INTO exhibit_reward_clock(grp,day) VALUES(?,?)", (group,day))
    clock = db.execute("SELECT day,checked FROM exhibit_reward_clock WHERE grp=?", (group,)).fetchone()
    if enabled and not clock["checked"]:
        for row in db.execute("SELECT DISTINCT member FROM fishing_exhibits WHERE grp=?", (group,)).fetchall():
            regions(db, (group,row[0]), REGIONS, now)
        db.execute("UPDATE exhibit_reward_clock SET checked=1 WHERE grp=?", (group,))
    if clock["day"] >= day:
        return
    if enabled:
        period = (today-timedelta(days=1)).isoformat()
        for slot, (row, points) in enumerate(zip(ranked(db,group), PRIZES), 1):
            credit(db, (group,row["member"]), "图鉴日榜", period, points,
                   f"{period} 图鉴榜第 {slot} 席 · {row['lit']} 种", now)
    db.execute("UPDATE exhibit_reward_clock SET day=? WHERE grp=?", (day,group))


def maintenance(db, now):
    for row in db.execute("""SELECT g.id, NOT g.paused AND NOT coalesce(p.detached,0)
        AND json_extract(g.config,'$.enabled') AND json_extract(g.config,'$.games')
        AND NOT EXISTS (SELECT 1 FROM json_each(g.config,'$.disabled_games') WHERE value='钓鱼') AS enabled
        FROM groups g LEFT JOIN group_profile p ON p.grp=g.id""").fetchall():
        settle(db, row["id"], now, bool(row["enabled"]))
