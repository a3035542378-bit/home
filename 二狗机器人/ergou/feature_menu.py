"""微信群一级目录和分类帮助。"""
from dataclasses import dataclass
import os

from . import breeding, models, roles as permissions, voice_policy
from .db import DEFAULT
from .fishing_waters import SPECIES


@dataclass(frozen=True)
class Topic:
    name: str
    title: str
    gate: str = ""
    aliases: tuple = ()
    actions: tuple = ()


TOPICS = (
    Topic("钓鱼","🎣 钓鱼和养鱼","fish",("钓鱼菜单","钓鱼玩法","怎么钓鱼","如何钓鱼","钓鱼怎么玩")),
    Topic("天气","🌤 天气查询",aliases=("查天气帮助",),actions=(("查北京的天气","天气 北京"),("也可以这样问","查看北京天气"))),
    Topic("积分","🏅 积分和兑换",aliases=("兑换帮助","签到帮助"),actions=(("查本群余额","积分"),("今天签到领 3 分","签到"),("查看本群奖励和所需积分","兑换列表"))),
    Topic("游戏","🎮 群游戏","games",actions=(("看本群可玩的游戏","游戏列表"),)),
    Topic("互动","🗳 投票和抽签","interaction",("投票帮助","抽签帮助")),
    Topic("点歌","🎵 点歌",actions=(("获取歌曲搜索链接","点歌 茉莉花"),)),
    Topic("生活","🔎 生活查询",aliases=("生活查询帮助","百科帮助","菜谱帮助"),actions=(("看词条摘要","百科 大熊猫"),("看家常做法","菜谱 土豆"),("看今日娱乐签","运势"),("看星座运势","星座 白羊座"))),
    Topic("聊天","💬 聊天",actions=(("听个笑话","讲个笑话"),("听个故事","讲个故事"))),
    Topic("群服务","📜 群服务",aliases=("群规帮助",),actions=(("读本群群规","群规"),)),
    Topic("鱼包","🎒 鱼包和出售","fish",actions=(("看库存和售价","查看鱼包"),("选一条入塘","放入鱼塘"),("查看单鱼出售报价","卖鱼"))),
    Topic("鱼塘","🐟 鱼塘和投喂","fish"),
    Topic("图鉴","📖 图鉴和点亮","fish",actions=(("预览可点亮、换展的鱼号","放入图鉴"),("看本场收藏","图鉴"),("查所有鱼种","全图鉴"))),
    Topic("巨物","🐋 巨物和鱼讯","fish",actions=(("看巨物出没时段","巨物鱼讯"),)),
    Topic("装备","🪱 鱼饵和装备","fish",("鱼饵帮助",),actions=(("看用饵方法和积分价格","鱼饵"),("查鱼线状态","鱼线"),("看鱼竿强化规则","强化玩法"),("看我的装备和钓手等级","钓鱼信息"),("看进阶玩法","钓鱼进阶"))),
    Topic("钓场","🌊 钓场和鱼种","fish",actions=(("看可去的钓场","切换钓场"),("查新手池塘鱼种","水域介绍 新手池塘"))),
    Topic("护塘","🛡 偷鱼和护塘","fish",("偷鱼帮助",),actions=(("了解偷鱼和风险","偷鱼玩法"),("看护塘状态和价格","鱼塘保护"))),
    Topic("鱼榜","🏆 钓鱼排行榜","fish",("排行榜帮助",),actions=(("比收藏种数","图鉴榜"),("比亲钓重量","重量榜"),("比本群资产","资产榜"))),
    Topic("繁育","🥚 配对和幼鱼","breed",actions=(("看自己的配对条件","繁育配对"),("查配对或待领状态","繁育状态"))),
)
TOPIC_BY_ALIAS = {alias:t for t in TOPICS for alias in (t.name+"帮助",*t.aliases)}


def find_topic(cmd):
    return TOPIC_BY_ALIAS.get(cmd.rstrip("。！？!?").strip())


def visible(topic,cfg,pilot):
    if topic.gate in ("fish","breed"):
        return cfg["games"] and "钓鱼" not in cfg.get("disabled_games",[]) and (topic.gate!="breed" or pilot)
    if topic.gate=="interaction":
        return cfg["polls"] or cfg["draws"]
    return not topic.gate or cfg[topic.gate]


def render(db,group,event,cfg,prefix):
    lines=["🐕 二狗菜单",f"发「{prefix}＋指令」，例如「{prefix}积分」。"]
    for t in TOPICS:
        if (t.name=="钓鱼" or t.gate not in ("fish","breed")) and visible(t,cfg,False):
            entry=f"{t.title}　{prefix}{t.name}帮助"
            if t.name=="积分":
                entry+=f" / {prefix}签到"
            lines.append(entry)
    return "\n".join([*lines,f"📚 全部指令　{prefix}全菜单"])


