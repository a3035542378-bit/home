"""从同一份目录生成微信群导航、别名与只读玩法帮助。"""
import os
from dataclasses import dataclass

from . import breeding, exhibit_batch, fishing_bait, models, pond_growth, roles, voice_policy
from .group_tools import CHECKIN_POINTS
from .db import DEFAULT
from .fishing_waters import SPECIES


@dataclass(frozen=True)
class Topic:
    name: str
    title: str
    body: str = ""
    section: str = "main"
    gate: str = ""
    aliases: tuple = ()


TOPICS = (
    Topic(
        "钓鱼", "🎣 钓第一条鱼",
        gate="fish",
        aliases=('钓鱼菜单', '钓鱼玩法', '怎么钓鱼', '如何钓鱼', '钓鱼怎么玩'),
    ),
    Topic(
        "天气", "🌤 查城市天气",
        (
            "查北京的天气\n"
            "{p}天气 北京\n\n"
            "把北京换成要查的城市\n"
            "{p}天气 抚州"
        ),
        aliases=('查天气帮助', '天气怎么查'),
    ),
    Topic(
        "积分", "🏅 签到和兑奖",
        (
            f"按北京时间每天可领一次，本群到账 {CHECKIN_POINTS} 分。\n"
            "{p}签到\n\n"
            "看本群余额\n"
            "{p}积分\n\n"
            "想换奖励？先看价格，查看免费。\n"
            "{p}兑换列表\n"
            "照回执发兑换指令才会扣分。\n"
            "想比积分？发周榜，也可把周换成月或总。\n"
            "{p}周榜"
        ),
        aliases=('签到帮助', '打卡帮助', '兑换帮助'),
    ),
    Topic(
        "游戏", "🎮 开局和加入",
        (
            "先看本群有哪些游戏、哪些局正在玩\n"
            "{p}游戏列表"
        ),
        gate="games",
        aliases=('群游戏帮助', '开局帮助', '加入帮助'),
    ),
    Topic(
        "互动", "🗳 投票和抽签",
        gate="interaction",
    ),
    Topic(
        "投票", "🗳 找投票或看结果",
        section="detail",
        gate="polls",
    ),
    Topic(
        "抽签", "🎟 报名或退出抽签",
        section="detail",
        gate="draws",
    ),
    Topic(
        "点歌", "🎵 找一首歌",
        (
            "发送歌名或歌手，会收到音乐搜索入口。\n"
            "{p}点歌 茉莉花"
        ),
        aliases=('找歌帮助',),
    ),
    Topic(
        "生活", "🔎 查百科、做菜或看运势",
        (
            "查一条百科摘要\n"
            "{p}百科 大熊猫\n\n"
            "用食材找本地菜谱\n"
            "{p}菜谱 土豆\n\n"
            "看看今日娱乐签\n"
            "{p}运势\n\n"
            "看自己的星座，把白羊座换成你的星座\n"
            "{p}星座 白羊座"
        ),
        aliases=('百科帮助', '菜谱帮助', '生活查询帮助', '运势帮助', '星座帮助'),
    ),
    Topic(
        "快递", "📦 查快递",
        section="service",
        gate="parcel",
        aliases=('查件帮助',),
    ),
    Topic(
        "聊天", "💬 听笑话或聊两句",
        (
            "听个笑话\n"
            "{p}讲个笑话\n\n"
            "听故事，每次追问也要点名\n"
            "{p}讲个故事\n"
            "{p}然后呢"
        ),
        aliases=('智能对话帮助', '陪聊帮助'),
    ),
    Topic(
        "群服务", "📜 看群规和群关键词",
        (
            "查看本群群规\n"
            "{p}群规\n\n"
            "想用群关键词？在前缀后发群运营公布的词。"
        ),
        aliases=('群规帮助', '关键词帮助'),
    ),
    Topic(
        "管理", "⚙️ 管理本群",
        section="service",
        gate="admin",
        aliases=('群管帮助', '权限帮助'),
    ),
    Topic(
        "绑定", "🔗 激活或停用群聊",
        section="service",
        gate="binding",
        aliases=('群绑定帮助', '激活帮助'),
    ),
    Topic(
        "鱼包", "🎒 处理鱼获或卖鱼",
        (
            "钓到的鱼先进自己的鱼包。满包要先腾格。\n\n"
            "挑一条鱼，看看能存塘还是出售\n"
            "{p}查看鱼包\n\n"
            "先查一尾鱼的售价，查看免费\n"
            "{p}卖鱼\n"
            "收到报价后，发带鱼号的卖鱼指令才卖出。\n\n"
            "想扩鱼包或整包出售？\n"
            "鱼包页会列出扩容费用和整包售价。\n"
            "想了解收购价，可发\n"
            "{p}鱼市"
        ),
        section="fish",
        gate="fish",
        aliases=('出售帮助', '卖鱼帮助', '背包帮助'),
    ),
    Topic(
        "鱼塘", "🐟 在鱼塘把鱼养大",
        (
            "鱼进空闲成长位就开始长，不喂也能养。\n"
            f"每 {pond_growth.SECONDS//60} 分钟一轮，最多 {pond_growth.ROUNDS} 轮。\n\n"
            "先挑一尾鱼\n"
            "{p}查看鱼包\n"
            "假设鱼号是 #71，放入自己的鱼塘\n"
            "{p}放入鱼塘#71\n\n"
            "想喂鱼？先看本次费用和能喂的鱼\n"
            "{p}鱼塘\n"
            "假设 #71 正在成长，发送即扣饲料费\n"
            "{p}投喂#71\n\n"
            "换成长位、设招牌、扩塘或整塘出售\n"
            "先看自己能做什么和要花多少\n"
            "{p}鱼塘操作"
        ),
        section="fish",
        gate="fish",
        aliases=('投喂帮助', '成长位帮助', '鱼塘怎么养', '养鱼帮助'),
    ),
    Topic(
        "繁育", "🥚 配对和领幼鱼",
        (
            "两尾同种成年鱼放在自己的塘里就能配对。\n"
            f"每次 {breeding.FEE} 鱼币，{breeding.DURATION//60} 分钟后有 {breeding.SUCCESS:.0%} 机会出幼鱼。\n\n"
            "先看还缺什么，或免费预览一对亲鱼\n"
            "{p}繁育配对\n"
            "照回执发确认才扣钱。亲鱼提前离塘会中止。\n\n"
            "看配对结果，成功后按提示领取\n"
            "{p}繁育状态"
        ),
        section="fish",
        gate="breed",
        aliases=('配对帮助', '幼鱼帮助'),
    ),
    Topic(
        "图鉴", "📖 点亮和换展",
        (
            "每种鱼展一尾，更重的能换展，旧展品回包。\n\n"
            "先选出能点亮或换展的鱼，查看免费\n"
            "{p}放入图鉴\n"
            f"复制回执最后一行可一次展出最多 {exhibit_batch.LIMIT} 个鱼号。\n"
            "批量会跳过正在配对的亲鱼。\n\n"
            "看当前钓场的收藏\n"
            "{p}图鉴\n\n"
            "翻看所有鱼种、品级和巨物分类\n"
            "{p}全图鉴\n\n"
            "看一尾鱼如何升品、获得首次突破积分\n"
            "{p}鱼获品级"
        ),
        section="fish",
        gate="fish",
        aliases=('点亮帮助', '批量点亮帮助'),
    ),
    Topic(
        "钓场", "🌊 选钓场、找鱼种",
        (
            "先看可去的水域\n"
            "{p}切换钓场\n\n"
            "想回新手池塘，直接发送\n"
            "{p}切换钓场 新手池塘\n\n"
            "想找某种鱼，把白条换成鱼名\n"
            "{p}白条怎么钓"
        ),
        section="fish",
        gate="fish",
        aliases=('水域帮助', '鱼种帮助'),
    ),
    Topic(
        "巨物", "🐋 看巨物出没时间",
        (
            "鱼讯会告诉你本场何时有机会遇见巨物。\n"
            "出现后最多停留 3 分钟，被钓走就结束。\n"
            "新手池塘遇上巨物也可能损坏装备。\n\n"
            "查本场的预告\n"
            "{p}巨物鱼讯"
        ),
        section="fish",
        gate="fish",
        aliases=('鱼讯帮助',),
    ),
    Topic(
        "装备", "🪱 选饵、升竿或换线",
        (
            "普通抛竿用免费饵。\n"
            f"高级饵每竿 {fishing_bait.BAITS['高级鱼饵'].points} 分，顶级饵 {fishing_bait.BAITS['顶级鱼饵'].points} 分。\n"
            "按本竿选饵，跑鱼也消耗积分\n"
            "{p}鱼饵\n\n"
            "看鱼竿等级和升级费\n"
            "{p}我的鱼竿\n\n"
            "看修线费用，或用「升级鱼线」升韧性\n"
            "{p}鱼线\n\n"
            "想强化、重铸或回退？先看费用\n"
            "{p}强化帮助"
        ),
        section="fish",
        gate="fish",
        aliases=('鱼饵帮助', '鱼竿帮助', '鱼线帮助', '钓鱼进阶'),
    ),
    Topic(
        "强化", "🔧 强化或重铸鱼竿",
        (
            "每级鱼竿多开一阶强化。\n"
            "品质、韧性影响稀有鱼，硬度影响珍品。\n\n"
            "先看自己的已开阶数\n"
            "{p}我的鱼竿\n\n"
            "开新阶，会扣「新阶数 × 10」鱼币\n"
            "{p}强化鱼竿\n\n"
            "假设已有第 1 阶，重抽韧性扣 4 币\n"
            "{p}重铸 韧性 1\n"
            "韧性也可换成硬度，重抽可能降低属性。\n\n"
            "移除最高阶，扣「最高阶数 × 3」鱼币\n"
            "{p}回退强化"
        ),
        section="detail",
        gate="fish",
        aliases=('强化玩法', '重铸帮助'),
    ),
    Topic(
        "护塘", "🛡 去群友鱼塘或防偷",
        (
            "输入偷鱼后，在微信里选中一位群友。\n"
            "只摸得到普通塘鱼，被发现可能赔鱼币。\n\n"
            "看成功机会和赔付规则\n"
            "{p}偷鱼玩法\n\n"
            "先查保护时长、积分价格\n"
            "{p}鱼塘保护\n"
            "招牌鱼和图鉴展品也免偷。"
        ),
        section="fish",
        gate="fish",
        aliases=('偷鱼帮助', '保护帮助'),
    ),
    Topic(
        "鱼榜", "🏆 看纪录和排行榜",
        (
            "查自己的装备、鱼获和亲钓纪录\n"
            "{p}钓鱼信息\n\n"
            "比亲手钓起时的重量\n"
            "{p}重量榜\n\n"
            "比本群点亮的鱼种数\n"
            "{p}图鉴榜\n\n"
            "比鱼币余额和库存售价之和\n"
            "{p}资产榜"
        ),
        section="fish",
        gate="fish",
        aliases=('排行榜帮助', '纪录帮助', '记录帮助', '个人纪录帮助'),
    ),
)
BY_ALIAS = {word:topic for topic in TOPICS for word in (topic.name+"帮助",*topic.aliases)}


