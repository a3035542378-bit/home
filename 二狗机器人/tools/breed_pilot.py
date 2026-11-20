"""按稳定群 ID 开关繁育或读取首周报表。"""
import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from ergou import breed_metrics, breeding, db


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("enable","disable","week"))
    parser.add_argument("database",type=Path)
    parser.add_argument("group")
    args=parser.parse_args()
    path=args.database.resolve(strict=True)
    now=time.time()
    if args.action=="week":
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)) as con, con:
            con.execute("BEGIN")
            print(json.dumps(breed_metrics.week(con,args.group,now),ensure_ascii=False,indent=2))
        return
    with db.closing_db(path) as con, db.transaction(con):
        if args.action=="enable" and not con.execute("""SELECT 1 FROM groups g JOIN agent_wechat_links l
                   ON l.grp=g.id AND l.account=g.account WHERE g.id=? AND g.paused=0""",(args.group,)).fetchone():
            parser.error("须指定已绑定并启用的稳定群 ID")
        breed_metrics.switch(con,args.group,args.action=="enable",now)
        print("繁育已开启" if breeding.enabled(con,args.group) else "繁育已关闭")


if __name__=="__main__":
    main()
