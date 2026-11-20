"""Member-facing command reference for one addressed group message."""
from . import roles as permissions, voice_policy


MAIN_MENU = """🐕 二狗菜单
命令前缀「{prefix}」　{mode}
{games}🏅 {prefix}积分　📜 {prefix}群规
🎵 {prefix}点歌 茉莉花
🌤 {prefix}天气 北京　🔎 {prefix}百科 大熊猫
{interaction}📚 {prefix}全菜单"""


def render(db,group,event,cfg,prefix):
    games=[]
    if cfg["games"]:
        if "钓鱼" not in cfg.get("disabled_games",[]):
            games.append(f"🎣 {prefix}抛竿　/　{prefix}钓鱼玩法")
        games.append(f"🎮 {prefix}游戏列表")
    interaction=[]
    if cfg["polls"]:
        interaction.append(f"{prefix}投票 V01 1")
    if cfg["draws"]:
        interaction.append(f"{prefix}抽签 报名")
    from .models import api_first
    mode="智能聊天请 @二狗" if api_first(db,group["id"]) else "@二狗 也可发指令"
    return MAIN_MENU.format(prefix=prefix,mode=mode,games="".join(line+"\n" for line in games),
                            interaction=("🗳 "+ "　".join(interaction)+"\n") if interaction else "")


def full_menu(db,group,event,cfg,prefix):
    roles=db.execute("""SELECT m.verified IS NOT NULL AS verified,COALESCE(c.enabled,1) AS model_on,
                EXISTS(SELECT 1 FROM json_each(c.admins) WHERE value=:member) AS model_admin,
                EXISTS(SELECT 1 FROM managers WHERE grp=g.id AND member=:member) AS group_admin
                FROM groups g LEFT JOIN chat_models m ON m.grp=g.id LEFT JOIN smart_controls c ON c.grp=g.id
                WHERE g.id=:grp""",{"grp":group["id"],"member":event["member"]}).fetchone()
    lines=[f"📚 二狗全菜单　命令前缀「{prefix}」", f"🌤 {prefix}天气 北京"]
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
        lines.append("@二狗 帮我想三个周末活动")
    else:
        lines.append("智能对话已关闭" if roles["verified"] else "本地聊天")
    lines.extend(["讲个笑话　/　讲个故事","追问　然后呢（也要点名）",
                  "\n🔎 查询与娱乐","百科 大熊猫","菜谱 土豆","运势","星座 白羊座",
                  "快递 圆通 单号（承运商需已接通）",
                  "\n🏅 积分与群服务","周榜　/　月榜　/　总榜","资产榜","兑换列表","兑换 奖励名","关键词：点名后发本群关键词"])
    if cfg["games"]:
        start="开始 成语接龙" if "成语接龙" not in cfg.get("disabled_games",[]) else "开始 游戏名"
        lines.extend(["\n🎮 群游戏",start,"加入 G01","状态 G01","G01 动作","退出 G01",
                      "管理员可用：" if adopted else "发起人或群管可用：","G01 重置","结束 G01"])
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
    lines.extend(["\n📌 使用说明","智能模式开启时，@二狗 会与模型对话。" if roles["verified"] and roles["model_on"] else "也可以 @二狗 后发指令。",*notes,voice,"欢迎、退群提醒和定时通知由后台设置。",f"没找到？发「{prefix}菜单」。"])
    return "\n".join(lines)
