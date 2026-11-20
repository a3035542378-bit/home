"""逐阶强化：基础品质随强化确定，两项附属性可分别重铸。"""
import time
import http.client
import logging
from urllib.parse import quote
import json
import random
import re

from .fish_receipts import grid

COMMANDS={"强化鱼竿","回退强化","强化玩法"}
GRADE_BY_LEVEL = {1: "普通", 2: "优良", 3: "稀有", 4: "史诗", 5: "传说"}
REFORGE=re.compile(r"重铸 (韧性|硬度)(?: ([1-5]))?")


def levels(db,key):
    return db.execute("SELECT * FROM rod_enhancements WHERE grp=? AND member=? ORDER BY tier",key).fetchall()


def weights(rod,rows):
    # 保持总权重不变，将普通鱼的部分权重转给稀有、珍品。
    rare=sum(r["quality"]+r["toughness"] for r in rows)*0.2
    prized=sum(r["hardness"] for r in rows)*0.2
    return (40-rare-prized,30,20,8*rod+rare,2*rod+prized)


def describe(rod,rows):
    active=[r for r in rows if r["tier"]<=rod]
    w=weights(rod,active)
    lines=[f"🔧 强化 {len(active)}/{rod} 阶",f"咬钩机会　稀有 {100*w[3]/sum(w):.2f}%",f"　　　　　珍品 {100*w[4]/sum(w):.2f}%"]
    for r in rows:
        lines.append(f"\n第 {r['tier']} 阶　各项上限 {r['tier']+2}\n强化品质 {r['quality']}　韧性 {r['toughness']}　硬度 {r['hardness']}"+(" 暂停" if r["tier"]>rod else ""))
    return "\n".join(lines)


def change(db,key,cmd,rod,event_id,prefix="二狗",now=None):
    rows=levels(db,key)
    depth=len(rows)
    match=REFORGE.fullmatch(cmd)
    tier=int(match[2]) if match and match[2] else depth
    rng=random.Random(event_id)
    if cmd=="强化玩法":
        return ("🔧 鱼竿强化\n鱼竿每升一级，可多强化一阶。\n第 N 阶每项随机 1～N+2 点。\n"
                "品质、韧性提高稀有鱼概率。\n硬度提高珍品概率。\n\n"
                "🔨 开新阶　强化鱼竿\n花费：10 × 新阶数 鱼币\n\n"
                "🎲 重抽一项属性\n重铸 韧性 1\n重铸 硬度 1\n花费：4 × 阶数 鱼币\n数值可能降低，省略阶数选最高阶。\n\n"
                "↩️ 移除最高阶　回退强化\n花费：3 × 最高阶数 鱼币\n低阶保留，重新强化可重抽品质。")
    if depth>rod:
        return "折竿后高阶强化已封存，先恢复竿等级再调整强化。"
    if cmd=="强化鱼竿":
        tier=depth+1
        if tier>rod:
            return "强化已达到当前竿等级上限。可重铸附属性，或先升级鱼竿。"
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
    cap=tier+2
    if cmd=="强化鱼竿":
        values=[rng.randint(1,cap) for _ in range(3)]
        change=f"新开第 {tier} 阶，强化品质 {values[0]}、韧性 {values[1]}、硬度 {values[2]}。"
        db.execute("INSERT INTO rod_enhancements VALUES(?,?,?,?,?,?)",(*key,tier,*values))
    elif match:
        column={"韧性":"toughness","硬度":"hardness"}[match[1]]
        old=next(r[column] for r in rows if r["tier"]==tier)
        value=rng.randint(1,cap)
        db.execute(f"UPDATE rod_enhancements SET {column}=? WHERE grp=? AND member=? AND tier=?",
                   (value,*key,tier))
        change=f"第 {tier} 阶{match[1]}：{old} → {value}。"
    else:
        change=f"已移除第 {tier} 阶，剩余 {tier-1} 阶。"
        db.execute("DELETE FROM rod_enhancements WHERE grp=? AND member=? AND tier=?",(*key,tier))
    return f"{cmd}成功，消耗 {cost} 鱼币。\n{change}\n"+describe(rod,levels(db,key))


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
