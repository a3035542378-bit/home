"""从同一份目录生成微信群导航、别名与只读玩法帮助。"""
import os
from dataclasses import dataclass

from . import breeding, exhibit_batch, models, pond_growth, roles, voice_policy
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
    Topic('钓鱼', '🎣 钓第一条鱼', gate='fish', aliases=('钓鱼菜单', '钓鱼玩法', '怎么钓鱼', '如何钓鱼', '钓鱼怎么玩')),
    Topic('天气', '🌤 查城市天气',
        """把示例里的城市换成你想查的地方。

📍 按城市查
【天气 北京】查北京天气
【天气 抚州】查江西抚州天气""", aliases=('查天气帮助', '天气怎么查')),
    Topic('积分', '🏅 签到和兑奖',
        f"""按北京时间每天签到一次，可领 {CHECKIN_POINTS} 分。

🏅 攒积分
【签到】领取今天的积分
【积分】看本群余额
【兑换列表】看奖励和价格，按回执兑换

🏆 看排名
【周榜】查本周积分
【月榜】查本月积分
【总榜】查累计积分""", aliases=('签到帮助', '打卡帮助', '兑换帮助')),
    Topic('游戏', '🎮 开局和加入',
        """🎮 找一局
【游戏列表】看本群游戏和进行中的局""", gate='games', aliases=('群游戏帮助', '开局帮助', '加入帮助')),
    Topic('互动', '🗳 投票和抽签', gate='interaction'),
    Topic('投票', '🗳 找投票或看结果', section='detail', gate='polls'),
    Topic('抽签', '🎟 报名或退出抽签', section='detail', gate='draws'),
    Topic('点歌', '🎵 找一首歌',
        """🎵 找歌
【点歌 茉莉花】获取这首歌的搜索入口""", aliases=('找歌帮助',)),
    Topic('生活', '🔎 查百科、做菜或看运势',
        """🔎 查资料
【百科 大熊猫】读一段百科
【菜谱 土豆】按食材找做法

🍀 休闲
【运势】抽今日娱乐签
【星座 白羊座】看星座运势""", aliases=('百科帮助', '菜谱帮助', '生活查询帮助', '运势帮助', '星座帮助')),
    Topic('快递', '📦 查快递', section='service', gate='parcel', aliases=('查件帮助',)),
    Topic('聊天', '💬 听笑话或聊两句',
        """💬 聊两句
【讲个笑话】听一个笑话
【讲个故事】听一段故事
【然后呢】接着上次的故事""", aliases=('智能对话帮助', '陪聊帮助')),
    Topic('群服务', '📜 看群规和群关键词',
        """📜 本群约定
【群规】看本群规则
群关键词按运营公布的词发送，也要加前缀。""", aliases=('群规帮助', '关键词帮助')),
    Topic('管理', '⚙️ 管理本群', section='service', gate='admin', aliases=('群管帮助', '权限帮助')),
    Topic('绑定', '🔗 激活或停用群聊', section='service', gate='binding', aliases=('群绑定帮助', '激活帮助')),
    Topic('鱼包', '🎒 处理鱼获或卖鱼',
        """鱼包固定 5 条。想多留鱼，可存塘、升级鱼塘。

🎒 挑一条鱼
【查看鱼包】一次看完鱼号和售价
【批量放入鱼塘】选多条鱼入塘
【批量卖出鱼包】预览售价，再按鱼号出售
【卖鱼】免费查价，带编号发送才出售
【鱼市】看各鱼种收购价""", section='fish', gate='fish', aliases=('出售帮助', '卖鱼帮助', '背包帮助')),
    Topic('鱼塘', '🐟 在鱼塘把鱼养大',
        f"""鱼进空闲成长位就开始长，不喂也能养。

🌱 开始养鱼
【查看鱼包】挑一条鱼，记下鱼号
【放入鱼塘#71】假设鱼号是 #71，放进鱼塘

🍤 给鱼投喂
【鱼塘】看饲料费及成长进度
每 {pond_growth.SECONDS//60} 分钟一轮，最多 {pond_growth.ROUNDS} 轮。
【投喂#71】替换成自己的鱼号，发送即扣费
【批量投喂】预览多条鱼的饲料费
【批量收回鱼包】选塘鱼放回包里
【批量卖出塘鱼】只卖选中的鱼号
【鱼塘操作】换成长位、设招牌或扩容""", section='fish', gate='fish', aliases=('投喂帮助', '成长位帮助', '鱼塘怎么养', '养鱼帮助')),
    Topic('繁育', '🥚 配对和领幼鱼',
        f"""同种成年鱼同塘配对，确认才扣 {breeding.FEE} 鱼币。

🥚 配一对亲鱼
【繁育配对】免费查条件和亲鱼编号
【繁育状态】{breeding.DURATION//60} 分钟后看结果，成功率 {breeding.SUCCESS:.0%}
【领取幼鱼】将待领幼鱼收入塘中
亲鱼提前离塘会中止配对。""", section='fish', gate='breed', aliases=('配对帮助', '幼鱼帮助')),
    Topic('图鉴', '📖 点亮和换展',
        f"""每种鱼展一尾，更重的可以换展，旧展品回包。

✨ 收藏鱼获
【放入图鉴】免费预览可展出的鱼
【图鉴】看当前钓场的收藏
【全图鉴】按品种和巨物分类找鱼
【鱼获品级】看升品和首次突破奖励
复制预览末行可展出最多 {exhibit_batch.LIMIT} 种。
批量会跳过配对亲鱼。""", section='fish', gate='fish', aliases=('点亮帮助', '批量点亮帮助')),
    Topic('钓场', '🌊 选钓场、找鱼种',
        """🌊 换个钓场
【切换钓场】看可去的水域
【切换钓场 新手池塘】免费回到新手塘
【白条怎么钓】查鱼的钓场和重量""", section='fish', gate='fish', aliases=('水域帮助', '鱼种帮助')),
    Topic('巨物', '🐋 看巨物出没时间',
        """巨物最多停留 3 分钟，被钓走就消失。

🐋 追巨物
【巨物鱼讯】看本场出没时间
【巨物图鉴】看各鱼种的巨物门槛""", section='fish', gate='fish', aliases=('鱼讯帮助',)),
    Topic('装备', '🪱 选饵、升竿或换线',
        """普通抛竿用免费饵，选用积分饵只管一竿。

🪱 选鱼饵
【鱼饵】查价格和本群可用积分

🎣 看装备
鱼越重磨损越多。新手塘普通鱼不会损坏装备。
【鱼线】看耐久、换线和升级鱼线费用
【我的鱼竿】看本场咬钩率、耐久和费用
【强化帮助】看强化、重铸和回退规则""", section='fish', gate='fish', aliases=('鱼饵帮助', '鱼竿帮助', '鱼线帮助', '钓鱼进阶')),
    Topic('强化', '🔧 强化或重铸鱼竿',
        """每级竿可开 20 阶，传说竿最高 100 阶。
越往后每阶越强，各阶效果累计。
品质偏向稀有鱼，幸运提高好鱼咬钩率。
韧性减少线、竿磨损，硬度降低脱钩率。

🔧 调整鱼竿
【我的鱼竿】先看已开阶数
【强化鱼竿】开新阶，扣新阶数 × 10 币
【重铸 韧性 1】重抽第 1 阶韧性，扣 4 币
【重铸 幸运】重抽当前阶，也可选硬度
重铸扣阶数 × 4 币，数值可能降低。
【回退强化】移除最高阶，扣该阶数 × 3 币""", section='detail', gate='fish', aliases=('强化玩法', '重铸帮助')),
    Topic('护塘', '🛡 去群友鱼塘或防偷',
        """只能偷普通塘鱼，被发现可能要赔鱼币。

🛡 群友互动
【偷鱼玩法】看如何选群友及赔付规则
【鱼塘保护】查保护时长和积分价格
【鱼塘操作】给自己的招牌鱼免偷""", section='fish', gate='fish', aliases=('偷鱼帮助', '保护帮助')),
    Topic('鱼榜', '🏆 看纪录和排行榜',
        """🏆 比一比
【钓鱼信息】看装备和个人进度
【重量榜】比亲手钓起时的重量
【图鉴榜】比已点亮的鱼种数
【资产榜】比鱼币和库存估价""", section='fish', gate='fish', aliases=('排行榜帮助', '纪录帮助', '记录帮助', '个人纪录帮助')),
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


