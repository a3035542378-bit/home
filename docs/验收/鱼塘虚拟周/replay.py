"""Set PYTHONPATH to the archived 97616d9 robot directory. No live adapters are used."""
import argparse
import inspect
import hashlib
import json
import re
import tempfile
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from unittest.mock import patch

from ergou import db, engine, fishing, fishing_bait, fish_storage, pond_growth as growth
from tools.pond_week import report

START = datetime(2026, 11, 2, tzinfo=db.BJ)
EPOCH = int(START.timestamp())
SEEDS = (17, 31, 53, 79, 101, 137)
GROUPS = ("lake", "bay")
# member, starts (hours), minutes/session, rod, line, pond, bag, area
PROFILES = (
    ("brief", (20,), 4, 1, 1, 1, 1, "新手池塘"),
    ("split", (8, 13, 21), 5, 3, 3, 3, 2, "外海"),
    ("expert", (7, 12, 19), 16, 5, 5, 5, 5, "深渊海沟"),
)
STRATEGIES = ("sell", "natural", "feed", "select")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def decision(seed, token, probability):
    return Random(f"{seed}/{token}").random() < probability


def calendar():
    slots = []
    for day in range(7):
        for gi, group in enumerate(GROUPS):
            for pi, (member, hours, minutes, *_) in enumerate(PROFILES):
                for hour in hours:
                    for minute in range(minutes):
                        # Separate member action windows. The same player always casts at :20.
                        start = EPOCH + day*86400 + hour*3600 + (pi*18+gi*60+minute)*60
                        slots.append((start, group, member, minute))
    return sorted(slots)


