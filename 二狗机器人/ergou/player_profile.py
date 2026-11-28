"""本群的休闲档案、里程碑和每日打工。"""
from datetime import datetime
import json
import random

from . import angler
from .db import BJ
from .display_names import labels, mention_sender
from .fishing_bait import balance
from .fishing_cards import JournalReply


WORK_POINTS = 1
SHIFTS = (
    ("咖啡店店员","你拉了个歪歪的小鱼花，客人舍不得喝第一口。"),
    ("渔场管理员","你收好池边的抄网，顺手捞起了一只离家出走的拖鞋。"),
    ("花店助手","你给最后一束小雏菊系上棉线，花尖刚好露出包装纸。"),
    ("图书馆管理员","你从还书箱里找到一张银杏叶书签，替读者夹回扉页。"),
    ("海洋馆饲养员","喂食铃刚响，小鱼就排到了玻璃跟前。"),
    ("宠物店助手","刚叠好的毛巾被小猫占了座。你给它留了一条。"),
    ("便利店店员","雨停时，你把借出去的最后一把伞挂回了门口。"),
    ("咖啡店店员","熟客今天点了热牛奶，你照例在杯套上画了片叶子。"),
)


def work(db,event,prefix):
    key=event["grp"],event["member"]
    job,story=random.Random(event["event_id"]).choice(SHIFTS)
    earned=db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
        VALUES(?,?,0,'打工',?,'work/1',?,?,?) ON CONFLICT DO NOTHING RETURNING id""",
        (*key,WORK_POINTS,event["event_id"],event["arrived"],job)).fetchone()
    mention_sender(db,event)
    points=balance(db,key)
    if earned is None:
        return f"今天在本群已经收工，积分余额 {points} 分。明天再来。"
    return f"今日打工 · {job}\n{story}\n到账 {WORK_POINTS} 积分，本群余额 {points} 分。\n{prefix}个人档案"


def profile(db,event,prefix,achievements_only=False):
    key=event["grp"],event["member"]
    midnight=datetime.fromtimestamp(event["arrived"],BJ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    days={r["kind"]:r for r in db.execute("""SELECT kind,count(*) total,max(at)>=? today FROM ledger
        WHERE grp=? AND member=? AND kind IN ('签到','打工') GROUP BY kind""",(midnight,*key))}
    wallet=db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()
    catches=db.execute("SELECT count FROM fishing_records WHERE grp=? AND member=?",key).fetchone()
    caught=catches[0] if catches else 0
    casts=db.execute("SELECT casts FROM fishing_experience WHERE grp=? AND member=?",key).fetchone()
    exhibited=db.execute("SELECT count(*) FROM fishing_exhibits WHERE grp=? AND member=?",key).fetchone()[0]
    played=db.execute("""SELECT count(*) FROM participation p JOIN games g ON g.id=p.game
                         WHERE g.grp=? AND p.member=?""",key).fetchone()[0]
    victories=db.execute("SELECT count(*) FROM ledger WHERE grp=? AND member=? AND kind='胜利'",key).fetchone()[0]
    milestones=(("渔场新手",caught,1),("十尾鱼获",caught,10),("图鉴初藏",exhibited,1),
                ("首场胜利",victories,1),("初次签到",days["签到"]["total"] if "签到" in days else 0,1),
                ("第一次收工",days["打工"]["total"] if "打工" in days else 0,1))
    badges=[title for title,count,goal in milestones if count>=goal]
    badges_text="、".join(badges) or "尚无，第一次签到或钓获就能点亮。"
    if achievements_only:
        entries=[(title,("已点亮" if count>=goal else "未点亮")+f"  ·  {min(count,goal)}/{goal}") for title,count,goal in milestones]
        goals=("首次钓获","累计钓获","收录鱼种","游戏获胜","本群签到","本群打工")
        pending=[f"{goal} {count}/{total}" for goal,(_,count,total) in zip(goals,milestones) if count<total]
        summary="\n待点亮 · "+"、".join(pending) if pending else ""
        return JournalReply(f"成就手册\n{badges_text}{summary}\n{prefix}个人档案",heading="成就手册",title="本群里程碑",
                            subtitle=f"点亮 {len(badges)}/{len(entries)} 项",entries=entries,commands=[prefix+"个人档案"])
    nickname=labels(db,key[0])(key[1],json.loads(event["payload"]).get("name"))
    group=db.execute("SELECT alias FROM group_profile WHERE grp=?",key[:1]).fetchone()
    lines=["个人档案 · "+(nickname if nickname!="一位群成员" else "我的记录"),
           group[0] if group and group[0] else "当前群组：本群",
           f"积分 {balance(db,key)} 分"]
    if wallet or catches:
        lines.append(f"钓手 {angler.level(casts[0] if casts else caught)} 级  ·  钓获 {caught} 条")
        if wallet:
            lines.append(f"鱼币 {wallet[0]}  ·  图鉴已点亮 {exhibited} 种")
    if played or victories:
        lines.append(f"已登记参局 {played} 局  ·  获胜到账 {victories} 次")
    lines.extend(["成就  "+badges_text,"今日进度"])
    for activity in ("签到","打工"):
        lines.append(activity+"已完成" if activity in days and days[activity]["today"] else prefix+activity)
    facts=[("积分",str(balance(db,key)))]
    if wallet:
        facts.append(("鱼币",str(wallet[0])))
    if wallet or catches:
        facts.extend([("钓手",f"{angler.level(casts[0] if casts else caught)} 级"),("累计钓获",f"{caught} 条"),
                      ("已点亮图鉴",f"{exhibited} 种")])
    if played or victories:
        facts.extend([("已登记参局",str(played)),("获胜到账",str(victories))])
    return JournalReply("\n".join(lines),heading="个人档案",title=nickname if nickname!="一位群成员" else "我的记录",
                        subtitle=lines[1],facts=facts,notes=["本群成就  "+badges_text,
                        *[a+("已完成" if a in days and days[a]["today"] else "待完成") for a in ("签到","打工")]],
                        commands=[prefix+"成就手册",*[prefix+a for a in ("签到","打工") if a not in days or not days[a]["today"]]])