def entry(command, purpose):
    return f"【{command}】{purpose}"


def topic_rows(topics):
    return [entry(t.name+"帮助", t.title.split(" ", 1)[1]) for t in topics]


def section(title, rows):
    return "\n".join([title, *rows]) if rows else ""


def blocks(*parts):
    return "\n\n".join(part for part in parts if part)


def example(prefix, command):
    return f"💬 试着发一句\n{prefix}{command}"


def directory(db, group, event, cfg, prefix, full):
    flags = access(db, group, event["member"], cfg)
    available = {t.name:t for t in TOPICS if flags.get(t.gate, True)}
    def topics(title, names):
        return section(title, topic_rows(available[n] for n in names if n in available))
    heading = "📚 本群全部帮助" if full else "🐕 二狗菜单"
    intro = f"{heading}\n发送时加「{prefix}」，例如：{prefix}积分"
    main = blocks(intro, section("⭐ 常用", [entry("签到", f"每天领 {CHECKIN_POINTS} 积分"),
                  *topic_rows(available[n] for n in ("钓鱼","积分","天气") if n in available)]),
                  topics("🎮 群里一起玩", ("游戏","互动","点歌","聊天")),
                  topics("🔎 群服务", ("生活","群服务","快递","绑定","管理")))
    if full:
        return blocks(main, topics("🎣 钓鱼和养鱼", [t.name for t in TOPICS if t.section=="fish" or t.name=="强化"]),
                      topics("🗳 投票和报名", ("投票","抽签")),
                      "💬 智能已开启，微信里选中 @二狗 提问。" if models.api_first(db,group["id"]) else "💬 本群当前使用本地指令。")
    return blocks(main, section("📚 更多", [entry("全菜单","查看本群全部帮助")]), example(prefix,"全菜单"))