def find_topic(cmd):
    return BY_ALIAS.get(cmd.rstrip("。！？!?").strip())


def parcel_carriers():
    from .queries import CARRIERS
    domestic=list(CARRIERS) if os.getenv("ERGOU_KDN_ID") and os.getenv("ERGOU_KDN_KEY") else []
    return domestic+(["DHL"] if os.getenv("ERGOU_DHL_KEY") else [])


def access(db,group,member,cfg):
    from .group_binding import administrator
    bot,grp=group["account"],group["id"]
    governed=bool(roles.owner(db,bot))
    level=roles.LEVEL[roles.role(db,bot,grp,member)] if governed else 0
    manager=level>=3 if governed else bool(db.execute("SELECT 1 FROM managers WHERE grp=? AND member=?",(grp,member)).fetchone())
    model_admin=level>=4 if governed else bool(db.execute("SELECT 1 FROM smart_controls,json_each(admins) WHERE grp=? AND value=?",(grp,member)).fetchone())
    fish=cfg["games"] and "钓鱼" not in cfg.get("disabled_games",())
    return dict(fish=fish,breed=fish and breeding.enabled(db,grp),games=cfg["games"],
                interaction=cfg["polls"] or cfg["draws"],polls=cfg["polls"],draws=cfg["draws"],admin=manager or model_admin,
                binding=bool(administrator(db,bot,member)),parcel=bool(parcel_carriers()),
                manager=manager,model_admin=model_admin,level=level,
                model_ready=bool(db.execute("SELECT 1 FROM chat_models WHERE grp=? AND verified IS NOT NULL AND credential IS NOT NULL",(grp,)).fetchone()))


