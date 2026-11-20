"""在临时 SQLite 中重放真实抛竿。运行 python -m tools.pond_economy。"""
from collections import Counter
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory

from ergou import db, fishing, fishing_bait, pond_growth as growth


def mature(row, fed, level):
    state = dict(original_grams=row["grams"], original_grade=row["grade"], original_price=row["price"],
                 rounds=0, food=0, first_fed=0, fed_segment=0, appearance=0, promoted=0)
    grams, grade, cost = row["grams"], row["grade"], 0
    fish = row["fish"]
    while grams < growth.cap(fish,row["grams"]) and state["rounds"] < growth.ROUNDS:
        if fed and not state["food"]:
            cost += growth.feed_cost(row["price"],state["rounds"])
            state.update(food=min(3,growth.ROUNDS-state["rounds"]),first_fed=1)
        rng = Random(f"pond/v1:{row['id']}:{state['rounds']}")
        grams,grade = growth.advance(fish,state,grams,grade,level,rng)
    return growth.valuation(fish,state,grams,grade),cost


def simulate(path, area, bait, casts):
    db.initialize(path)
    db.demo(path)
    key = ("demo-group","angler")
    rod, line, level = (1,1,1) if area == "新手池塘" else (4,3,5)
    with db.closing_db(path) as con, db.transaction(con):
        con.execute("INSERT INTO fishing_wallets VALUES(?,?,10000000,?)",(*key,rod))
        con.execute("INSERT INTO fishing_line_levels VALUES(?,?,?)",(*key,line))
        con.execute("INSERT INTO fishing_waters VALUES(?,?,?)",(*key,area))
        con.execute("INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason) VALUES(?,?,0,'模拟',10000000,'sim','sim',0,'模拟')",key)
        sums = Counter()
        for i in range(casts):
            event = dict(grp=key[0],member=key[1],adapter_version="simulation",arrived=1700000000+i*20,
                         event_id=f"economy/v1/{area}/{i}")
            msg = fishing.play(con,event,"抛竿 "+bait,"二狗",db.DEFAULT)
            if "鱼线断了" in msg:
                fishing.play(con,event,"买鱼线","二狗",db.DEFAULT)
                sums["line"] += 3
            if "鱼竿折断" in msg and rod > 1:
                fishing.play(con,event,"升级鱼竿","二狗",db.DEFAULT)
                sums["rod"] += 20*(rod-1)
            row = con.execute("SELECT * FROM fishing_pond").fetchone()
            if row:
                natural,_ = mature(row,False,level)
                fed,cost = mature(row,True,level)
                sums.update(dict(landed=1,direct=row["price"],natural=natural,
                                 fed=fed,food=cost,wins=int(fed-cost>natural)))
                con.execute("DELETE FROM pond_growth WHERE item=?",(row["id"],))
                con.execute("DELETE FROM fishing_pond WHERE id=?",(row["id"],))
        actual = con.execute("SELECT casts FROM fishing_experience").fetchone()[0]
        assert actual == casts
        points = -con.execute("SELECT coalesce(sum(points),0) FROM ledger WHERE kind='鱼饵'").fetchone()[0]
        assert points == casts*fishing_bait.BAITS[bait].points
        costs = sums["line"] + sums["rod"]
        values = [sums["landed"],points,sums["line"],sums["rod"],sums["food"],
                  sums["direct"]-costs,sums["natural"]-costs,sums["fed"]-costs-sums["food"]]
        return [round(x*100/casts,1) for x in values]+[round(100*sums["wins"]/sums["landed"],1)]


if __name__ == "__main__":
    with TemporaryDirectory() as folder:
        for area in ("新手池塘","外海","深渊海沟"):
            for bait in fishing_bait.BAITS:
                print(area,bait,*simulate(Path(folder)/(area+bait),area,bait,2000),flush=True)
