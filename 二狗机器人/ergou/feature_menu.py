"""Member-facing command reference for one addressed group message."""
from . import voice_policy


def render(db,group,event,cfg,prefix):
    roles=db.execute("""SELECT m.verified IS NOT NULL AS verified,COALESCE(c.enabled,1) AS model_on,
                EXISTS(SELECT 1 FROM json_each(c.admins) WHERE value=:member) AS model_admin,
                EXISTS(SELECT 1 FROM managers WHERE grp=g.id AND member=:member) AS group_admin
                FROM groups g LEFT JOIN chat_models m ON m.grp=g.id LEFT JOIN smart_controls c ON c.grp=g.id
                WHERE g.id=:grp""",{"grp":group["id"],"member":event["member"]}).fetchone()
    chat_example=f"「{prefix} 帮我想三个周末活动」"
    if roles["verified"] and roles["model_on"]:
        chat=f"智能对话已开启。试试{chat_example}，接着发「{prefix} 换个室内的」可以追问。"
    elif roles["verified"]:
        chat="本群已关闭智能对话，目前使用本地回复。"
    else:
        chat="本群目前使用本地回复。运营在「大模型配置」测试并启用后，即可点名自由提问。"
    lines=[
        "二狗功能菜单",
        f"命令前缀「{prefix}」。在每条指令前加上它，例如「{prefix}积分」，也可以在微信里 @ 我再发指令。",
        "",
        "聊天｜"+chat,
        "陪聊｜讲个笑话、讲个故事、然后呢。每次追问也要点名。",
        "生活查询｜天气 北京、百科 大熊猫、菜谱 土豆。查件用「快递 圆通 单号」，单号换成你的运单号，承运商需已接通。",
        "娱乐｜点歌 茉莉花（歌曲搜索链接）、运势、星座 白羊座。",
        "积分｜积分、周榜、月榜、总榜。发「兑换列表」看可换奖励，再发「兑换 奖励名」。",
        "群规与关键词｜发「群规」查看群规。点名后也可发送运营设置的关键词。",
    ]
    if cfg["games"]:
        start="开始 成语接龙" if "成语接龙" not in cfg.get("disabled_games",[]) else "开始 游戏名"
        lines.append(f"游戏｜发「游戏列表」看可玩的游戏，用「{start}」开局。加入 G01、状态 G01、G01 动作、退出 G01 都要换成实际局号。发起人或群管理员可用「G01 重置」「结束 G01」。")
    if cfg["polls"]:
        lines.append("投票｜「投票 V01」看结果，「投票 V01 1」选第 1 项。多选可发「投票 V01 1,2」。V01 换成实际投票编号。")
        if roles["group_admin"]:
            lines.append("创建投票｜「投票 创建 午餐|米饭|面条」。允许多选时，在主题前加「多选 」。")
    if cfg["draws"]:
        lines.append("抽签｜发「抽签 报名」参加或「抽签 退出」取消报名。")
        if roles["group_admin"]:
            lines.append("执行抽签｜「抽签 开始 1」抽一人，「抽签 重抽 1 原因」重新抽取。")
    if roles["model_admin"]:
        lines.append("智能对话管理｜在微信里选择 @ 我，再发「开启智能对话」或「关闭智能对话」。")
    if voice_policy.active(db,group["id"],group["account"],group["binding"]) is not None:
        lines.append("语音｜发一条以「二狗二狗」开头的语音，例如「二狗二狗，积分」。")
    else:
        lines.append("语音｜本群语音尚未启用。启用后，说「二狗二狗，积分」可收到语音回复。")
    lines.append("自动群管｜欢迎新人、退群提醒和定时通知由运营在后台按群设置。")
    return "\n".join(lines)
