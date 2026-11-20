"""逐阶强化：基础品质随强化确定，三项附属性可分别重铸。"""
import time
import http.client
import logging
from urllib.parse import quote
import json
import random
import re

from . import angler, fishing_bait, rod_stats
from .fishing_waters import WATERS
from .fish_receipts import grid

COMMANDS={"强化鱼竿","回退强化","强化玩法"}
GRADE_BY_LEVEL = {1: "普通", 2: "优良", 3: "稀有", 4: "史诗", 5: "传说"}
REFORGE=re.compile(r"重铸 (韧性|硬度|幸运)(?: ([1-9][0-9]{0,2}))?")


def levels(db,key):
    return db.execute("SELECT * FROM rod_enhancements WHERE grp=? AND member=? ORDER BY tier",key).fetchall()


def weights(rod,rows):
    # 保持总权重不变，将普通鱼的部分权重转给稀有、珍品。
    luck=rod_stats.power(rows,"luck")
    rare=12*(rod_stats.power(rows,"quality")+luck)
    prized=8*luck
    return (40-rare-prized,30,20,8*rod+rare,2*rod+prized)


def trophy_bonus(rod, active):
    return 1 + .25*(rod-1) + .05*len(active) + 2*rod_stats.power(active,"luck")


def describe(db,key,rod,area):
    rows=levels(db,key)
    active=rod_stats.active_levels(rod,rows)
    bonus=trophy_bonus(rod,active)
    chances=fishing_bait.distribution(WATERS[area],weights(rod,active),fishing_bait.BAITS["免费鱼饵"],bonus)
    lines=[f"🔧 当前强化 {len(active)}/{rod*rod_stats.STAGES_PER_GRADE} 阶"]
    if active:
        current=active[-1]
        low,high=rod_stats.bounds(current["tier"])
        casts=db.execute("""SELECT COALESCE(
            (SELECT casts FROM fishing_experience WHERE grp=? AND member=?),
            (SELECT count FROM fishing_records WHERE grp=? AND member=?),0)""",(*key,*key)).fetchone()[0]
        slip=angler.slip_percent(casts,area=="新手池塘",False,rod_stats.power(active,"hardness"))
        lines.extend([f"本阶属性范围 {low}～{high}",
                      f"品质 {current['quality']}　幸运 {current['luck']}",
                      f"韧性 {current['toughness']}　硬度 {current['hardness']}",
                      f"累计少磨损 {50*rod_stats.power(active,'toughness'):.3f}%",
                      f"下竿常规鱼脱钩率 {slip:.4g}%"])
    if len(rows)>len(active):
        lines.append(f"封存 {len(rows)-len(active)} 阶，恢复竿级后生效。")
    lines.extend(["",f"🎣 常规咬钩率 · {area} · 免费饵"])
    for tier in ("普通","稀有","珍品","史诗","传说"):
        chance=chances.get(tier)
        value=f"{chance:.4f}".rstrip("0").rstrip(".")+"%" if chance is not None else "本场无此鱼种"
        lines.append(f"{tier}　{value}")
    return "\n".join(lines)


def change(db,key,cmd,rod,event_id,prefix,now,area):
    rows=levels(db,key)
    depth=len(rows)
    match=REFORGE.fullmatch(cmd)
    tier=int(match[2]) if match and match[2] else depth
    rng=random.Random(event_id)
    if cmd=="强化玩法":
        from .feature_menu import TOPICS
        return next(topic.body for topic in TOPICS if topic.name=="强化")
    if depth>rod*rod_stats.STAGES_PER_GRADE:
        return "折竿后高阶强化已封存，先恢复竿等级再调整强化。"
    if cmd=="强化鱼竿":
        tier=depth+1
        if tier>rod*rod_stats.STAGES_PER_GRADE:
            return "已达本竿强化上限，可重铸当前阶的属性。"
        cost=10*tier
    elif not 1<=tier<=depth:
        return "该强化阶尚未开启。"
    else:
        cost=(4 if match else 3)*tier
    paid=db.execute("UPDATE fishing_wallets SET coins=coins-? WHERE grp=? AND member=? AND coins>=?",
                    (cost,*key,cost))
    if not paid.rowcount:
        from .fish_storage import shortfall
        return shortfall(db,key,cost,prefix,now or time.time(),"本次强化")
    low,cap=rod_stats.bounds(tier)
    if cmd=="强化鱼竿":
        values=[rng.randint(low,cap) for _ in rod_stats.FIELDS]
        change=f"已开启第 {tier} 阶。"
        db.execute("INSERT INTO rod_enhancements VALUES(?,?,?,?,?,?,?)",(*key,tier,*values))
    elif match:
        column={"韧性":"toughness","硬度":"hardness","幸运":"luck"}[match[1]]
        old=next(r[column] for r in rows if r["tier"]==tier)
        value=rng.randint(low,cap)
        db.execute(f"UPDATE rod_enhancements SET {column}=? WHERE grp=? AND member=? AND tier=?",
                   (value,*key,tier))
        change=f"第 {tier} 阶{match[1]}：{old} → {value}。"
    else:
        change=f"已移除第 {tier} 阶，剩余 {tier-1} 阶。"
        db.execute("DELETE FROM rod_enhancements WHERE grp=? AND member=? AND tier=?",(*key,tier))
    return f"{cmd}成功，消耗 {cost} 鱼币。\n{change}\n"+describe(db,key,rod,area)


ASSET_RANKS = """WITH pond AS (SELECT member,sum(price) value FROM fishing_pond WHERE grp=? GROUP BY member),
        assets AS (SELECT w.member,w.coins+coalesce(p.value,0) total FROM fishing_wallets w LEFT JOIN pond p
        ON p.member=w.member WHERE w.grp=?), ranked AS (SELECT *,rank() OVER(ORDER BY total DESC) place FROM assets)
        SELECT * FROM ranked ORDER BY total DESC,member"""

def refresh_names(db,client,group):
    from .display_names import refresh
    refresh(db,client,group,[r["member"] for r in db.execute(ASSET_RANKS+" LIMIT 10",(group,group))])


def leaderboard(db,group,member):
    rows=db.execute(ASSET_RANKS,(group,group))
    from .display_names import labels
    name_for=labels(db,group)
    lines=["🏆 本群资产榜","鱼币余额＋鱼包和鱼塘售价",""]
    entries=[]
    mine="你还未入榜。"
    for idx,row in enumerate(rows):
        if row["member"]==member:
            mine=f"你排第 {row['place']}，资产 {row['total']} 鱼币。"
        if idx<10:
            name=name_for(row["member"])
            if name=="一位群成员":
                name="你" if row["member"]==member else "昵称暂不可用"
            entries.append((f"第 {row['place']} 名",name,f"{row['total']} 鱼币"))
    return "\n".join([*lines,*grid(entries),"","📍 "+mine])
