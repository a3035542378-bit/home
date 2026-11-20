"""只读统计：python -m tools.pond_week DB GROUP YYYY-MM-DD（首日，北京时间）。"""
import argparse
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path


def report(con, group, start):
    end = start + timedelta(days=7)
    rows = con.execute("""SELECT day,member,action FROM pond_activity
        WHERE day>=? AND day<? AND grp=?""",(start.isoformat(),end.isoformat(),group))
    active, stored, lit, tend = set(), {}, set(), set()
    for day, member, action in rows:
        if action == "cast":
            active.add(member)
        if action == "store":
            stored[member] = min(stored.get(member,day),day)
        if action in ("store","tend"):
            tend.add((member,day))
        if action == "light":
            lit.add(member)
    cohort = {member:date.fromisoformat(day) for member,day in stored.items()
              if date.fromisoformat(day) < end-timedelta(days=1)}
    returned = sum((member,(day+timedelta(days=1)).isoformat()) in tend for member,day in cohort.items())
    net = con.execute("SELECT coalesce(sum(net),0) FROM pond_coin_flow WHERE grp=? AND day>=? AND day<?",
                      (group,start.isoformat(),end.isoformat())).fetchone()[0]
    return {"活跃钓手中主动存塘":(len(active & stored.keys()),len(active)),
            "首次存塘次日主动养鱼":(returned,len(cohort)),
            "鱼币净新增":net, "活跃钓手中点亮新鱼种":(len(active & lit),len(active))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database",type=Path)
    parser.add_argument("group")
    parser.add_argument("start",type=date.fromisoformat)
    args = parser.parse_args()
    with closing(sqlite3.connect(args.database.resolve().as_uri()+"?mode=ro",uri=True)) as database:
        for label,value in report(database,args.group,args.start).items():
            print(label, value if isinstance(value,int) else f"{value[0]} / {value[1]}")