class World:
    def __init__(self, path, seed, mode, log_path):
        db.initialize(path)
        db.demo(path, GROUPS)
        self.con = db.connect(path)
        self.con.execute("PRAGMA synchronous=OFF")  # disposable simulation only
        self.now = EPOCH-120
        self.con.create_function("date", 2, self.sqlite_date)
        self.seed, self.mode = seed, mode
        self.events = []
        self.log_path = log_path
        self.catches = []
        self.sums = defaultdict(Counter)
        self.active_fish = {}
        self.fish_values = {}
        self.exhibits = defaultdict(set)
        self.token = ""
        for group in GROUPS:
            for member, _, _, rod, line, pond, bag, area in PROFILES:
                key = (group,member)
                self.con.execute("INSERT INTO fishing_wallets VALUES(?,?,1000,?)",(*key,rod))
                self.con.execute("INSERT INTO fishing_waters VALUES(?,?,?)",(*key,area))
                self.con.execute("INSERT INTO fishing_line_levels VALUES(?,?,?)",(*key,line))
                self.con.executemany("INSERT INTO fishing_storage_levels VALUES(?,?,?,?)",
                                     [(*key,"pond",pond),(*key,"bag",bag)])
                if member == "expert":
                    self.con.executemany("INSERT INTO rod_enhancements VALUES(?,?,?,?,?,?)",
                        [(*key,i,i+2,i+2,i+2) for i in range(1,6)])
                    self.con.execute("INSERT INTO fishing_experience VALUES(?,?,100)",key)
                self.con.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                     VALUES(?,?,0,'fixture',500,'fixture',?,?,'期初积分')""",(*key,group+member,self.now))

    def sqlite_date(self, value, zone):
        assert (value,zone)==("now","+8 hours")
        return datetime.fromtimestamp(self.now,db.BJ).date().isoformat()

    def send(self, key, cmd, when, source):
        assert when>=self.now, (when,self.now)
        self.now = when
        self.token = f"{self.seed}/{source}"
        seq = engine.receive(self.con,"sim-account",*key,source,{"text":"二狗"+cmd},now=when)
        engine.step(self.con)
        row = self.con.execute("""SELECT i.state,o.body FROM inbox i JOIN outbox o ON o.biz=i.event_id
                                  WHERE i.seq=?""",(seq,)).fetchone()
        assert row and row["body"] and row["state"] not in ("FAILED","REJECTED","RATE_LIMITED"), (key,cmd,source,row)
        self.events.append((when,*key,cmd,row["body"]))
        return row["body"]

    def visit(self, base, group, member, minute):
        key = (group,member)
        tag = f"{group}/{member}/{base}"
        counter = 0
        def say(cmd):
            nonlocal counter
            counter += 1
            assert counter < 20
            return self.send(key,cmd,base+counter,tag+"/act/"+str(counter))
        day = (base-EPOCH)//86400
        only_view = day == 1 and member == "brief"
        if minute == 0 or (self.mode!="sell" and minute%3==0):
            say("鱼塘")
            if decision(self.seed,tag+"/peek",.35):
                say("鱼塘")
            if not only_view and self.mode!="sell":
                for r in self.con.execute(growth.SELECT+" AND p.member=? ORDER BY p.id",key).fetchall():
                    if r["next_at"] is None:
                        assert "到账" in say(f"卖鱼#{r['item']}")
                    elif not r["food"] and self.feeds(r["fish"],r["original_price"],r["original_grams"]):
                        assert "已投喂" in say(f"投喂#{r['item']}")
        if only_view:
            return
        bait = "免费鱼饵"
        if member != "brief" and decision(self.seed,tag+"/bait",.25):
            target = "顶级鱼饵" if member=="expert" else "高级鱼饵"
            if fishing_bait.balance(self.con,key)>=fishing_bait.BAITS[target].points:
                bait = target
        cmd = "抛竿 "+bait
        body = self.send(key,cmd,base+20,tag+"/cast")
        result = re.search(r"收入鱼包 #(\d+)",body)
        if not result:
            assert any(x in body for x in ("脱钩","折断","鱼线断了")), body
            self.catches.append([tag,bait,body.splitlines()[1]])
            if "折断" in body and member!="brief":
                reply=self.send(key,"升级鱼竿",base+22,tag+"/repair")
                assert "鱼竿升到" in reply
            if "鱼线断了" in body:
                assert "新鱼线" in self.send(key,"买鱼线",base+23,tag+"/line")
            return
        item = int(result[1])
        row = self.con.execute("SELECT * FROM fishing_pond WHERE id=?",(item,)).fetchone()
        fish,grams,grade,price = (row[n] for n in ("fish","grams","grade","price"))
        self.catches.append([tag,bait,item,fish,grams,grade,price])
        def after(cmd, offset):
            return self.send(key,cmd,base+offset,tag+"/post/"+str(offset))
        if fish not in self.exhibits[key] and decision(self.seed,tag+"/light",.12):
            assert "已点亮" in after(f"收入图鉴#{item}",25)
            self.exhibits[key].add(fish)
            return
        if self.mode != "sell":
            active = self.con.execute(growth.SELECT+" AND p.member=? AND g.next_at IS NOT NULL",key).fetchall()
            used,capacity,level = fish_storage.occupancy(self.con,key,"pond")
            if len(active)<growth.SLOTS[level-1] or used==capacity:
                reply=after(f"放入鱼塘#{item}",25)
                if "已将" in reply:
                    self.active_fish[item]=(key,price,self.feeds(fish,price,grams))
                    if "进入成长位" in reply and self.feeds(fish,price,grams):
                        assert "已投喂" in after(f"投喂#{item}",29)
                    return
                assert "鱼塘已满" in reply
        assert "到账" in after(f"卖鱼#{item}",32)

    def feeds(self,fish,price,grams):
        if self.mode == "feed":
            return True
        return self.mode=="select" and price>=25 and growth.cap(fish,grams)>=grams*1.15

    def finish(self):
        # A read-only accounting snapshot at the common cutoff; no late sales or feeding.
        self.now = EPOCH+7*86400-1
        c=self.con
        c.execute("SAVEPOINT closing_quote")
        for group in GROUPS:
            growth.settle(c,group,self.now)
        for row in c.execute("SELECT * FROM fishing_pond"):
            key=(row["grp"],row["member"])
            self.sums[key].update(stock=row["price"],stock_n=1)
            self.fish_values[row["id"]] = row["price"]
        c.execute("ROLLBACK TO closing_quote")
        c.execute("RELEASE closing_quote")
        with self.log_path.open("w") as f:
            for event in self.events:
                f.write(json.dumps(event,ensure_ascii=False)+"\n")
        return self.audit()

    def audit(self):
        days=defaultdict(lambda:defaultdict(set))
        daily_cash=Counter()
        feeds=Counter()
        for line in self.log_path.open():
            stamp,g,m,cmd,msg=json.loads(line)
            key=(g,m)
            s=self.sums[key]
            day=(stamp-EPOCH)//86400
            before=s["sales"]-s["feed"]-s["repairs"]
            if cmd.startswith("抛竿"):
                days[key][day].add("cast")
                s["casts"]+=1
                s["landed"]+=int("收入鱼包 #" in msg)
                s["points_spent"]+=fishing_bait.BAITS[cmd.split()[1]].points
                reward=re.search(r"品级新高　＋(\d+) 积分",msg)
                s["points_earned"]+=int(reward[1]) if reward else 0
            if cmd.startswith("放入鱼塘#"):
                if "已将" in msg:
                    days[key][day].add("store")
                    s["stored"]+=1
                else:
                    s["full"]+=1
            if cmd.startswith("收入图鉴#"):
                days[key][day].add("light")
                s["lit"]+=1
            if cmd.startswith("投喂#") and "已投喂" in msg:
                days[key][day].add("tend")
                cost=int(re.search(r"−(\d+) 鱼币",msg)[1])
                s["feed"]+=cost
                feeds[int(cmd.split("#")[1])]+=cost
            if cmd.startswith("卖鱼#"):
                item=int(cmd.split("#")[1])
                sale=int(re.search(r"到账 (\d+) 枚",msg)[1])
                self.fish_values[item]=sale
                s.update(sales=sale,sold=1)
            if cmd in ("升级鱼竿","买鱼线"):
                if cmd=="买鱼线":
                    s["repairs"]+=int(re.search(r"消耗 (\d+) 鱼币",msg)[1])
                else:
                    balance=int(re.search(r"剩余 (\d+) 鱼币",msg)[1])
                    s["repairs"]+=1000+s["sales"]-s["feed"]-s["repairs"]-balance
            daily_cash[g,day]+=s["sales"]-s["feed"]-s["repairs"]-before
        reports={}
        for g in GROUPS:
            active,stored,lit,cohort,returned=set(),set(),set(),set(),set()
            cash=0
            for m,*_ in PROFILES:
                key=(g,m)
                s=self.sums[key]
                actions=days[key]
                for day,act in actions.items():
                    if "cast" in act: active.add(m)
                    if "light" in act: lit.add(m)
                first=min((d for d,a in actions.items() if "store" in a),default=None)
                if first is not None:
                    stored.add(m)
                    if first<6:
                        cohort.add(m)
                        if actions[first+1]&{"store","tend"}: returned.add(m)
                s["cash"]=s["sales"]-s["repairs"]-s["feed"]
                s["net"]=s["cash"]+s["stock"]
                cash+=s["cash"]
                wallet=self.con.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()[0]
                assert wallet==1000+s["cash"]
                assert fishing_bait.balance(self.con,key)==500+s["points_earned"]-s["points_spent"]
                assert s["landed"]==s["sold"]+s["stock_n"]+s["lit"]
                if m=="brief": assert not actions[1]
            posted=dict(self.con.execute("SELECT day,net FROM pond_coin_flow WHERE grp=?",(g,)))
            for day in range(7):
                label=(START.date()+timedelta(days=day)).isoformat()
                assert posted.get(label,0)==daily_cash[g,day]
            actual=report(self.con,g,START.date())
            expected={"活跃钓手中主动存塘":(len(active&stored),len(active)),
                      "首次存塘次日主动养鱼":(len(returned),len(cohort)),
                      "鱼币净新增":cash,"活跃钓手中点亮新鱼种":(len(active&lit),len(active))}
            assert actual==expected,(actual,expected)
            marks={(r["day"],r["member"],r["action"]) for r in self.con.execute("SELECT * FROM pond_activity WHERE grp=?",(g,))}
            derived={((START.date()+timedelta(days=day)).isoformat(),m,act) for (grp,m),dd in days.items() if grp==g
                     for day,acts in dd.items() for act in acts}
            assert marks==derived
            reports[g]=actual
        return dict(seed=self.seed,mode=self.mode,fish_hash=digest(json.dumps(self.catches)),messages=len(self.events),
                    players={g+"/"+m:dict(s) for (g,m),s in self.sums.items()},reports=reports,
                    fish={item:[k[0]+"/"+k[1],orig,self.fish_values[item]-feeds[item],feeds[item]]
                          for item,(k,orig,_) in self.active_fish.items()})


def repair_candidate(cost):
    if cost == 80:
        return fishing.play
    # Only in the replay process: a fifth enhancement tier proves the rod previously reached level 5.
    src=inspect.getsource(fishing.play)
    anchor="    upgrade=20*rod\n"
    assert src.count(anchor)==1
    replacement=anchor+f"""    if cmd=="升级鱼竿" and rod==4 and len(gear.levels(db,key))==5:
        upgrade={int(cost)}
