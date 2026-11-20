"""在项目目录运行 python3 -m tools.preview_help，以隔离微信事件生成文案预览。"""
from pathlib import Path

from ergou.feature_menu import TOPICS
from tests.test_help_walkthrough import HelpWalkthrough
from tests.test_pond_directory import PondDirectoryTests


def sample(command, reply):
    return f"玩家发送\n\n```text\n{command}\n```\n\n二狗回复\n\n```text\n{reply}\n```"


def main():
    replay = HelpWalkthrough()
    pond = PondDirectoryTests()
    output = ["# 二狗微信群文案预览",
              "正文来自隔离微信事件的回执。鱼号、账号、权限及余额均为测试数据。天气、百科及快递使用模拟供应商。"]
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
