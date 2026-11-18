"""Local replay benchmark. CLI arguments can reproduce the PRD rate/duration profiles."""
import argparse
import json
import math
import platform
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from ergou.db import closing_db,demo,initialize
from ergou.engine import receive,step
from ergou.jobs import Simulation,send_one


def percentile(values,p):
    return round(sorted(values)[max(0,math.ceil(len(values)*p)-1)]*1000,2) if values else None


def run(groups,total,ratio,hot,rate):
    with tempfile.TemporaryDirectory() as tmp:
        dbpath=Path(tmp)/"load.sqlite"
        initialize(dbpath)
        names=[f"group-{i}" for i in range(groups)]
        demo(dbpath,names)
        with closing_db(dbpath) as db:
            for group in names:
                for game in ("猜数字","成语接龙","向日葵花圃"):
                    receive(db,"sim-account",group,"host","setup-"+group+game,{"text":"二狗 开始 "+game});step(db)
            db.execute("UPDATE outbox SET state='CANCELLED',detail='预置局' WHERE state='PENDING'")
        done=threading.Event()
        latency=[];peak=0;errors=[]
        def consume():
            nonlocal peak
            try:
                with closing_db(dbpath) as db:
                    while not done.is_set() or db.execute("SELECT 1 FROM inbox WHERE state='PENDING'").fetchone():
                        with_pending=db.execute("SELECT COUNT(*),MIN(arrived) FROM inbox WHERE state='PENDING'").fetchone()
                        peak=max(peak,with_pending[0])
                        if with_pending[0] and step(db):latency.append(time.time()-with_pending[1])
                        else:time.sleep(.001)
                        send_one(db,Simulation())
            except Exception as exc:errors.append(type(exc).__name__)
        thread=threading.Thread(target=consume);thread.start()
        begin=time.monotonic()
        try:
            with closing_db(dbpath) as db:
                for i in range(total):
                    if rate:
                        time.sleep(max(0,begin+i/rate-time.monotonic()))
                    size=len(names) if not hot or i%10==0 else min(3,len(names))
                    group=names[(i*73)%size]
                    cmd=(i*37)%100<ratio
                    receive(db,"sim-account",group,"user-"+str(i%211),f"load-{i}",{"text":"二狗 状态 G01" if cmd else "测试群成员普通文本"})
        finally:done.set();thread.join()
        elapsed=time.monotonic()-begin
        with closing_db(dbpath) as db:
            counts=dict(db.execute("SELECT state,COUNT(*) FROM inbox WHERE source LIKE 'load-%' GROUP BY state"))
            outbound=dict(db.execute("SELECT state,COUNT(*) FROM outbox WHERE detail IS NULL OR detail!='预置局' GROUP BY state"))
            times=[r[0] for r in db.execute("SELECT ack_at-created FROM outbox WHERE state='ACKNOWLEDGED'")]
        return dict(groups=groups,hot=hot,parallel_games=3,command_pct=ratio,events=total,seconds=round(elapsed,3),
                    throughput=round(total/elapsed,2),ingest_to_commit_p95_ms=percentile(latency,.95),ingest_to_commit_p99_ms=percentile(latency,.99),
                    peak_sampled_queue=peak,ingress=counts,outbox_at_end=outbound,delivery_from_ingress_p95_ms=percentile(times,.95),
                    errors=errors,completed_samples=len(latency))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--groups",type=int,default=200);p.add_argument("--events",type=int,default=1000)
    p.add_argument("--rate",type=float,default=0);p.add_argument("--ratios",type=int,nargs="+",default=[5,30,100]);p.add_argument("--output",type=Path)
    args=p.parse_args()
    results=[run(args.groups,args.events,r,h,args.rate) for h in (False,True) for r in args.ratios]
    report=json.dumps(dict(adapter="simulation",python=platform.python_version(),sqlite=sqlite3.sqlite_version,
                      system=platform.platform(),rate=args.rate,profiles=results),indent=2)
    if args.output:args.output.write_text(report,encoding="utf-8")
    print(report)
    if any(r["errors"] or r["completed_samples"]!=args.events for r in results):raise SystemExit(1)