def render(db,group,event,cfg,prefix):
    return directory(db,group,event,cfg,prefix,False)


def full_menu(db,group,event,cfg,prefix):
    return directory(db,group,event,cfg,prefix,True)


def fishing_directory(prefix,cooldown,pilot):
    care = [entry("查看鱼包","看刚钓到的鱼"),entry("鱼包帮助","学整理和出售"),
            entry("鱼塘帮助","学放鱼、养鱼和投喂"),entry("放入图鉴","挑鱼点亮图鉴"),
            entry("图鉴帮助",f"学点亮和换展，共 {len(SPECIES)} 种")]
    if pilot:
        care.append(entry("繁育帮助","学配对和领幼鱼"))
    return blocks(f"🎣 钓鱼帮助\n发送时加「{prefix}」，例如：{prefix}抛竿",
                  section("🎯 开始钓鱼",[entry("抛竿",f"免费下竿，每 {cooldown} 秒一次"),
                        entry("切换钓场","看能去哪里钓"),entry("钓鱼信息","看鱼竿和个人进度")]),
                  section("🎒 处理鱼获",care),
                  section("🌊 找鱼和配装备", [entry("钓场帮助","找鱼种和水域"),entry("巨物帮助","查巨物出没"),
                        entry("装备帮助","选鱼饵、升鱼线和鱼竿")]),
                  section("🏆 看看本群",[entry("图鉴榜","比点亮的鱼种数"),entry("鱼榜帮助","看重量榜和资产榜"),
                        entry("护塘帮助","学偷鱼和保护鱼塘")]),example(prefix,"抛竿"))


