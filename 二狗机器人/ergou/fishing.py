"""本群成员的钓鱼记录；随入站消息在同一事务提交。"""
import math
import random
import re
from . import breed_metrics, breeding, exhibit_board, pond_growth, angler, fish_grades, fish_storage, fishing_bait, giant_fish, pond_raids
from .db import DEFAULT
from . import rod as gear

COMMANDS = {"图鉴榜", "切换水域", "鱼获品级", "巨物鱼讯", "钓鱼信息", "钓手等级", "钓鱼等级", "钓鱼", "抛竿", "我的鱼获", "钓鱼玩法", "鱼塘", "鱼市","鱼线","买鱼线","购买鱼线","升级鱼线","水域","切换水域 新手池塘","切换水域 外海","重量榜","重量排行榜","鱼类图鉴","钓鱼图鉴","图鉴", "一键卖鱼", "升级鱼竿", "我的鱼竿","资产榜","资产排行榜"} | gear.COMMANDS
# 名称、最轻/最重克数、基础价格、每公斤加价、稀有度
from .fishing_waters import FISH, HABITAT, TROPHY_PERCENT, WATERS, giant_min, guide, size_grade, weight
RARITY_ICONS = {"普通": "🐟", "稀有": "💎", "珍品": "👑", "史诗": "🔮", "传说": "🌟"}
BOOK_PAGE = re.compile(r"(?P<kind>全图鉴|图鉴|鱼类图鉴|钓鱼图鉴|普通图鉴|稀有图鉴|珍品图鉴|史诗图鉴|传说图鉴|巨物图鉴)"
                       r"(?:\s+(?P<area>[\u4e00-\u9fff]+))?(?:\s+(?P<page>[1-9][0-9]{0,3}))?")