"""
    env=dict(fishing.play.__globals__)
    exec(compile(src.replace(anchor,replacement),"<simulation-only fifth-tier repair>","exec"),env)
    return env["play"]


def run(job):
    seed,mode,divisor,repair,folder=job
    with tempfile.TemporaryDirectory() as temp, patch.object(growth,"FEED_PRICE_DIVISOR",divisor), patch.object(fishing,"play",repair_candidate(repair)):
        path=Path(temp)/"sim.sqlite"
        prefix=Path(folder)/f"{divisor}-{seed}-{mode}"
        w=World(path,seed,mode,prefix.with_suffix(".jsonl"))
        try:
            with patch("time.time",new=lambda:w.now), patch("uuid.uuid4",new=lambda:uuid.UUID(digest(w.token)[:32])):
                for args in calendar():
                    w.visit(*args)
                result=w.finish()
            prefix.with_suffix(".json").write_text(json.dumps(result,ensure_ascii=False))
        finally:
            w.con.close()
        return result["fish_hash"]


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("folder",type=Path)
    parser.add_argument("--divisor",type=int,default=16)
    parser.add_argument("--repair",type=int,default=80)
    parser.add_argument("--seeds",type=int,nargs="+",default=SEEDS)
    args=parser.parse_args()
    args.folder.mkdir(exist_ok=True,parents=True)
    with ProcessPoolExecutor(max_workers=4) as pool:
        for seed in args.seeds:
            hashes=list(pool.map(run,[(seed,s,args.divisor,args.repair,args.folder) for s in STRATEGIES]))
            assert len(set(hashes))==1,(seed,hashes)
            print(seed,hashes[0][:16],flush=True)
