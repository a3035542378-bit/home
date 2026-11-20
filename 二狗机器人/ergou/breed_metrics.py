"""按群统计灰度开启后的七天。确定性的自然成长允许在离线期计算资格到达时间。"""
from collections import defaultdict

from . import breeding, pond_growth
from .fishing_waters import SPECIES

WEEK = 7 * 86400


def ready_at(db,row,now):
    fish=row["fish"]
    child=breeding.fry(db,row["item"])
    if fish not in SPECIES:
        return None
    if breeding.adult(row,child):
        return now
    due=row["next_at"]
    if due is None:
        return None
    if child:
        return max(now,due+(breeding.STEPS-row["rounds"]-1)*pond_growth.SECONDS)
    state=dict(row)
    grams,grade=row["grams"],row["grade"]
    limit=pond_growth.cap(fish,row["original_grams"])
    while state["rounds"]<pond_growth.ROUNDS and grams<limit:
        grams,grade=pond_growth.advance(fish,state,grams,grade,row["level"],
                                        pond_growth.round_rng(row["item"],state["rounds"]))
        due+=pond_growth.SECONDS
    return max(now,due-pond_growth.SECONDS)


def refresh(db,key,now):
    pilot=db.execute("SELECT started FROM breed_pilots WHERE grp=? AND enabled=1",(key[0],)).fetchone()
    if not pilot:
        return
    now=max(now,pilot[0])
    old=db.execute("SELECT ready FROM breed_eligible WHERE grp=? AND member=?",key).fetchone()
    if old and old[0]<=now:
        return
    if now>=pilot[0]+WEEK:
        return
    species=defaultdict(list)
    for row in db.execute(pond_growth.SELECT+" AND p.member=?",key):
        stamp=ready_at(db,row,now)
        if stamp is not None:
            species[row["fish"]].append(stamp)
    earliest=min((sorted(times)[1] for times in species.values() if len(times)>=2),default=None)
    if earliest is None:
        db.execute("DELETE FROM breed_eligible WHERE grp=? AND member=?",key)
    else:
        db.execute("""INSERT INTO breed_eligible VALUES(?,?,?) ON CONFLICT(grp,member)
                      DO UPDATE SET ready=excluded.ready""",(*key,earliest))


def switch(db,group,on,now):
    if not on:
        db.execute("UPDATE breed_pilots SET enabled=0 WHERE grp=?",(group,))
        db.execute("DELETE FROM breed_previews WHERE grp=?",(group,))
        db.execute("DELETE FROM breed_eligible WHERE grp=? AND ready>?",(group,now))
        return
    db.execute("""INSERT INTO breed_pilots VALUES(?,?,1) ON CONFLICT(grp)
                  DO UPDATE SET enabled=1""",(group,now))
    for member, in db.execute("SELECT DISTINCT member FROM fishing_pond WHERE grp=? AND storage='pond'",(group,)).fetchall():
        refresh(db,(group,member),now)


def week(db,group,now):
    pilot=db.execute("SELECT started FROM breed_pilots WHERE grp=?",(group,)).fetchone()
    if not pilot:
        raise ValueError("该群没有繁育灰度记录")
    start=pilot[0]
    # 首周固定为半开区间；进行中包含当前时刻。
    import math
    end=min(start+WEEK,math.nextafter(now,math.inf))
    def scalar(sql,params):
        return db.execute(sql,params).fetchone()[0]
    args=(group,start,end)
    eligible=scalar("SELECT count(*) FROM breed_eligible WHERE grp=? AND ready>=? AND ready<?",args)
    first,second,fees=db.execute("""WITH people AS (SELECT member,count(*) n,sum(fee) fees FROM breed_pairs
             WHERE grp=? AND started>=? AND started<? GROUP BY member)
             SELECT count(*),coalesce(sum(n>=2),0),coalesce(sum(fees),0) FROM people""",args).fetchone()
    claimed,retained=db.execute("""WITH ordered AS (
        SELECT *,row_number() OVER(PARTITION BY member ORDER BY claimed_at,id) n FROM breed_pairs
        WHERE grp=? AND claimed_at>=? AND claimed_at<?)
        SELECT count(*),coalesce(sum(NOT EXISTS(SELECT 1 FROM breed_sales s WHERE s.item=o.offspring AND s.at<?)
          AND coalesce((SELECT t.member FROM breed_transfers t WHERE t.item=o.offspring AND t.at<?
            ORDER BY t.at DESC,t.id DESC LIMIT 1),o.member)=o.member),0)
        FROM ordered o WHERE n=1""",(*args,end,end)).fetchone()
    after_claim=scalar("""SELECT count(DISTINCT b.member) FROM breed_pairs b WHERE b.grp=? AND b.started>=?
        AND b.started<? AND EXISTS (SELECT 1 FROM breed_pairs p WHERE p.grp=b.grp AND p.member=b.member
        AND p.id<b.id AND p.claimed_at<=b.started)""",args)
    sales=scalar("SELECT coalesce(sum(price),0) FROM breed_sales WHERE grp=? AND at>=? AND at<?",args)
    return {"有两条同种成年塘鱼":eligible,"首次发起配对":first,"成功后领取":claimed,"留下首尾幼鱼":retained,
            "发起第二次配对":second,"首领后再次配对":after_claim,"实际配对费":fees,"育苗售鱼到账":sales,
            "实际鱼币净回收":fees-sales}


def sale(db,where,params,now):
    db.execute("""INSERT INTO breed_sales(item,grp,member,at,price)
                  SELECT id,grp,member,?,price FROM fishing_pond WHERE """+where+
               " AND EXISTS(SELECT 1 FROM breed_fry f WHERE f.item=fishing_pond.id)",(now,*params))
