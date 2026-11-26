"""群内连续猜题。轮次保存在盘面，提醒经现有发件箱发送。"""
import json
import random

from .db import dump
from .display_names import mention_sender
from .games import QUIZZES

QUESTION_SECONDS = 120
CONTINUE_SECONDS = 180


def active(db, group):
    return db.execute("""SELECT * FROM games WHERE grp=? AND state='RUNNING'
        AND json_extract(rules,'$.quiz_origin') IS NOT NULL""", (group,)).fetchone()


def prompt(row, board, prefix):
    reward = "本局仅首个正确答案可领积分。\n" if board["number"] == 1 else ""
    instruction="只填方框缺的字" if row["game"]=="猜歌词" else "全群可答"
    return (f"🎮 {row['code']} {row['game']} · 第 {board['number']} 题\n题面：{board['clue']}\n"
            f"{instruction}，直接发「{prefix}＋答案」。限时 2 分钟。\n"
            f"{reward}发起人可发：{prefix}停止游戏")


def choose(db, quiz_id, event, used, previous=None):
    pool=QUIZZES[quiz_id][2]
    choices=[pair for pair in pool if pair[1] not in used]
    if not choices:
        used.clear()
        choices=[pair for pair in pool if pair[1]!=previous]
    history=dict(db.execute("SELECT answer,last_seq FROM quiz_history WHERE grp=?", (event["grp"],)))
    oldest=min(history.get(answer,0) for _,answer in choices)
    candidates=[pair for pair in choices if history.get(pair[1],0)==oldest]
    clue,answer=random.Random(event["event_id"]).choice(candidates)
    db.execute("""INSERT INTO quiz_history VALUES(?,?,?) ON CONFLICT(grp,answer)
                  DO UPDATE SET last_seq=excluded.last_seq""",(event["grp"],answer,event["seq"]))
    return clue,answer


def advance(db, row, board, event, prefix):
    quiz_id=json.loads(row["rules"])["game_id"]
    clue,answer=choose(db,quiz_id,event,board["used"],board["answer"])
    board.update(clue=clue, answer=answer, number=board["number"]+1, phase="question")
    board["used"].append(answer)
    db.execute("UPDATE games SET board=?,deadline=? WHERE id=?",
               (dump(board),event["arrived"]+QUESTION_SECONDS,row["id"]))
    return prompt(row, board, prefix)


def end(db,row,board,now):
    text=f"🏁 {row['game']}已结束，共答对 {board['solved']} 题。"
    db.execute("UPDATE games SET state='FINISHED',ended=?,reason=? WHERE id=?", (now,text,row["id"]))
    return text


def handle(db,row,event,text,prefix,*,explicit=False):
    board=json.loads(row["board"])
    if text in ("停止游戏","继续"):
        if event["member"] != row["owner"]:
            raise ValueError("这局由发起人决定是否继续或停止。")
        if text=="停止游戏":
            return end(db,row,board,event["arrived"])
        if board["phase"]=="question":
            return prompt(row,board,prefix)
        return advance(db,row,board,event,prefix)
    if board["phase"]!="question" or event["arrived"]>=row["deadline"]:
        return "本题已截止，等发起人决定是否继续。" if explicit else None
    guess=text.strip(" 《》！。!?？.，,")
    if guess=="揠苗助长" and board["answer"]=="拔苗助长":
        guess=board["answer"]
    if guess!=board["answer"]:
        questions=QUIZZES[json.loads(row["rules"])["game_id"]][2]
        if explicit or any(guess==answer for _,answer in questions):
            raise ValueError("还没猜中，再看看题面："+board["clue"])
        return None
    from .engine import victory_reward
    mention_sender(db,event)
    prize=victory_reward(db,event,row,json.loads(row["rules"])) if board["solved"]==0 else ""
    board["solved"]+=1
    return f"🎉 答对了！{board['answer']}。{prize}\n\n"+advance(db,row,board,event,prefix)


def due(db, now, group=None):
    rows=db.execute("""SELECT * FROM games WHERE state='RUNNING' AND deadline<=?
        AND json_extract(rules,'$.quiz_origin') IS NOT NULL AND (? IS NULL OR grp=?)
        AND NOT EXISTS (SELECT 1 FROM inbox i WHERE i.grp=games.grp AND i.state='PENDING'
                        AND i.arrived<games.deadline)""",(now,group,group)).fetchall()
    for row in rows:
        g=db.execute("SELECT * FROM groups WHERE id=?",(row["grp"],)).fetchone()
        cfg=json.loads(g["config"])
        rules=json.loads(row["rules"])
        board=json.loads(row["board"])
        if (not cfg["enabled"] or not cfg["games"] or g["paused"] or row["game"] in cfg.get("disabled_games",[])
                or [g["account"],g["binding"]]!=rules["quiz_binding"]):
            end(db,row,board,now)
            continue
        prefix=cfg["prefix"]
        reveal=board["phase"]=="question"
        if reveal:
            body=(f"⏳ {row['code']} 时间到！答案是「{board['answer']}」。还玩吗？\n"
                  f"{prefix}继续\n也可以发「{prefix}停止游戏」，3 分钟未回应就收场。")
            board["phase"]="waiting"
            db.execute("UPDATE games SET board=?,deadline=? WHERE id=?",(dump(board),now+CONTINUE_SECONDS,row["id"]))
        else:
            body=end(db,row,board,now)
        key=f"quiz/{row['id']}/{board['number']}/"+("answer" if reveal else "end")
        task=db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
            VALUES(?,?,?,?,?,'PENDING',?,?,?)""",(key,g["account"],g["id"],g["binding"],body,now,now+120,now)).lastrowid
        db.execute("INSERT INTO quiz_notices VALUES(?,?,?,?,?)",(task,row["id"],board["number"],int(reveal),body))