def directory(best, exhibits, picks, prefix, honors):
    found = sum(row[0] in best for row in FISH)
    lit = sum(row[0] in exhibits for row in FISH)
    lines = [f"📖 全图鉴 · {len(WATERS)} 处钓场",
             f"✨ 已点亮 {lit}/{len(FISH)} 种　🐾 已发现 {found}/{len(FISH)} 种", honors, ""]
    for rarity, icon in RARITY_ICONS.items():
        species = [row for row in FISH if row[-1] == rarity]
        names = [species[i][0] for i in (0,len(species)//2,-1)]
        lines.extend([f"{icon} {rarity} · {len(species)} 种\n{prefix}{rarity}图鉴",
                      "　" + "、".join(names)])
    lines.extend(["", f"🐋 {prefix}巨物图鉴", "　本场每种鱼都可能成为活动目标", "　巨物鲤鱼 · 12～25 公斤",
                  "　"+ "、".join(row[0] for row in sorted(FISH,key=giant_min,reverse=True)[:2]),
                  "", f"逐条查看\n{prefix}全图鉴 1"])
    if picks:
        lines.extend(["", "🎒 手里的鱼"])
        for fish,item in list(picks.items())[:2]:
            action="换展" if fish in exhibits else "点亮"
            lines.append(f"{fish}{action}\n{prefix}收入图鉴#{item}")
    return "\n".join(lines)


def book(db,key,match,current_area,prefix):
    kind=match["kind"]
    area=match["area"]
    category=kind.removesuffix("图鉴")
    local=kind in ("图鉴","鱼类图鉴","钓鱼图鉴")
    if area in (*RARITY_ICONS,"巨物") and (local or kind=="全图鉴"):
        category,area,local=area,None,False
    home=local and not area and not match["page"]
    area=area or (current_area if local else None)
    if area and area not in WATERS:
        return f"未找到钓场。发「{prefix}水域」查看名称。"
    catalog=WATERS[area] if area else FISH
    records = {r["fish"]: r for r in db.execute(
        "SELECT fish,best_grams,best_grade,best_grade_upgraded FROM fishing_species WHERE grp=? AND member=?", key)}
    displays = {r["fish"]: r for r in db.execute(
        """SELECT e.*,g.catcher,g.rounds,f.breeder,f.firstborn FROM fishing_exhibits e LEFT JOIN pond_growth g ON g.item=e.item_id LEFT JOIN breed_fry f ON f.item=e.item_id
           WHERE e.grp=? AND e.member=?""", key)}
    best = {fish: r["best_grams"] for fish, r in records.items()}
    exhibits = {fish: r["grams"] for fish, r in displays.items()}
    giants=category=="巨物"
    if giants:
        catalog=sorted(catalog,key=lambda row:(row[0]!="鲤鱼",-giant_min(row)))
    elif category in RARITY_ICONS:
        catalog=[row for row in catalog if row[-1]==category]
    if not catalog:
        return f"{area}没有{category}鱼。发「{prefix}{category}图鉴」查看出没钓场。"
    page=int(match["page"] or 1)
    pages=(len(catalog)+5)//6
    if page>pages:
        return f"图鉴共 {pages} 页。"
    thresholds={row[0]:giant_min(row) if giants else 1 for row in catalog}
    found=sum(best.get(name,0)>=limit for name,limit in thresholds.items())
    lit=sum(exhibits.get(name,0)>=limit for name,limit in thresholds.items())
    category_title=category if giants or category in RARITY_ICONS else ""
    title=(area or "")+category_title or "鱼类"
    lines=[f"📖 {title}图鉴 {page}/{pages}",
           f"✨ 已点亮 {lit}/{len(catalog)} 种　🐾 已发现 {found}/{len(catalog)} 种", ""]
    bag_used,bag_limit,_=fish_storage.occupancy(db,key,"bag")
    picks={}
    for row in db.execute("""SELECT fish,id,grams,storage FROM fishing_pond
                             WHERE grp=? AND member=? ORDER BY grams DESC,id""",key):
        fish=row["fish"]
        if fish not in thresholds or row["grams"]<thresholds[fish] or row["grams"]<=exhibits.get(fish,0):
            continue
        if fish in exhibits and row["storage"]=="pond" and bag_used>=bag_limit:
            continue
        picks.setdefault(fish,row["id"])
    if kind=="全图鉴" and category=="全" and not area and not match["page"]:
        return directory(best, exhibits, picks, prefix, fish_grades.honors(db, key[0]))
    if home:
        missing=[row[0] for row in catalog if row[0] not in exhibits]
        lines[0]=f"📖 当前钓场 · {area}"
        lines.insert(2, fish_grades.honors(db,key[0]))
        if missing:
            lines.append(f"◇ 未点亮 {len(missing)} 种")
            for rarity in RARITY_ICONS:
                names=[row[0] for row in catalog if row[-1]==rarity and row[0] not in exhibits]
                for i in range(0,len(names),3):
                    lines.append((rarity+"　" if i==0 else "　　　")+"、".join(names[i:i+3]))
        else:
            lines.append("🏅 本钓场已集齐")
        ready=[fish for fish in picks if HABITAT.get(fish)==area][:2]
        for fish in ready:
            action="可换展" if fish in exhibits else "可点亮"
            lines.extend([f"{fish}{action}",f"{prefix}收入图鉴#{picks[fish]}"])
        lines.extend(["",f"查看本场　{prefix}图鉴 {area}",f"全部钓场　{prefix}全图鉴",
                      f"🐋 看巨物图鉴和鱼讯\n{prefix}巨物图鉴\n{prefix}巨物鱼讯"])
        return "\n".join(lines)
    visible=catalog[(page-1)*6:page*6]
    if giants and page==1:
        lines.append("体型：小型 / 标准 / 大型 / 巨物")
    lines.append("✨ 已展出　🐾 亲钓纪录　◇ 待发现")
    actions=[]
    for row in visible:
        fish,rarity=row[0],row[-1]
        caught=best.get(fish,0)>=thresholds[fish]
        shown=exhibits.get(fish,0)>=thresholds[fish]
        icon="✨" if shown else "🐾" if caught else "◇"
        name=f"巨物{fish}" if giants else fish
        lines.append(f"{icon} {name}（{rarity}）")
        if giants:
            lines.append(f"　{HABITAT[fish]} · {weight(thresholds[fish])}起")
        elif category in TROPHY_PERCENT:
            lines.append(f"　{HABITAT[fish]} · {weight(row[1])}～{weight(row[2])}")
        if shown:
            grams=exhibits[fish]
            display = displays[fish]
            quality = fish_grades.label(display["grade"], display["grade_upgraded"])
            source = "亲钓" if display["catcher"] == key[1] else "群友钓获" if display["catcher"] else "历史来源未记录"
            if display["breeder"] is not None:
                source = breeding.source(display,key[1])
            elif display["rounds"]:
                source += "后塘养"
            lines.append("　来源 "+source)
            lines.append(f"　已点亮 {weight(grams)} · {size_grade(fish,grams)}" + (" · " + quality if quality else ""))
        if caught and not shown and not giants and category not in TROPHY_PERCENT:
            lines[-1]+=f"　{weight(best[fish])} · {size_grade(fish,best[fish])}"
        elif caught and (not shown or best[fish]!=exhibits[fish]):
            lines.append(f"　个人纪录 {weight(best[fish])} · {size_grade(fish,best[fish])}")
        elif shown:
            lines.append("　亲钓同重" if caught else "　尚无亲钓纪录")
        if caught:
            record = records[fish]
            quality = fish_grades.label(record["best_grade"], record["best_grade_upgraded"])
            if quality:
                lines.append("　最高品级 " + quality)
        if fish in picks:
            action="换展" if fish in exhibits else "点亮"
            actions.append(f"{fish}{action}\n{prefix}收入图鉴#{picks[fish]}")
    if actions:
        lines.extend(["","🎒 可收藏",*actions])
    lines.append("")
    if page<pages:
        command=category_title+"图鉴" if category_title else "图鉴" if area else "全图鉴"
        if area:
            command+=" "+area
        lines.append(f"下页\n{prefix}{command} {page+1}")
    lines.append(f"巨物出没　{prefix}巨物鱼讯" if giants else f"查钓法\n{prefix}{visible[0][0]}怎么钓？")
    return "\n".join(lines)


FISH_QUESTION=re.compile(r"(?:怎么钓到|怎么钓|在哪(?:里)?(?:能|可以)?钓到|哪里能钓到|(?:怎么|如何)(?:获得|获取))\s*(.+?)|(.+?)\s*(?:怎么钓到|怎么钓|在哪(?:里)?(?:能|可以)?钓(?:到)?|(?:怎么|如何)(?:获得|获取)|的获取方式)")


def requested_fish(cmd):
    phrase=cmd.rstrip("。！？!?").strip()
    if phrase.startswith("鱼种查询 "):
        return phrase.removeprefix("鱼种查询 ").strip().removeprefix("巨物")
    question=FISH_QUESTION.fullmatch(phrase)
    if question:
        name=(question[1] or question[2]).strip()
        name = name.removeprefix("巨物")
        if name in HABITAT:
            return name
    return None


def catch_guide(name,prefix):
    area=HABITAT.get(name)
    if area is None:
        return f"图鉴里没找到「{name}」。发「{prefix}图鉴」查看鱼名。"
    species=next(row for row in WATERS[area] if row[0]==name)
    _,low,high,_,_,rarity=species
    extra=(f"\n🌊 巨物鲤鱼 12～25 公斤" if name=="鲤鱼" else f"\n🌊 巨物门槛　{weight(giant_min(species))}")
    if rarity in TROPHY_PERCENT:
        extra+=f"\n免费饵常规咬钩率 {TROPHY_PERCENT[rarity]:g}%\n⚠️ 重鱼可能断线或折竿。"
    return (f"🐟 {name}（{rarity}）\n⚖️ 重量　{weight(low)}～{weight(high)}\n"
            f"📍 在{area}随机上钩{extra}\n本场可刷到它的巨物　{prefix}巨物鱼讯\n\n前往　{prefix}切换水域 {area}\n开钓　{prefix}抛竿\n"
            f"🎒 钓到后选鱼点亮　{prefix}查看鱼包")


def heavy_board(db,key):
    from .display_names import labels
    names=labels(db,key[0])
    rows=db.execute("""WITH ranked AS (SELECT member,best_name,best_grams,
        rank() OVER(ORDER BY best_grams DESC) place FROM fishing_records WHERE grp=?)
        SELECT * FROM (SELECT * FROM ranked ORDER BY place,member LIMIT 10)
        UNION SELECT * FROM ranked WHERE member=? ORDER BY place,member""",key)
    lines=["🏆 本群单尾重量榜"]
    mine="你还没有上榜鱼获。"
    for idx,r in enumerate(rows):
        if idx<10:
            lines.append(f"{r['place']}. {names(r['member'])} · {r['best_name']} {weight(r['best_grams'])}")
        if r['member']==key[1]:
            mine=f"你的纪录：第 {r['place']} 名，{weight(r['best_grams'])}。"
    return "\n".join([*lines,"","📍 "+mine])


LINE_COST=(0,25,60,140,300)
LINE_BASE=(4000,8000,15000,25000,40000)


def line_capacity(level,rod,levels):
    return LINE_BASE[level-1]+1500*rod+250*sum(r["toughness"] for r in levels)


def fight(rng,grams,rod,levels,line_level=1):
    line_limit=line_capacity(line_level,rod,levels)
    rod_limit=6000+2200*rod+400*sum(r["hardness"] for r in levels)
    if grams>rod_limit and rng.random()<min(.55,(grams/rod_limit-1)*.4):
        return "竿"
    if line_level<len(LINE_BASE) and grams>line_limit and rng.random()<min(.75,(grams/line_limit-1)*.5):
        return "线"
    return None



HELP_COMMANDS = {"钓鱼玩法", "钓鱼帮助", "钓鱼怎么玩", "怎么钓鱼", "如何钓鱼"}


def help_requested(cmd):
    return cmd.rstrip("。！？!?").strip() in HELP_COMMANDS


def matches(cmd):
    return breeding.matches(cmd) or pond_raids.matches(cmd) or cmd=="鱼饵" or (cmd.startswith(("抛竿 ","钓鱼 ")) and cmd.endswith("鱼饵")) or help_requested(cmd) or cmd=="钓鱼进阶" or cmd in ("海域","海域列表","水域列表") or cmd.startswith(("切换水域 ","切换海域 ","水域介绍 ","海域介绍 ")) or cmd in COMMANDS or BOOK_PAGE.fullmatch(cmd) or gear.REFORGE.fullmatch(cmd) or fish_storage.matches(cmd) or requested_fish(cmd)


def full_bag_notice(count,capacity,prefix):
    return f"🎒 鱼包已满（{count}/{capacity} 条），先腾出 {count-capacity+1} 格再钓。\n{prefix}查看鱼包"


def line_help(db, key, coins, area, prefix, now, heading="鱼线已断"):
    if coins>=3:
        return f"🧵 {heading}。换线扣 3 鱼币，余额 {coins} 鱼币。\n{prefix}买鱼线"
    held = db.execute("SELECT 1 FROM fishing_pond WHERE grp=? AND member=? LIMIT 1",key).fetchone()
    if held:
        step = f"{prefix}卖鱼\n可先免费查看一条鱼的售价。"
    elif area!="新手池塘":
        step = f"{prefix}切换水域 新手池塘\n回塘免费，备用线能钓普通鱼。"
    else:
        step = fish_storage.cast_step(db,key,prefix,now)+"\n备用线能钓新手池塘的普通鱼。"
    return f"🧵 {heading}。换线需 3 鱼币，余额 {coins}，还差 {3-coins} 币。\n{step}"


def play(db, event, cmd, prefix, cfg, *, batch_ids=None):
    if event["adapter_version"]=="agent-wechat-events/2.7.1":
        from .display_names import mention_sender
        mention_sender(db,event)
    if cmd in ("资产榜","资产排行榜"):
        pond_growth.settle(db,event["grp"],event["arrived"])
        return gear.leaderboard(db,event["grp"],event["member"])
    if not cfg["games"] or "钓鱼" in cfg.get("disabled_games",[]):
        raise ValueError(f"本群已关闭钓鱼，查看可用功能\n{prefix}菜单")
    key = (event["grp"], event["member"])
    pilot = breeding.enabled(db,key[0])
    cooldown = cfg.get("fishing_cooldown_seconds", DEFAULT["fishing_cooldown_seconds"])
    if cmd=="鱼获品级":
        return ("🏷️ 每条鱼入包时抽一次品级，小鱼也能升传说。\n"
                "✨ 升品提高售价，刷新本群同种鱼的品级纪录可得积分。\n"
                "🌊 活动目标额外升一级，有机会出神话。\n"
                f"📖 看展品和本群喜报　{prefix}图鉴")
    if cmd=="鱼饵":
        return fishing_bait.menu(db,key,prefix)
    if help_requested(cmd):
        from .feature_menu import fishing_directory
        return fishing_directory(prefix,cooldown,pilot)
    if cmd=="钓鱼进阶":
        from .feature_menu import find_topic
        return find_topic(cmd).body.format(p=prefix)
    if cmd=="偷鱼玩法":
        return pond_raids.play(db,event,cmd,prefix)
    breeding.resolve(db,key,event["arrived"])
    if batch_ids is not None:
        from . import exhibit_batch
        pond_growth.settle(db,key[0],event["arrived"],key[1])
        reply=exhibit_batch.render(db,key,prefix,event["arrived"],batch_ids)
        if pilot:
            breed_metrics.refresh(db,key,event["arrived"])
        return reply
    if breeding.matches(cmd):
        reply=breeding.play(db,key,event,cmd,prefix)
        if pilot:
            breed_metrics.refresh(db,key,event["arrived"])
        return reply
    if cmd == "图鉴榜":
        return exhibit_board.board(db,key,prefix)
    if pond_raids.matches(cmd):
        return pond_raids.play(db,event,cmd,prefix)
    if fish_storage.matches(cmd):
        reply=fish_storage.handle(db,key,cmd,prefix,event["arrived"])
        if pilot:
            breed_metrics.refresh(db,key,event["arrived"])
        return reply
    location=db.execute("SELECT area FROM fishing_waters WHERE grp=? AND member=?",key).fetchone()
    area=location[0] if location else "新手池塘"
    if cmd=="切换水域":
        names=list(WATERS)
        rows=["、".join(names[i:i+3]) for i in range(0,len(names),3)]
        return "\n".join(["🌊 想去哪里钓鱼？",f"📍 当前　{area}","当前可去",*rows,"",
                          f"例如回到新手池塘，发送\n{prefix}切换钓场 新手池塘"])
    if cmd=="巨物鱼讯":
        now=event["arrived"]
        sighting=giant_fish.current(db,key[0],area,now)
        if sighting.taken:
            return giant_fish.departure(key[0],area,sighting)
        return f"📍 {area} · 本场每种鱼都可能出没\n{sighting.notice(now, area, prefix=prefix)}"
    if cmd in ("水域","海域","水域列表","海域列表"):
        names=list(WATERS)
        rows=["、".join(names[i:i+3]) for i in range(0,len(names),3)]
        return (f"🗺 钓场地图　{len(names)} 处\n📍 当前：{area}\n免费切换，新手塘常规鱼获免损。\n\n"+"\n".join(rows)
                +f"\n\n看鱼种　{prefix}水域介绍 外海\n看进度　{prefix}图鉴 外海\n去钓鱼　{prefix}切换水域 外海")
    if cmd.startswith(("水域介绍 ","海域介绍 ")):
        target=cmd.split(maxsplit=1)[1]
        return guide(target) if target in WATERS else "未找到钓场。发「水域」查看名称。"
    if cmd=="鱼市":
        return f"🪙 {area}鱼市\n售价＝基础价 × 体重系数 × 品级系数\n\n"+"\n".join(
            f"{name}（{rarity}）基础 {base} 币" for name,_,_,base,rate,rarity in WATERS[area])
    if cmd in ("重量榜","重量排行榜"):
        return heavy_board(db,key)
    page=BOOK_PAGE.fullmatch(cmd)
    if page:
        pond_growth.settle(db,key[0],event["arrived"],key[1])
        return book(db,key,page,area,prefix)
    name=requested_fish(cmd)
    if name:
        return catch_guide(name,prefix)
    record = db.execute("SELECT * FROM fishing_records WHERE grp=? AND member=?", key).fetchone()
    if cmd in ("钓手等级","钓鱼等级"):
        return angler.profile(db,key,record["count"] if record else 0,area)
    if cmd == "我的鱼获":
        if not record:
            return f"鱼篓还是空的。发「{prefix} 钓鱼」试试第一竿。"
        return (f"🧺 我的鱼获\n累计 {record['count']} 条　共 {weight(record['grams'])}\n\n"
                f"🏆 最重纪录\n{record['best_name']}　{weight(record['best_grams'])}")
    if cmd!="钓鱼信息":
        db.execute("INSERT OR IGNORE INTO fishing_wallets(grp,member) VALUES(?,?)",key)
    wallet=db.execute("SELECT coins,rod FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()
    coins,rod=wallet if wallet else (30,1)
    offshore=area!="新手池塘"
    if cmd.startswith(("切换水域 ","切换海域 ")):
        target=cmd.split(maxsplit=1)[1]
        if target not in WATERS:
            return f"未找到钓场。查看可以去的水域\n{prefix}切换钓场"
        db.execute("""INSERT INTO fishing_waters(grp,member,area) VALUES(?,?,?) ON CONFLICT(grp,member)
                      DO UPDATE SET area=excluded.area""",(*key,target))
        return guide(target)
    tackle=db.execute("SELECT broken,last_attempt FROM fishing_tackle WHERE grp=? AND member=?",key).fetchone()
    broken=bool(tackle and tackle["broken"])
    saved=db.execute("SELECT level FROM fishing_line_levels WHERE grp=? AND member=?",key).fetchone()
    line_level=saved[0] if saved else 1
    if cmd=="钓鱼信息":
        bag,bag_limit,_=fish_storage.occupancy(db,key,"bag")
        pond,pond_limit,_=fish_storage.occupancy(db,key,"pond")
        landed=record["count"] if record else 0
        best=f"{record['best_name']}　{weight(record['best_grams'])}" if record else "暂无鱼获"
        growth=angler.profile(db,key,landed,area)
        return (f"📋 我的钓鱼信息\n{growth}\n\n"
                f"🪙 当前余额　{coins} 鱼币\n🧰 鱼竿 {rod} 级　鱼线 {line_level} 级"
                f"（{'已断' if broken else '完好'}）\n🎒 鱼包 {bag}/{bag_limit} 条　鱼塘 {pond}/{pond_limit} 条\n"
                f"🐟 累计钓获　{landed} 条\n🏆 最重纪录　{best}\n\n处理鱼获\n{prefix}查看鱼包")
    if cmd in ("鱼线","升级鱼线"):
        if cmd=="升级鱼线":
            if line_level==len(LINE_COST):
                return "鱼线已满 5 级，抛竿时不会断线。"
            if broken:
                return line_help(db,key,coins,area,prefix,event["arrived"])
            cost=LINE_COST[line_level]
            if coins<cost:
                return fish_storage.shortfall(db,key,cost,prefix,event["arrived"],"升级")
            db.execute("UPDATE fishing_wallets SET coins=coins-? WHERE grp=? AND member=?",(cost,*key))
            line_level+=1
            db.execute("""INSERT INTO fishing_line_levels VALUES(?,?,?) ON CONFLICT(grp,member)
                          DO UPDATE SET level=excluded.level""",(*key,line_level))
        if broken:
            return line_help(db,key,coins,area,prefix,event["arrived"],f"{line_level} 级鱼线已断")
        levels=[r for r in gear.levels(db,key) if r["tier"]<=rod]
        limit=line_capacity(line_level,rod,levels)/1000
        effect="满级免断线；鱼竿仍可能折断。" if line_level==len(LINE_COST) else (
            f"安全承重 {limit:g} 公斤\n升级需要 {LINE_COST[line_level]} 鱼币。")
        paid=f"升级成功，消耗 {cost} 鱼币。\n" if cmd=="升级鱼线" else ""
        remaining=coins-cost if paid else coins
        if line_level<len(LINE_COST) and remaining>=LINE_COST[line_level]:
            effect+=f"\n发送即扣费升级\n{prefix}升级鱼线"
        return f"{paid}🧵 鱼线 {line_level} 级　完好\n{effect}"
    if cmd in ("买鱼线","购买鱼线"):
        if not broken:
            return "鱼线完好，无需购买。"
        if coins<3:
            return line_help(db,key,coins,area,prefix,event["arrived"])
        db.execute("UPDATE fishing_wallets SET coins=coins-3 WHERE grp=? AND member=?",key)
        db.execute("UPDATE fishing_tackle SET broken=0 WHERE grp=? AND member=?",key)
        return "新鱼线已装好，消耗 3 鱼币。"
    if cmd in gear.COMMANDS or gear.REFORGE.fullmatch(cmd):
        return gear.change(db,key,cmd,rod,event["event_id"],prefix,event["arrived"])
    upgrade=20*rod
    if cmd=="我的鱼竿":
        next_level=f"下级升级费 {upgrade} 币" if rod<5 else "已满级"
        if rod<5 and coins>=upgrade:
            next_level+=f"，发送即升级\n{prefix}升级鱼竿"
        return f"🎣 鱼竿 {rod} 级\n🪙 余额 {coins} 鱼币\n{next_level}\n\n"+gear.describe(rod,gear.levels(db,key))
    if cmd=="升级鱼竿":
        if rod==5:
            return "鱼竿已满 5 级。"
        if coins<upgrade:
            return fish_storage.shortfall(db,key,upgrade,prefix,event["arrived"],"升级")
        db.execute("UPDATE fishing_wallets SET coins=coins-?,rod=rod+1 WHERE grp=? AND member=?",(upgrade,*key))
        return f"鱼竿升到 {rod+1} 级，稀有鱼和珍品鱼出现机会提高。剩余 {coins-upgrade} 鱼币。"
    bait_name = cmd.partition(" ")[2].strip() or "免费鱼饵"
    bait = fishing_bait.BAITS.get(bait_name)
    if bait is None:
        return f"没有这种鱼饵。发「{prefix}鱼饵」查看名称和用法。"
    bag_count, bag_capacity, _ = fish_storage.occupancy(db,key,"bag")
    if bag_count >= bag_capacity:
        return full_bag_notice(bag_count,bag_capacity,prefix)
    now = event["arrived"]
    if broken and offshore:
        return line_help(db,key,coins,area,prefix,now)
    last=tackle["last_attempt"] if tackle else record["last_cast"] if record else None
    if last is not None and now < last + cooldown:
        return f"🎣 鱼窝还没静下来，{math.ceil(last+cooldown-now)} 秒后再来。"
    receipt = ""
    if bait.points:
        available = fishing_bait.balance(db,key)
        if available < bait.points:
            return (f"🪱 {bait_name}需要 {bait.points} 积分，你有 {available} 积分。\n"
                    f"还差 {bait.points-available} 分。免费开钓\n{prefix}抛竿")
        db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                      VALUES(?,?,0,'鱼饵',?,'bait/1',?,?,?)""",
                   (*key,-bait.points,event["event_id"],now,bait_name))
        receipt = f"\n🪱 {bait_name}　−{bait.points} 积分，扣饵后余 {available-bait.points} 分"
    rng = random.Random(event["event_id"])
    levels=[row for row in gear.levels(db,key) if row["tier"]<=rod]
    weights=gear.weights(rod,levels)
    rarity=fishing_bait.choose_rarity(rng,WATERS[area],weights,bait)
    pool=[item for item in WATERS[area] if item[-1]==rarity]
    fish,low,high,_,_,rarity=rng.choice(pool)
    grams = round(rng.triangular(low, high, low+(high-low)*bait.weight_mode))
    sighting=giant_fish.current(db,key[0],area,now)
    special=giant_fish.encounter(sighting,area,now,event["event_id"])
    if special:
        species,grams=special
        fish,_,_,_,_,rarity=species
    if sighting.taken and fish==sighting.fish:
        grams=min(grams,giant_fish.giant_min(giant_fish.SPECIES[fish])-1)
    grade=size_grade(fish,grams)
    db.execute("""INSERT INTO fishing_tackle VALUES(?,?,0,?) ON CONFLICT(grp,member)
                  DO UPDATE SET last_attempt=excluded.last_attempt""",(*key,now))
    pond_growth.mark(db,key,now,"cast")
    casts = angler.advance(db,key,record["count"] if record else 0)
    footer = receipt+"\n"+angler.progress(casts)
    progress_footer=footer
    if not sighting.taken and sighting.start-giant_fish.LEAD<=now<sighting.start+giant_fish.DURATION:
        footer+="\n"+sighting.notice(now, area)
    if broken and grade=="巨物":
        return line_help(db,key,coins,area,prefix,now,f"巨物{fish}游走了，备用线拉不住它")+footer
    heavy_encounter=grade=="巨物" or rarity in TROPHY_PERCENT
    risk=heavy_encounter or (offshore and record and record["count"]>=2)
    damage=fight(rng,grams,rod,levels,line_level) if risk else None
    if damage=="线":
        db.execute("UPDATE fishing_tackle SET broken=1 WHERE grp=? AND member=?",key)
        return line_help(db,key,coins,area,prefix,now,"鱼线断了")+footer
    if damage=="竿":
        new_level=max(1,rod-1)
        db.execute("UPDATE fishing_wallets SET rod=? WHERE grp=? AND member=?",(new_level,*key))
        return f"你稳住竿柄，{fish}又猛地一挣。\n🎣 鱼竿折断！换用 {new_level} 级竿。\n高阶强化已封存，升回原等级可恢复。"+footer
    chance = angler.slip_percent(casts-1, not offshore, heavy_encounter)
    if chance and rng.random() < chance/100:
        story=f"水面翻起一大片浪花，巨物{fish}甩开了钩。" if grade=="巨物" else rng.choice(angler.SLIPPED)
        if rarity in TROPHY_PERCENT:
            story=f"{RARITY_ICONS[rarity]} {rarity}鱼「{fish}」翻出水面，甩开了钩。"
        return story+"\n💨 脱钩了，下竿再试试！"+footer
    event_fish = sighting.active(now) and fish == sighting.fish and grade == "巨物"
    quality = fish_grades.final_grade(fish, grams, event["event_id"], event_fish)
    points = fish_grades.award_first_grade_points(db, key, fish, grams, quality, event)
    db.execute("""INSERT INTO fishing_records(grp,member,count,grams,best_name,best_grams,last_cast)
                  VALUES(?,?,1,?,?,?,?) ON CONFLICT(grp,member) DO UPDATE SET
                  count=count+1, grams=grams+excluded.grams,
                  best_name=CASE WHEN excluded.grams>best_grams THEN excluded.best_name ELSE best_name END,
                  best_grams=max(best_grams,excluded.grams), last_cast=excluded.last_cast""",
               (*key, grams, fish, grams, now))
    price = fish_grades.price(fish, grams, quality.final)
    item = db.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,grade,grade_upgraded,storage)
                         VALUES(?,?,?,?,?,?,?,'bag')""", (*key,fish,grams,price,quality.final,quality.upgraded)).lastrowid
    pond_growth.register(db,item,key[1])
    if event_fish:
        db.execute("""INSERT INTO fishing_giant_claims(grp,area,start) VALUES(?,?,?)
                      ON CONFLICT(grp,area) DO UPDATE SET start=excluded.start""",(key[0],area,sighting.start))
        footer=progress_footer+"\n"+giant_fish.departure(key[0],area,sighting)
    story = rng.choice(angler.HEAVY_CATCH if grams>=5000 else angler.LIGHT_CATCH)
    news = fish_grades.announcement(db, key, fish, grams, quality, event_fish)
    if news:
        story = news + "\n" + story
    badge = fish_grades.label(quality.final, quality.upgraded)
    reward = f"\n🎁 {fish}品级新高　＋{points} 积分" if points else ""
    used=bag_count+1
    bag_label = "鱼包已满" if used==bag_capacity else "鱼包"
    grade_line = f"\n🏷️ 品级 {badge}" if quality.upgraded or badge!="普通" else ""
    return (f"🎣 上钩了！#{item} {fish}（{rarity} · {grade}）\n{prefix}查看鱼包\n"
            f"{area}｜{bag_label} {used}/{bag_capacity} · {weight(grams)} · {price} 币"
            f"{grade_line}{reward}\n{story}{footer}")
