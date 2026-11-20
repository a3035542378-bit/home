"""鱼塘繁育。报价、确认和领取走本群消息事务。"""
import math
import re
from datetime import datetime
from random import Random

from .db import BJ
from .fishing_waters import SPECIES, weight

DURATION = 1800
FEE = 6
SUCCESS = .75
NEWBORN_PRICE = 2
ADULT_PRICE = 3
STEPS = 10
QUOTE_SECONDS = 600
PAIR = re.compile(r"(繁育配对|确认配对)\s*[#＃](\d{1,18})\s+[#＃](\d{1,18})")
COMMANDS = {"繁育配对", "确认配对", "繁育状态", "领取幼鱼"}


def matches(cmd):
    return cmd in COMMANDS or PAIR.fullmatch(cmd)


def enabled(db, group):
    return bool(db.execute("SELECT 1 FROM breed_pilots WHERE grp=? AND enabled=1",(group,)).fetchone())


def clock(stamp):
    return datetime.fromtimestamp(math.ceil(stamp),BJ).strftime("%m月%d日 %H:%M:%S")


def resolve(db,key,now):
    db.execute("""UPDATE breed_pairs SET state=CASE WHEN wins THEN 'pending' ELSE 'failed' END
                  WHERE grp=? AND member=? AND state='active' AND due<=?""",(*key,now))


def state(db,key):
    return db.execute("""SELECT * FROM breed_pairs WHERE grp=? AND member=?
                         ORDER BY id DESC LIMIT 1""",key).fetchone()


def fry(db,item):
    return db.execute("SELECT * FROM breed_fry WHERE item=?",(item,)).fetchone()


def source(child,member):
    who = "亲自繁育" if child["breeder"]==member else "群友繁育"
    return who + ("的第一尾" if child["firstborn"] else "") + " · 塘养繁育"