def fishing_directory(prefix,cooldown,pilot):
    lines=["🎣 钓鱼帮助",f"免费饵每 {cooldown} 秒一竿，鱼获进包",prefix+"抛竿"]
    for t in TOPICS:
        if t.name!="钓鱼" and (t.gate=="fish" or (t.gate=="breed" and pilot)):
            label=f"{t.title}（{len(SPECIES)} 种）" if t.name=="图鉴" else t.title
            lines.append(f"{label}　{prefix}{t.name}帮助")
    return "\n".join(lines)


def pond_actions(db,key,prefix,now):
    from . import fish_storage,pond_growth,pond_view
    pond_growth.settle(db,key[0],now,key[1])
    breeding.resolve(db,key,now)
    count,_,level=fish_storage.occupancy(db,key,"pond")
    lines=["看塘和投喂费用",prefix+"鱼塘"]
    rows=db.execute(pond_view.STOCK+" AND p.storage='pond' ORDER BY p.id DESC",key).fetchall()
    if rows:
        row=rows[0]
        i=row["id"]
        lines.extend(["查单鱼详情及当前操作",f"{prefix}查看鱼#{i}"])
        if any(not r["flagship"] for r in rows):
            target=next(r["id"] for r in rows if not r["flagship"])
            lines.extend(["设为招牌鱼，免偷",f"{prefix}设为招牌鱼#{target}"])
        paused=next((r for r in rows if r["next_at"] is None and not pond_view.finished(r)),None)
        if paused:
            lines.extend(["恢复成长，位满时暂停原有一尾",f"{prefix}换入成长位#{paused['id']}"])
        lines.extend(["选一尾，查看出售报价",prefix+"卖鱼"])
    else:
        lines.extend(["选鱼放入第一格",prefix+"放入鱼塘","鱼入塘后可设招牌、换成长位或出售。"])
    if level<len(fish_storage.TIERS["pond"]):
        capacity,cost=fish_storage.TIERS["pond"][level]
        coins=db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()
        if (coins[0] if coins else 30)>=cost:
            lines.extend([f"扩到 {capacity} 条 · 发送扣 {cost} 鱼币",prefix+"升级鱼塘"])
        else:
            lines.append(f"扩到 {capacity} 条需 {cost} 鱼币，当前余额不足。")
    if rows:
        total=sum(r["price"] for r in rows)
        warning=fish_storage.breeding_sale_note(db,key)
        lines.extend(["",f"⚠ 整塘出售会清空 {count} 条，当前共 {total} 鱼币。",
                      *([warning] if warning else []),prefix+"一键卖鱼"])
    return lines


def page(db,group,event,cfg,prefix,t):
    key=(group["id"],event["member"])
    pilot=breeding.enabled(db,key[0])
    if not visible(t,cfg,pilot):
        return f"本群暂未开启{t.name}功能。查看可用模块\n{prefix}菜单"
    if t.name=="钓鱼":
        return fishing_directory(prefix,cfg.get("fishing_cooldown_seconds",DEFAULT["fishing_cooldown_seconds"]),pilot)
    lines=[t.title+"帮助"]
    for intent,command in t.actions:
        lines.extend([intent,prefix+command])
    if t.name=="群服务" and permissions.owner(db,group["account"]):
        level=permissions.LEVEL[permissions.role(db,group["account"],key[0],key[1])]
        for command,hint in (("查看群主状态","查本群授权状态"),("群主授权列表","查自己授予的群主权限")):
            if level>=permissions.REQUIRED[command]:
                lines.extend([hint,prefix+command])
    if t.name=="鱼塘":
        lines.extend(pond_actions(db,key,prefix,event["arrived"]))
    if t.name=="游戏" and "成语接龙" not in cfg.get("disabled_games",[]):
        lines.extend(["开一局成语接龙",prefix+"开始 成语接龙"])
    if t.name=="生活":
        if os.getenv("ERGOU_KDN_ID") and os.getenv("ERGOU_KDN_KEY"):
            lines.append("查国内快递可发「"+prefix+"快递 圆通 你的运单号」。")
        if os.getenv("ERGOU_DHL_KEY"):
            lines.append("查国际快递可发「"+prefix+"快递 DHL 你的运单号」。")
    if t.name=="互动":
        if cfg["polls"]:
            poll=db.execute("SELECT id,title FROM polls WHERE grp=? ORDER BY id DESC LIMIT 1",(key[0],)).fetchone()
            if poll:
                lines.extend([f"看「{poll[1]}」的结果",f"{prefix}投票 V{poll[0]:02}"])
            else:
                lines.append("本群暂无投票。")
        if cfg["draws"]:
            lines.extend(["加入本群抽签报名池",prefix+"抽签 报名","取消报名",prefix+"抽签 退出"])
    if t.name in ("天气","聊天") and models.api_first(db,key[0]):
        lines.append("💬 在微信里选中 @二狗 再问，由本群大模型回答。")
    if t.name=="群服务":
        lines.append("本群关键词也可在点名后发送。管理用法见你的全菜单。")
        lines.append(prefix+"全菜单")
    return "\n".join(lines)


