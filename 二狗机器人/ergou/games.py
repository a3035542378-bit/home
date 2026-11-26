"""Built-in rule handlers. All mutable state is JSON, committed by the engine."""
from dataclasses import dataclass
import random


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    category: str
    prompt: str
    initial: callable
    move: callable
    example: tuple


def compare(b, text):
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= 32:
        raise ValueError("请输入 1 到 32 的整数")
    n = int(text)
    return n == b["target"], "偏小" if n < b["target"] else "偏大" if n > b["target"] else "猜中了"


IDIOMS = "一心一意 意气风发 发扬光大 大功告成 成千上万 万众一心 心想事成 意味深长 长驱直入 入木三分 分秒必争 争先恐后 后来居上 上下同心".split()


def chain(b, text):
    if text not in IDIOMS or text in b["used"] or text[0] != b["used"][-1][-1]:
        raise ValueError("请接上末字，使用本局词库中尚未用过的成语")
    b["used"].append(text)
    return len(b["used"]) == 4, " → ".join(b["used"])


def garden(b, text):
    if text == "浇水" and b["water"] < 2:
        b["water"] += 1
    elif text == "晒太阳" and b["water"]:
        b["water"] -= 1
        b["growth"] += 1
    elif text == "采收" and b["growth"] >= 2:
        return True, "收获了第一束向日葵"
    else:
        raise ValueError("水量上限 2；晒太阳消耗 1 水；成长到 2 后可采收")
    return False, f"水 {b['water']}/2，成长 {b['growth']}/2"


def bulls(b, text):
    if len(text) != 3 or any(c not in "123456" for c in text) or len(set(text)) != 3:
        raise ValueError("请输入三个互不重复的 1–6 数字")
    exact = sum(a == c for a, c in zip(b["key"], text))
    misplaced = len(set(text) & set(b["key"])) - exact
    return exact == 3, f"同位 {exact}，异位 {misplaced}"


def hanoi(b, text):
    if text not in ("AB","AC","BA","BC","CA","CB"):
        raise ValueError("例如 AC 表示把 A 顶部圆盘移到 C")
    a, c = (b[p] for p in text)
    if not a or (c and c[-1] < a[-1]):
        raise ValueError("空柱不能取盘，大盘不能压小盘")
    c.append(a.pop())
    return len(b["C"]) == 3, "  ".join(p + str(b[p]) for p in "ABC")


def jug(b, text):
    x, y = b["三"], b["五"]
    moves = {"装三":(3,y),"装五":(x,5),"倒三":(0,y),"倒五":(x,0),
             "三入五":(max(0,x+y-5),min(5,x+y)), "五入三":(min(3,x+y),max(0,x+y-3))}
    if text not in moves or moves[text] == (x,y):
        raise ValueError("装三、装五、倒三、倒五、三入五、五入三；操作须改变水量")
    b["三"], b["五"] = moves[text]
    return b["五"] == 4, f"三升壶 {b['三']}，五升壶 {b['五']}"


def crossing(b, text):
    if text not in ("空船","狼","羊","菜"):
        raise ValueError("可选 空船、狼、羊、菜")
    side = b["人"]
    if text != "空船" and b[text] != side:
        raise ValueError("乘客不在船这一侧")
    trial = dict(b)
    trial["人"] = 1-side
    if text != "空船":
        trial[text] = 1-side
    if trial["羊"] == side and (trial["狼"] == side or trial["菜"] == side):
        raise ValueError("无人照看的一岸不能留下狼和羊或羊和菜")
    b.update(trial)
    return all(trial.values()), "彼岸：" + "".join(k for k,v in b.items() if v)


def lights(b, text):
    if text not in list("12345"):
        raise ValueError("输入灯号 1–5")
    i = int(text)-1
    for j in range(max(0,i-1), min(5,i+2)):
        b["lamps"][j] ^= 1
    return not any(b["lamps"]), "".join("亮" if v else "暗" for v in b["lamps"])