def management(cfg,flags):
    rows = []
    if flags["manager"]:
        if cfg["polls"]:
            rows.append(entry("投票 创建 午餐|饭|面","立即发起投票"))
        if cfg["draws"]:
            rows.extend([entry("抽签 开始 1","抽出一位已报名群友"),
                         entry("抽签 重抽 1 中奖人弃权","写明原因重抽")])
        if cfg["games"]:
            rows.append(entry("游戏列表","选局结束或重置"))
    controls = []
    if flags["model_admin"]:
        if flags["model_ready"]:
            controls.extend([entry("@二狗 开启智能对话","选中机器人后发送"),
                             entry("@二狗 关闭智能对话","切回本地指令")])
        else:
            controls.append("请群运营先在后台测试并保存模型。")
    grants = []
    if flags["level"]>=4:
        grants.extend([entry("本群设置","看本群功能开关"),entry("查看群主状态","查群主授权"),
                       entry("授权管理员 @群友","选中群友后授权"),entry("取消管理员 @群友","撤销其权限")])
    if flags["level"]==5:
        grants.extend([entry("群主授权列表","看所有群主授权"),entry("授权群主","授予本群群主权限"),
                       entry("取消群主授权","撤销本群群主权限"),entry("全局配置","查新群默认设置"),
                       entry("主人转移 @群友","选中接任者即交接权限")])
    return blocks(section("🗳 管理活动",rows),section("💬 智能开关",controls),section("🔑 管理授权",grants)) or "当前没有开启的群互动可管理。"


def page(db,group,event,cfg,prefix,t):
    flags=access(db,group,event["member"],cfg)
    if not flags.get(t.gate,True):
        reason={"admin":"群管理帮助仅向本群已授权的管理人员开放。","binding":"绑定群聊需要二狗主人或获授权的绑定人员。","parcel":"本群暂未接通快递查询。"}.get(t.gate,f"本群暂未开启{t.name}功能。")
        return f"🐕 {reason}\n看本群可用功能\n{prefix}菜单"
    name=t.name
    if name=="钓鱼":
        return fishing_directory(prefix,cfg.get("fishing_cooldown_seconds",DEFAULT["fishing_cooldown_seconds"]),flags["breed"])
    title=t.title.split(" ",1)[0]+" "+name+"帮助"
    body=t.body
    if name=="游戏" and "成语接龙" not in cfg.get("disabled_games",()):
        body+="\n"+entry("开始 成语接龙","立即开局，按回执加入或接词")
    if name in ("互动","投票","抽签"):
        rows=[]
        if cfg["polls"] and name!="抽签":
            rows.append(entry("投票","看本群投票及投票方式"))
        if cfg["draws"] and name!="投票":
            rows.extend([entry("抽签 报名","加入报名池"),entry("抽签 退出","取消报名")])
        body=section("🎟 参与活动",rows)
    if name=="生活" and flags["parcel"]:
        body=blocks(body,section("📦 查件",[entry("快递帮助","看已接通的承运商")]))
    if name=="积分" and not flags["fish"]:
        body+="\n"+entry("资产榜","查本群鱼币和库存")
    if name=="快递":
        carriers=parcel_carriers()
        body=blocks("把示例单号换成自己的运单号。",section("📦 查物流",[
                    entry("快递 "+carriers[0]+" 1234567890","查运单进度"),"已接通："+"、".join(carriers)]))
    if name in ("聊天","天气") and models.api_first(db,group["id"]):
        body=blocks(body,"💬 智能已开启\n在微信选中 @二狗 提问，由本群大模型回答。")
    if name=="聊天" and voice_policy.active(db,group["id"],group["account"],group["binding"]):
        body=blocks(body,"🎙 语音指令\n说「二狗二狗，积分」查余额。")
    if name=="管理":
        body=management(cfg,flags)
    if name=="绑定":
        body=section("🔗 管理群聊",[entry("@二狗 激活本群","在新群选中机器人"),
                     entry("绑定状态","查看本群激活状态"),entry("停用本群","立即停用，保留数据")])
    if name=="群服务":
        body=blocks(body,section("⚙️ 群管理",topic_rows(t for t in TOPICS if t.name in ("管理","绑定") and flags[t.gate])))
    next_step={"天气":"天气 抚州","积分":"积分","游戏":"游戏列表","鱼塘":"查看鱼包","点歌":"点歌 茉莉花",
               "鱼包":"查看鱼包","繁育":"繁育配对","图鉴":"放入图鉴","钓场":"切换钓场","绑定":"绑定状态"}.get(name)
    gap="\n\n" if body and not body[0].isalnum() else "\n"
    return blocks(title+gap+body,example(prefix,next_step) if next_step else "")