def entries(topics,prefix):
    return [f"{t.title}\n{prefix}{t.name}帮助" for t in topics]


def render(db,group,event,cfg,prefix):
    flags=access(db,group,event["member"],cfg)
    available=[t for t in TOPICS if t.section=="main" and flags.get(t.gate,True)]
    return "\n".join(["🐕 二狗菜单",f"今天领 {CHECKIN_POINTS} 分\n{prefix}签到","",*entries(available,prefix),f"所有已开放功能\n{prefix}全菜单"])


def fishing_directory(prefix,cooldown,pilot):
    topics=[t for t in TOPICS if t.section=="fish" and (t.gate!="breed" or pilot)]
    return "\n\n".join([f"🎣 第一竿用免费饵，鱼会进鱼包。\n每 {cooldown} 秒可抛一竿\n{prefix}抛竿",
                         *entries(topics,prefix),f"全图鉴收录 {len(SPECIES)} 种。"])


def management(cfg,flags,prefix):
    parts=[]
    if flags["manager"]:
        if cfg["polls"]:
            parts.append("创建投票，发送后群友可投票\n"+prefix+"投票 创建 午餐|饭|面")
        if cfg["draws"]:
            parts.append("有人报名后，随机抽一人\n"+prefix+"抽签 开始 1\n需重抽时写明原因，例如\n"+prefix+"抽签 重抽 1 中奖人弃权")
        if cfg["games"]:
            parts.append("结束或重置一局会影响全局玩家。\n先查进行中的局号\n"+prefix+"游戏列表")
    if flags["model_admin"] and not flags["model_ready"]:
        parts.append("启用智能对话前，请群运营在后台测试并保存模型。")
    if flags["model_admin"] and flags["model_ready"]:
        parts.append("在微信选中 @二狗，再发以下开关。\n开启智能对话\n关闭智能对话\n开启前需在本群后台保存并验证模型。")
    if flags["level"]>=4:
        parts.extend(["看本群实际开关\n"+prefix+"本群设置\n调整时在后面加「游戏 开启」等选项。","查本群群主授权\n"+prefix+"查看群主状态\n想授权或撤销管理员，输入带前缀的\n「授权管理员」或「取消管理员」，再真 @ 群友。"])
    if flags["level"]==5:
        parts.extend(["看所有群主授权\n"+prefix+"群主授权列表\n在目标群用前缀加「授权群主」或「取消群主授权」。","查新群默认设置\n"+prefix+"全局配置\n在前缀后输入「主人转移」并真 @ 接任者。\n发送即交接全部主人权限。"])
    return parts or ["当前没有开启的群互动可管理。"]


