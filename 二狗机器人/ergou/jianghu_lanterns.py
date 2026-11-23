"""夜市灯谜按群与北京时间自然日轮换，点灯沿用江湖事件去重。"""

from datetime import datetime
import hashlib
import re

from .db import BJ

ANSWER = re.compile(r"夜市答\s+([0-9]{8})\s+([123])")
RIDDLES = (
    (
        "有面无口，有脚无手。客栈开饭时，大家都围着我。",
        ("饭桌", "铜镜", "茶壶"),
        1,
        "桌面和桌脚，正是谜眼。",
    ),
    (
        "一撇一捺撑开天，雨落下来，你在下边。",
        ("燕子", "油纸伞", "斗笠"),
        2,
        "撑开是伞面，合起来只剩一杆。",
    ),
    (
        "我不赶路，却把渡口的船系在岸边。",
        ("船桨", "风帆", "缆绳"),
        3,
        "解开缆绳，船才能离岸。",
    ),
    (
        "没有嗓子却报更，打一下，半条街都醒了。",
        ("木梳", "铜锣", "竹简"),
        2,
        "更夫敲锣，巷里便知道时辰。",
    ),
    (
        "肚里藏墨，身穿竹衣，老镖头拿我签押。",
        ("毛笔", "镇纸", "砚台"),
        1,
        "笔尖饱蘸墨汁，笔杆常用竹制。",
    ),
    (
        "半轮月亮揣胸前，一对燕子合成圆。老镖头用我验真假。",
        ("银锭", "铜钱", "燕印"),
        3,
        "合上两半燕印，就能核对送信人的身份。",
    ),
)


def play(db, key, event, cmd, prefix):
    day = datetime.fromtimestamp(event["arrived"], BJ).date()
    stamp = day.strftime("%Y%m%d")
    kind = "lantern/" + stamp
    solved = db.execute(
        "SELECT 1 FROM jh_events WHERE grp=? AND member=? AND chapter=2 AND event_type=?",
        (*key, kind),
    ).fetchone()
    if solved:
        return f"🏮 你已点亮今日花灯。灯谜明天换新。\n{prefix}江湖身世"
    offset = int.from_bytes(hashlib.sha256(key[0].encode()).digest()[:2], "big")
    question, choices, right, explanation = RIDDLES[
        (day.toordinal() + offset) % len(RIDDLES)
    ]
    match = ANSWER.fullmatch(cmd)
    hint = ""
    if match:
        if match[1] != stamp:
            return f"🏮 那盏灯的谜面已经换了，来看今天这盏。\n{prefix}夜市"
        if int(match[2]) == right:
            db.execute(
                "INSERT INTO jh_events VALUES(?,?,2,?,?,?)",
                (*key, kind, event["event_id"], event["arrived"]),
            )
            return f"🏮 猜中了，是{choices[right - 1]}！{explanation}\n摊主替你点亮一盏灯。\n{prefix}江湖身世"
        hint = "这次没猜中，再看看谜面。\n"
    options = "\n".join(
        f"{n}. {choice}\n{prefix}夜市答 {stamp} {n}"
        for n, choice in enumerate(choices, 1)
    )
    return f"🏮 夜市 · 一日一谜\n{hint}灯上写着：{question}\n{options}"