def settle_fry(db,row,child,now):
    from .pond_growth import SECONDS
    extra = min(STEPS-row["rounds"],1+int((now-row["next_at"])//SECONDS))
    rounds = row["rounds"]+extra
    grams = child["birth"]+(child["adult"]-child["birth"])*rounds//STEPS
    value = NEWBORN_PRICE+(ADULT_PRICE-NEWBORN_PRICE)*rounds//STEPS
    due = row["next_at"]+extra*SECONDS if rounds<STEPS else None
    db.execute("UPDATE pond_growth SET rounds=?,next_at=? WHERE item=?",(rounds,due,row["item"]))
    db.execute("UPDATE fishing_pond SET grams=?,price=? WHERE id=? AND grp=? AND member=?",
               (grams,value,row["item"],row["grp"],row["member"]))
    return grams-row["grams"],0,0


def detail(row,child):
    stage="成年" if row["rounds"]==STEPS else f"幼体 {row['rounds']}/{STEPS} 轮"
    return [f"🐣 #{row['item']} {row['fish']} · {source(child,row['member'])}",
            f"{stage}　{weight(row['grams'])}　{row['price']} 鱼币"]


def adult(row,child):
    from .pond_growth import cap
    return row["rounds"]==STEPS or (not child and row["grams"]>=cap(row["fish"],row["original_grams"]))


def banner(current,prefix):
    if current and current["state"]=="pending":
        return f"🐣 待领幼鱼 · {current['fish']}\n发送 {prefix}领取幼鱼"
    return ""


def parents_for(db,key,ids=None):
    from .pond_growth import SELECT
    sql=SELECT+" AND p.member=?"
    params=key
    if ids:
        sql+=" AND p.id IN (?,?)"
        params+=ids
    return [r for r in db.execute(sql+" ORDER BY p.id",params)
            if r["fish"] in SPECIES and adult(r,fry(db,r["item"]))]


def claim(db,key,current,now,prefix):
    from . import fish_storage, pond_growth
    used,capacity,_=fish_storage.occupancy(db,key,"pond")
    if used>=capacity:
        return f"鱼塘已满，{current['fish']}幼鱼保留待领。先腾一格，再发 {prefix}领取幼鱼。"
    first=not db.execute("SELECT 1 FROM breed_pairs WHERE grp=? AND member=? AND claimed_at IS NOT NULL LIMIT 1",key).fetchone()
    fish,birth=current["fish"],current["birth"]
    item=db.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,grade,grade_upgraded,storage)
                VALUES(?,?,?,?,?,0,0,'pond')""",(*key,fish,birth,NEWBORN_PRICE)).lastrowid
    pond_growth.register(db,item)
    db.execute("INSERT INTO breed_fry(item,birth,adult,breeder,firstborn) VALUES(?,?,?,?,?)",
               (item,birth,SPECIES[fish][1],key[1],first))
    db.execute("UPDATE breed_pairs SET state='claimed',offspring=?,claimed_at=? WHERE id=?",(item,now,current["id"]))
    placed=pond_growth.install(db,key,item,now)
    badge="🌟 这是你亲自繁育的第一尾！" if first else "🌱 来源　亲自繁育"
    return f"🐣 已领取 #{item} {fish}幼鱼 · {weight(birth)}\n{badge}\n{placed}\n查看　{prefix}鱼塘"


def play(db,key,event,cmd,prefix):
    from . import pond_growth
    if not enabled(db,key[0]):
        return "本群暂未开启鱼塘繁育。"
    now=event["arrived"]
    pond_growth.settle(db,key[0],now,key[1])
    resolve(db,key,now)
    current=state(db,key)
    status=current["state"] if current else None
    if cmd=="繁育状态":
        if status=="active":
            return f"🥚 配对中 · {current['fish']}\n北京时间 {clock(current['due'])} 出结果，还差 {math.ceil(current['due']-now)} 秒。"
        if status=="pending":
            return "已繁育成功！\n"+banner(current,prefix)
        if status=="failed":
            return f"这次繁育失败。重新选亲鱼　{prefix}繁育配对"
        return f"当前没有待领幼鱼或进行中的配对。\n选亲鱼　{prefix}繁育配对"
    if cmd=="领取幼鱼":
        if status!="pending":
            return "当前没有待领幼鱼。"
        return claim(db,key,current,now,prefix)
    if cmd.startswith("繁育配对"):
        from . import breed_metrics
        breed_metrics.record_query(db,key,now)
    if status in ("active","pending"):
        return f"已有一对繁育中或有幼鱼待领。查看　{prefix}繁育状态"
    match=PAIR.fullmatch(cmd)
    if not match:
        from . import breed_guide
        return breed_guide.guide(db,key,prefix)
    action=match[1]
    ids=tuple(sorted((int(match[2]),int(match[3]))))
    parents=parents_for(db,key,ids)
    if len(parents)!=2 or parents[0]["fish"]!=parents[1]["fish"]:
        return "请选择自己本群鱼塘里的两条同种成年鱼。"
    fish=parents[0]["fish"]
    if action=="繁育配对":
        db.execute("""INSERT INTO breed_previews VALUES(?,?,?,?,?) ON CONFLICT(grp,member) DO UPDATE SET
                      p1=excluded.p1,p2=excluded.p2,expires=excluded.expires""",(*key,*ids,now+QUOTE_SECONDS))
        pair_lines="\n".join(f"🐟 #{p['item']} {fish} · {weight(p['grams'])}" for p in parents)
        return (f"{pair_lines}\n🪙 本次 {FEE} 鱼币 · 成功率 {SUCCESS:.0%}\n确认后扣费，30 分钟出结果。"
                f"失败或亲鱼提前离塘不退费。\n10 分钟内发送　{prefix}确认配对#{ids[0]} #{ids[1]}")
    preview=db.execute("""SELECT 1 FROM breed_previews WHERE grp=? AND member=? AND p1=? AND p2=? AND expires>?""",
                       (*key,*ids,now)).fetchone()
    if not preview:
        return f"请先查看这两条亲鱼的报价　{prefix}繁育配对#{ids[0]} #{ids[1]}"
    if not db.execute("UPDATE fishing_wallets SET coins=coins-? WHERE grp=? AND member=? AND coins>=?",
                      (FEE,*key,FEE)).rowcount:
        return f"配对需要 {FEE} 鱼币，余额不足。"
    db.execute("DELETE FROM breed_previews WHERE grp=? AND member=?",key)
    rng=Random("breed/v1/"+event["event_id"])
    wins=rng.random()<SUCCESS
    birth=max(1,SPECIES[fish][1]*rng.randint(40,60)//100)
    due=now+DURATION
    db.execute("""INSERT INTO breed_pairs(grp,member,p1,p2,fish,started,due,wins,birth,fee,state)
                  VALUES(?,?,?,?,?,?,?,?,?,?,'active')""",(*key,*ids,fish,now,due,wins,birth,FEE))
    return (f"🥚 配对成功 #{ids[0]} + #{ids[1]} · {fish}\n配对支出 {FEE} 鱼币\n"
            f"北京时间 {clock(due)} 出结果，成功即可领取。\n查看　{prefix}鱼塘")
