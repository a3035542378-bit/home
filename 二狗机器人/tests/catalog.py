from pathlib import Path
from ergou.games import GAMES,example,start_board


if __name__=="__main__":
    intro="""# 游戏交付目录

共 GAME_COUNT 个内置规则 ID。每一行给出启动名、所属类别、局面与动作规则，以及一条可重放的完成路径。随机谜底的示例使用固定种子 catalog，实际开局由事件标识产生。自动验收结果见 [逐游戏记录](GAME_RESULTS.csv)。

## 共用规则

每款使用内置引擎/规则版本 1.0、项目内编写的规则与素材。断网可玩。人数 1–32，允许中途加入；发起人自动入局，其他成员先报名。单回合共享局面，每次合法动作以入站序列推进，首位达成目标者结束本局。错误尝试无扣分，默认奖励 10 分。每日奖励次数上限默认为不限，可按群配置，规则随开局快照。单局 10 分钟，截止时无奖励。无定时额外提示，部分游戏按动作反馈线索。成员可退出，发起人可取消，取消无奖。重启读取持久局面；同一内置规则版本可继续。独立玩法及难度适宜性需运营方逐项评审。

命令示例为 `二狗 开始 游戏名` → `二狗 加入 G01` → `二狗 G01 动作`。发起人可用 `二狗 G01 重置` 回到本局初始状态。固定测试遵循开局、参与、无效动作、完成全局、唯一积分和重复输入。同一游戏的别名、皮肤和题目不另计。
"""
    chunks=[intro.replace("GAME_COUNT",str(len(GAMES)))]
    for category in ("猜题","文字互动","模拟养成"):
        chunks += ["\n## "+category+"\n","|game_id|游戏|规则与起始状态|完成路径（示例）|","|---|---|---|---|"]
        for game in GAMES.values():
            if game.category!=category:continue
            moves=example(game,start_board(game,"catalog"))
            chunks.append("|"+"|".join([game.id,game.name,game.prompt.replace("|","/")," → ".join(moves)])+"|")
    Path("GAMES.md").write_text("\n".join(chunks)+"\n",encoding="utf-8")