def full_menu(db,group,event,cfg,prefix):
    roles=db.execute("""SELECT m.verified IS NOT NULL AS verified,COALESCE(c.enabled,1) AS model_on,
                EXISTS(SELECT 1 FROM json_each(c.admins) WHERE value=:member) AS model_admin,
                EXISTS(SELECT 1 FROM managers WHERE grp=g.id AND member=:member) AS group_admin
                FROM groups g LEFT JOIN chat_models m ON m.grp=g.id LEFT JOIN smart_controls c ON c.grp=g.id
                WHERE g.id=:grp""",{"grp":group["id"],"member":event["member"]}).fetchone()
    lines=["📚 二狗全菜单", f"每条指令前加「{prefix}」，例如「{prefix}天气 北京」。"]
    group_admin,model_admin=roles["group_admin"],roles["model_admin"]
    adopted=permissions.owner(db,group["account"])
    if adopted:
        level=permissions.LEVEL[permissions.role(db,group["account"],group["id"],event["member"])]
        group_admin,model_admin=level>=3,level>=4
    common=[("🏅","积分"),("🎵","点歌 茉莉花"),("📜","群规")]
    if cfg["games"]:
        common.append(("🎮","游戏列表"))
        if "钓鱼" not in cfg.get("disabled_games",[]):
            common.append(("🎣","钓鱼玩法"))
    if cfg["polls"]:
        common.append(("🗳","投票 V01 1"))
    if cfg["draws"]:
        common.append(("🎟","抽签 报名"))
    lines.extend(f"{icon} {prefix}{cmd}" for icon,cmd in common)
    if cfg["polls"] or cfg["draws"]:
        lines.append("\n🗳️ 群互动")
    if cfg["polls"]:
        lines.extend(["看结果：投票 V01","多选：投票 V01 1,2"])
    if cfg["draws"]:
        lines.append("取消报名：抽签 退出")
    lines.extend(["\n💬 聊天"])
    if roles["verified"] and roles["model_on"]:
        lines.append("想聊天？在微信里选中 @二狗，再说想聊的事。")
    else:
        lines.append("智能对话已关闭" if roles["verified"] else "本地聊天")
    lines.extend(["讲个笑话　/　讲个故事",f"接着听　{prefix}然后呢",
                  "\n🔎 查询与娱乐","百科 大熊猫","菜谱 土豆","运势","星座 白羊座",
                  "快递 圆通 单号（承运商需已接通）",
                  "\n🏅 积分与群服务",f"{prefix}签到（也可发「{prefix}打卡」）","周榜　/　月榜　/　总榜","资产榜","兑换列表","兑换 奖励名",f"群关键词也要加「{prefix}」"])
    if cfg["games"]:
        start="开始 成语接龙" if "成语接龙" not in cfg.get("disabled_games",[]) else "开始 游戏名"
        lines.extend(["\n🎮 群游戏",start,"加入 G01","状态 G01","G01 动作","退出 G01"])
        owns_game=not adopted and db.execute("SELECT 1 FROM games WHERE grp=? AND owner=? AND state='RUNNING' LIMIT 1",(group["id"],event["member"])).fetchone()
        if group_admin or owns_game:
            lines.extend(["本局管理","G01 重置","结束 G01"])
        if "钓鱼" not in cfg.get("disabled_games",[]):
            lines.extend([f"🎣 钓第一条鱼：{prefix}抛竿",f"🪱 查看鱼饵：{prefix}鱼饵",f"挑鱼收藏或出售：{prefix}查看鱼包",f"📋 个人档案：{prefix}钓鱼信息",f"🌊 巨物预告：{prefix}巨物鱼讯",f"🐾 {prefix}偷鱼玩法　/　鱼塘保护"])
    notes=[]
    if group_admin and cfg["polls"]:
        notes.extend(["🗳 群管创建投票","投票 创建 午餐|米饭|面条","多选时在主题前加「多选 」"])
    if group_admin and cfg["draws"]:
        notes.extend(["🎟 群管抽签","抽签 开始 1","抽签 重抽 1 原因"])
    if model_admin:
        notes.extend(["智能对话管理员选 @二狗 后发：","开启智能对话","关闭智能对话"])
    ids=[]
    if cfg["games"]:
        ids.append("G01 换成局号")
    if cfg["polls"]:
        ids.append("V01 换成投票编号")
    if ids:
        notes.append("，".join(ids))
    voice="语音未启用" if voice_policy.active(db,group["id"],group["account"],group["binding"]) is None else "语音用“二狗二狗”唤醒"
    lines.extend(["\n📌 使用说明","智能模式开启时，@二狗 会与模型对话。" if roles["verified"] and roles["model_on"] else "也可以 @二狗 后发指令。",*notes,voice,"欢迎、退群提醒和定时通知由后台设置。",f"返回常用指令　{prefix}菜单"])
    return "\n".join(lines)