def page(db,group,event,cfg,prefix,t):
    flags=access(db,group,event["member"],cfg)
    if not flags.get(t.gate,True):
        reason={"admin":"群管理帮助仅向本群已授权的管理人员开放。","binding":"绑定群聊需要二狗主人或获授权的绑定人员。","parcel":"本群暂未接通快递查询。"}.get(t.gate,f"本群暂未开启{t.name}功能。")
        return f"{reason}\n看本群可用功能\n{prefix}菜单"
    if t.name=="钓鱼":
        return fishing_directory(prefix,cfg.get("fishing_cooldown_seconds",DEFAULT["fishing_cooldown_seconds"]),flags["breed"])
    parts=[t.title]
    if t.body:
        parts.append(t.body.format(p=prefix))
    if t.name=="积分" and not flags["fish"]:
        parts.append("查本群鱼币和库存资产榜\n"+prefix+"资产榜")
    if t.name=="游戏" and "成语接龙" not in cfg.get("disabled_games",()):
        parts.append("想开一局成语接龙？发送后开局\n"+prefix+"开始 成语接龙\n开局回执会给出局号、玩法和加入指令。")
    if t.name in ("互动","投票","抽签"):
        if cfg["polls"] and t.name!="抽签":
            parts.append("查本群最近的投票、看结果或投一票\n"+prefix+"投票")
        if cfg["draws"] and t.name!="投票":
            parts.append("想参加抽签，发送后加入报名池\n"+prefix+"抽签 报名\n\n改变主意，取消报名\n"+prefix+"抽签 退出")
    if t.name=="生活" and flags["parcel"]:
        parts.append("看已接通的快递公司\n"+prefix+"快递帮助")
    if t.name=="快递":
        carriers=parcel_carriers()
        parts.append("可查"+"、".join(carriers)+"。\n把示例单号换成自己的运单号\n"+prefix+"快递 "+carriers[0]+" 1234567890")
    if t.name=="聊天" and not models.api_first(db,group["id"]):
        parts.append("本群当前为本地聊天。也可以在微信里 @二狗 后发指令。")
    if t.name in ("聊天","天气") and models.api_first(db,group["id"]):
        parts.append("💬 智能已开启。在微信选中 @二狗 后提问，\n由本群大模型回答。")
    if t.name=="聊天" and voice_policy.active(db,group["id"],group["account"],group["binding"]):
        parts.append("本群可用语音，说「二狗二狗，积分」。")
    if t.name=="管理":
        parts.extend(management(cfg,flags,prefix))
    if t.name=="绑定":
        parts.append("首次激活：在新群选中 @二狗，再发\n激活本群\n\n已绑定群查看状态，用文字前缀\n二狗绑定状态\n\n暂停当前群，数据保留，发送即停用\n二狗停用本群")
    if t.name=="群服务":
        if flags["level"]==5:
            parts.append("私聊二狗查群编号，可用「管理群 #编号 查看群主状态」。\n"+prefix+"群主授权列表")
        parts.extend(entries((topic for topic in TOPICS if topic.name in ("管理","绑定") and flags[topic.gate]),prefix))
    return "\n\n".join(parts)


def full_menu(db,group,event,cfg,prefix):
    flags=access(db,group,event["member"],cfg)
    topics=(t for t in TOPICS if flags.get(t.gate,True))
    mode="已开启，可真 @ 提问" if models.api_first(db,group["id"]) else "当前使用本地指令"
    return "\n".join(["📚 本群全部帮助","💬 "+mode,*entries(topics,prefix)])
