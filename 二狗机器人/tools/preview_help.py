"""在项目目录运行 python3 -m tools.preview_help，以隔离微信事件生成文案预览。"""
from pathlib import Path

from ergou.feature_menu import TOPICS
from tests.test_help_walkthrough import HelpWalkthrough
from tests.test_fish_receipts import FishReceipts
from tests.test_pond_directory import PondDirectoryTests


def sample(command, reply):
    return f"玩家发送\n\n```text\n{command}\n```\n\n二狗回复\n\n```text\n{reply}\n```"


def main():
    replay = HelpWalkthrough()
    pond = PondDirectoryTests()
    output = ["# 二狗微信群文案预览",
              "正文来自隔离微信事件的回执。鱼号、账号、权限及余额均为测试数据。天气、百科及快递使用模拟供应商。"]
    output.extend([
        "## 验收范围",
        "回放取监听器入站后生成的出站正文。微信原生提及由发送层附加，不在正文拼接昵称。"
        "时间、鱼获及繁育结果在指定场景中受控。列宽按 Unicode 字符宽度检查，微信真机换行还未验证。",
        "| 模块 | 检查的入口和状态 | 验证方式 |\n|---|---|---|\n"
        "| 抛竿、鱼饵、钓场与巨物 | 上钩入包、脱钩、断线与折竿、稀有度、活动预告与结束 | 微信入站样例和钓鱼、巨物业务回归 |\n"
        "| 鱼包、鱼塘、成长位 | 空满、翻页、投喂、详情、替换成长位、招牌和出售 | 微信入站、容量与资产断言 |\n"
        "| 繁育 | 选亲鱼、报价过期、确认、等待、失败、塘满与重复领取 | 连续微信事件，核对钱包、成长位和幼鱼数 |\n"
        "| 图鉴和展馆 | 首展、换展、回包、混合跳过、范围和批次上限 | 微信入站，核对库存与展品编号 |\n"
        "| 装备与偷鱼 | 强化、重铸、护塘、偷取和赔付 | 帮助示例入站、护塘业务回归 |\n"
        "| 积分与群榜 | 签到、重复签到、兑换、资产和纪录口径 | 微信入站及积分、榜单回归 |\n"
        "| 天气与生活 | 城市、词条、找歌、菜谱、快递、运势和星座 | 帮助与示例入站，外部查询使用模拟供应商 |\n"
        "| 游戏、投票和抽签 | 开局后实际动作、投票查询和报名 | 帮助示例入站、游戏与群服务回归 |\n"
        "| 聊天、群规与管理 | 关键词、角色权限、群绑定和智能分流 | 菜单回放及权限、路由回归 |",
    ])
    for heading,case in (
        ("抛竿、鱼包与首次点亮","test_card_and_first_exhibits"),
        ("亲鱼从换位到领取","test_parent_steps_and_expired_quote"),
        ("繁育失败与塘满待领","test_full_pond_claim_and_failed_pair"),
        ("展出、换展与部分跳过","test_mixed_batch_and_invalid_inputs"),
        ("天气查无结果、投票已截止","test_group_service_outcomes_at_ingress"),
        ("大重量、多位编号与满包换展","test_heaviest_feasible_exhibit_when_bag_is_full"),
    ):
        scenario=FishReceipts(case)
        try:
            scenario.setUp()
            getattr(scenario,case)()
            output.append("## "+heading)
            output.extend(sample(command,body) for command,body in scenario.trace)
        finally:
            scenario.doCleanups()
    preferred = {"天气":"天气 抚州","钓鱼":"抛竿","积分":"签到","鱼塘":"投喂#71","聊天":"讲个故事",
                 "鱼包":"查看鱼包","游戏":"开始 成语接龙","繁育":"繁育配对","绑定":"绑定状态"}
    try:
        replay.setUp()
        replay.test_every_topic_and_copyable_command()
        replay.test_management_and_binding()
        replay.test_personal_steps_and_feature_gates()
        for name in ["主菜单", *(t.name for t in TOPICS)]:
            command, reply, steps = replay.replays[name]
            output.extend(["## "+name, sample(command,reply)])
            next_command = "二狗"+preferred.get(name,"")
            action, response = next((row for row in steps if row[0]==next_command),steps[0])
            output.extend(["**从这页继续**", sample(action,response)])
            output.extend(sample(cmd,body) for cmd,body in steps if cmd!=action)
        player = replay.player()
        for command in ("全菜单","鱼包","卖鱼","卖鱼#71","签到","签到","兑换列表","兑换 选片权","游戏列表","抛竿","巨物鱼讯"):
            output.extend(["## 操作回执 · "+command,sample("二狗"+command,replay.follow(player,"二狗"+command))])
        pond.setUp()
        pond.scenario()
        for command in ("鱼塘","鱼塘操作","查看鱼#82","放入图鉴","点亮图鉴#82 #77","图鉴榜"):
            reply = pond.send("二狗"+command)
            assert reply and "没看懂" not in reply
            output.extend(["## 操作回执 · "+command,sample("二狗"+command,reply)])
        player.db.execute("UPDATE groups SET config=json_set(config,'$.prefix','团团')")
        custom = replay.follow(player,"团团查天气帮助")
        last = custom.splitlines()[-1]
        output.extend(["## 自定义前缀", sample("团团查天气帮助",custom),sample(last,replay.follow(player,last))])
    finally:
        pond.doCleanups()
        replay.doCleanups()
    Path(__file__).resolve().parents[1].joinpath("群聊文案微信回放.md").write_text("\n\n".join(output)+"\n")


if __name__=="__main__":
    main()
