"""群内赞美与积分礼物，赠礼流水和收藏同事务提交。"""
import json
import random
import re

from .display_names import labels
from .fishing_bait import BAITS,balance
from .fishing_cards import JournalReply
from .group_tools import CHECKIN_POINTS
from .player_profile import WORK_POINTS


DAILY=CHECKIN_POINTS+WORK_POINTS
PRICES={"小雏菊":max(1,DAILY//2),"奶茶":DAILY,"蛋糕":BAITS["高级鱼饵"].points,
        "小鱼玩偶":2*DAILY,"星星瓶":3*DAILY,"玫瑰花束":BAITS["顶级鱼饵"].points}
PRAISE=("你总能看见别人做得好的小事。","和你一起聊天，冷场也能变成笑场。",
        "你一来，就像池塘边多了一盏小灯。")


def handle(db,event,cmd,prefix):
    group,actor=event["grp"],event["member"]
    key=(group,actor)
    if cmd=="礼物商店":
        entries=[(name,f"{price} 积分") for name,price in PRICES.items()]
        guide=f"{prefix}送礼 小雏菊 @群友"
        body="礼物商店\n"+"\n".join(name+"  "+price for name,price in entries)+f"\n本群余额 {balance(db,key)} 积分\n"+guide
        return JournalReply(body,heading="礼物商店",title="挑一件小礼物",subtitle=f"本群余额 {balance(db,key)} 积分",
                            entries=entries,notes=["从微信成员列表选中一位群友。发送即扣对应积分。"],commands=[guide])
    if cmd=="我的礼物":
        entries=[(r[0],f"收到 {r[1]} 件") for r in db.execute("""SELECT gift,count(*) FROM social_gifts
                 WHERE grp=? AND recipient=? GROUP BY gift ORDER BY max(ledger_id) DESC""",key)]
        text="\n".join(n+"  "+v for n,v in entries) or "暂时还没收到礼物。"
        return JournalReply("我的礼物\n"+text,heading="礼物收藏",title="我的礼物",subtitle="本群收到的礼物",
                            entries=entries,commands=[prefix+"礼物商店"])
    praise=cmd.startswith("赞美")
    words=re.split(r"\s*[@＠]",cmd,maxsplit=1)
    gift=words[0].removeprefix("送礼").strip()
    if not praise and gift not in PRICES:
        return f"请先选礼物，再从成员列表选一人。\n{prefix}礼物商店"
    payload=json.loads(event["payload"])
    mode=db.execute("SELECT mode FROM account WHERE id=?",(event["account"],)).fetchone()[0]
    target=None
    if mode=="simulation" and len(words)==2:
        member=words[1].strip()
        if db.execute("SELECT 1 FROM simulation_members WHERE grp=? AND member=?",(group,member)).fetchone():
            target=member
    elif event["adapter_version"]=="agent-wechat-events/2.7.1" and payload.get("social_group")==group:
        target=payload.get("social_target")
    if cmd=="赞美":
        return random.Random(event["event_id"]).choice(PRAISE)
    if payload.get("social_lookup_failed"):
        return "暂时无法核实对方的群成员身份，请稍后重新选择群友。"
    if not target or target in (actor,event["account"]):
        return "请从本群微信成员列表选中另一位群友。"
    label=labels(db,group)(target)
    if praise:
        return label+"，"+random.Random(event["event_id"]).choice(PRAISE)
    price=PRICES[gift]
    available=balance(db,key)
    if available<price:
        return f"{gift}需要 {price} 积分，你还差 {price-available} 分。\n{prefix}积分"
    debit=db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
              VALUES(?,?,0,'赠礼',?,'gift/1',?,?,?) RETURNING id""",(*key,-price,event["event_id"],event["arrived"],gift)).fetchone()[0]
    db.execute("INSERT INTO social_gifts VALUES(?,?,?,?,?,?)",(debit,event["event_id"],group,actor,target,gift))
    body=f"已送给{label}一份{gift}，扣 {price} 积分，余额 {available-price} 分。"
    reply=JournalReply(body,heading="礼物手记",title=gift,subtitle="赠给  "+label,
                       facts=[("花费",f"{price} 积分"),("赠送后余额",f"{available-price} 分")],commands=[prefix+"我的礼物"])
    reply.card["gift"]=gift
    return reply