def ladder(b, text):
    if text not in ("COLD","CORD","CARD","WARD","WARM","WORD","WORM") or text in b["seen"] or sum(a!=c for a,c in zip(b["seen"][-1],text)) != 1:
        raise ValueError("请在所列词中选一个，只换一个字母且不重复")
    b["seen"].append(text)
    return text == "WARM", " → ".join(b["seen"])


BUILTINS = [
    Game("higher","猜数字","猜题","猜 1–32 的秘密整数，根据偏大/偏小继续。",lambda r: {"target":r.randint(1,32)},compare,()),
    Game("bulls","密码破译","猜题","猜三位互异的 1–6 数字，按同位与异位数量推理。",lambda r: {"key":"".join(r.sample("123456",3))},bulls,()),
    Game("idioms","成语接龙","文字互动","从一心一意起，首尾同字连三次。词库："+"、".join(IDIOMS),lambda r:{"used":["一心一意"]},chain,("意气风发","发扬光大","大功告成")),
    Game("ladder","英文词梯","文字互动","从 COLD 到 WARM，每次换一个字母。词库 COLD CORD CARD WARD WARM WORD WORM。",lambda r:{"seen":["COLD"]},ladder,("CORD","CARD","WARD","WARM")),
    Game("garden","向日葵花圃","模拟养成","浇水储水，晒太阳消耗水换成长。成长达到 2 后采收。",lambda r:{"water":0,"growth":0},garden,("浇水","晒太阳","浇水","晒太阳","采收")),
    Game("hanoi","汉诺塔","文字互动","三盘从 A 搬到 C。输入 AC 等两柱名，每次挪顶盘，大盘不能压小盘。",lambda r:{"A":[3,2,1],"B":[],"C":[]},hanoi,("AC","AB","CB","AC","BA","BC","AC")),
    Game("jugs","量水工坊","模拟养成","用 3 升和 5 升壶量出 4 升。装三、装五、倒三、倒五、三入五、五入三。",lambda r:{"三":0,"五":0},jug,("装五","五入三","倒三","五入三","装五","五入三")),
    Game("river","摆渡难题","文字互动","把狼羊菜全部送过河。每航次选狼、羊、菜或空船，防止无人看守时相食。",lambda r:dict.fromkeys("人狼羊菜",0),crossing,("羊","空船","狼","羊","菜","空船","羊")),
    Game("lights","连锁熄灯","猜题","灯列 亮亮暗亮亮。输入 1–5 同时翻转本灯及邻灯，使全暗。",lambda r:{"lamps":[1,1,0,1,1]},lights,("1","5")),
]
from . import boardgames, simgames, wordgames
from .scenarios import SCENARIOS

QUIZZES={
    "song_quiz":("猜歌名","根据题面猜歌名",(
        ("北京奥运会开幕前，百位歌手合唱欢迎远客，五个字。","北京欢迎你"),("送别朋友，题名就是告别时的两个字，李叔同填词。","送别"),("两只动物跑得快，一只少耳朵，一只少尾巴。","两只老虎"),
        ("一闪一闪挂在夜空，童谣，三个字。","小星星"),("一朵芳香的白花，江苏民歌，三个字。","茉莉花"),
        ("儿时拿着报纸沿街跑的小朋友，老儿歌，三个字。","卖报歌"))),
    "idiom_quiz":("猜成语","根据描述猜一个四字成语",(
        ("把禾苗往上拉，以为能帮它长高。","拔苗助长"),("守在树桩旁，盼着第二只兔子撞来。","守株待兔"),("捂住自己的耳朵，以为偷铃时别人也听不见。","掩耳盗铃"),
        ("给蛇添上它本来没有的肢体。","画蛇添足"),("井底的一只青蛙抬头看天。","井底之蛙"),
        ("客人把杯里映出的弓影看成了蛇。","杯弓蛇影"))),
    "emoji_quiz":("猜图片","根据表情图猜一个四字成语",(
        ("🐍 ✏️ 🦶","画蛇添足"),("👂 🚫 🔔","掩耳盗铃"),("🐴 🐴 🐯 🐯","马马虎虎"),
        ("🐔 ✈️ 🥚 💥","鸡飞蛋打"),("🐟 👁️ 🔀 💎","鱼目混珠"),("🐉 ✈️ 🐦 💃","龙飞凤舞"))),
}


def quiz_board(rng,questions):
    clue,answer=rng.choice(questions)
    return {"clue":clue,"answer":answer}


def guess_quiz(board,text):
    if text.strip(" 《》！。")!=board["answer"]:
        raise ValueError("还没猜中，再看看题面："+board["clue"])
    return True,"猜对了！答案是"+board["answer"]


for quiz_id,(name,instructions,questions) in QUIZZES.items():
    BUILTINS.append(Game(quiz_id,name,"猜题",instructions+"。",lambda rng,pool=questions:quiz_board(rng,pool),guess_quiz,()))

for scenario in SCENARIOS:
    opening = scenario.instructions + " 起始：" + scenario.describe(scenario.start)
    opening += "。可行动作：" + " / ".join(scenario.choices(scenario.start))
    BUILTINS.append(Game(scenario.id, scenario.name, scenario.category, opening,
                         lambda rng, initial=scenario.start: {"state": list(initial)},
                         scenario.move, ()))
GAMES = {g.name:g for g in BUILTINS}
RULE_VERSION = "1.0"


def start_board(game, event_id):
    return game.initial(random.Random(event_id))


def visible_board(game_id, board):
    if game_id in QUIZZES:
        return "题面："+board["clue"]
    if game_id in ("higher","bulls"):
        return "谜底由裁判保管"
    for scenario in SCENARIOS:
        if scenario.id==game_id:
            state=board["state"]
            return scenario.describe(state)+"。可行动作："+" / ".join(scenario.choices(state))
    if "node" in board:
        return board["node"]
    return "、".join(f"{k}={v}" for k,v in board.items())


def example(game, board):
    if game.id in QUIZZES:
        return [board["answer"]]
    for scenario in SCENARIOS:
        if scenario.id == game.id:
            return scenario.solution()
    if game.id == "higher":
        return [str(board["target"])]
    if game.id == "bulls":
        return [board["key"]]
    return game.example



def turn_hint(name, rules, board, code, prefix):
    """从当前盘面取一个可执行的动作，不读取猜谜的谜底。"""
    if "plugin" in rules:
        candidates=rules["plugin"]["states"][board["node"]]
        action=next(iter(candidates),None)
    else:
        game=GAMES[name]
        if rules.get("quiz_origin"):
            return f"题面：{board['clue']}\n发「{prefix}＋答案」参与。发起人可发「{prefix}停止游戏」。" if board["phase"]=="question" else f"本题已揭晓。发起人可发「{prefix}继续」。"
        if game.id in QUIZZES:
            return f"题面：{board['clue']}\n猜到后，在「{prefix}{code} 」后写答案。"
        scenario=next((s for s in SCENARIOS if s.id==game.id),None)
        if scenario:
            action=next(iter(scenario.choices(board["state"])),None)
        elif game.id in ("higher","bulls"):
            action="16" if game.id=="higher" else "123"
        else:
            from copy import deepcopy
            candidates={"idioms":IDIOMS,"hanoi":("AB","AC","BA","BC","CA","CB"),
                        "ladder":("COLD","CORD","CARD","WARD","WARM","WORD","WORM")}.get(game.id,game.example)
            action=None
            for candidate in candidates:
                try:
                    game.move(deepcopy(board),candidate)
                except ValueError:
                    continue
                action=candidate
                break
    if action:
        return f"可以这样走一步\n{prefix}{code} {action}"
    return f"这一步没有可用动作，先看盘面\n{prefix}状态 {code}"
