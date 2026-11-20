"""群内鱼塘守护与偷鱼。由入站消息事务统一结算。"""
import json
import math
import random
import re
from datetime import datetime

from . import breed_metrics, breeding, fish_storage, pond_growth
from .db import BJ
from .display_names import labels
from .fishing_bait import balance
from .fishing_waters import weight

PRICES = {4: 30, 12: 80, 24: 150}
COOLDOWN = 300
SUCCESS = 40
CAUGHT = 25
TARGET = re.compile(r"偷鱼[ \t\u2005]*[@＠]([^@＠\u2005\r\n]{1,100})")
BUY = re.compile(r"(?:购买保护|鱼塘加固)\s*(4|12|24)\s*(?:小时)?")
COMMANDS = {"偷鱼", "偷鱼玩法", "鱼塘保护", "购买保护", "鱼塘加固"}


def matches(cmd):
    return cmd in COMMANDS or TARGET.fullmatch(cmd) or BUY.fullmatch(cmd)


def guard_until(db, key):
    row = db.execute("SELECT protected_until FROM fishing_raids WHERE grp=? AND member=?",key).fetchone()
    return row[0] if row else 0


def expiry(stamp):
    return datetime.fromtimestamp(stamp,BJ).strftime("%m月%d日 %H:%M")


def play(db, event, cmd, prefix):
    key = (event["grp"],event["member"])
    now = event["arrived"]
    target = json.loads(event["payload"]).get("pond_target")
    if cmd == "偷鱼玩法" or (cmd == "偷鱼" and not target):
        return (f"🐾 偷鱼玩法\n输入「{prefix}偷鱼」，再用微信 @ 一位群友。\n"
                f"每 {COOLDOWN//60} 分钟可试一次。\n"
                f"🐟 {SUCCESS}% 捞到一条，放进自己的鱼包。\n"
                f"🪿 {CAUGHT}% 被抓，赔给塘主 2～5 鱼币。\n"
                f"💨 其余时候空手离开。\n\n"
                f"鱼包、图鉴和受保护的鱼塘都安全。\n🛡️ 查看护塘\n{prefix}鱼塘保护")
    purchase = BUY.fullmatch(cmd)
    if purchase or cmd in ("鱼塘保护","购买保护","鱼塘加固"):
        until = guard_until(db,key)
        if not purchase:
            state = f"守护至 {expiry(until)}" if until>now else "当前未开启保护"
            offers = [f"{hours} 小时　{cost} 积分" for hours,cost in PRICES.items()]
            lines=["🛡️ 鱼塘保护",state,"",*offers]
            if until<=now:
                points=balance(db,key)
                if points>=PRICES[4]:
                    lines.extend(["",f"购买 4 小时，发送即扣 {PRICES[4]} 积分",f"{prefix}购买保护 4小时"])
                else:
                    lines.extend(["",f"你有 {points} 分，最短保护还差 {PRICES[4]-points} 分。",prefix+"积分帮助"])
            return "\n".join(lines)
        if until>now:
            return f"🛡️ 鱼塘已受保护，{expiry(until)} 到期。到期后可再次购买。"
        hours = int(purchase[1])
        cost = PRICES[hours]
        points = balance(db,key)
        if points<cost:
            return f"护塘 {hours} 小时需要 {cost} 积分，你有 {points} 积分。\n还差 {cost-points} 分，未扣分。查看积分用法\n{prefix}积分帮助"
        db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                      VALUES(?,?,0,'护塘',?,'guard/1',?,?,?)""",
                   (*key,-cost,event["event_id"],now,f"鱼塘加固 {hours} 小时"))
        until = now+3600*hours
        db.execute("""INSERT INTO fishing_raids(grp,member,protected_until) VALUES(?,?,?)
                      ON CONFLICT(grp,member) DO UPDATE SET protected_until=excluded.protected_until""",(*key,until))
        return f"🛡️ 护塘成功　{hours} 小时\n保护至 {expiry(until)}\n消耗 {cost} 积分，余 {points-cost} 分。"

    if not isinstance(target,str) or not target or target==event["account"]:
        return f"请在微信里输入「{prefix}偷鱼」，再从 @ 列表选一位群友。"
    if target==key[1]:
        return "这是你自己的鱼塘，换位群友试试。"
    if event["adapter_version"]=="agent-wechat-events/2.7.1" and not db.execute(
            "SELECT 1 FROM directed_events WHERE biz=?",(event["event_id"],)).fetchone():
        return "这次点名已失效，请重新发起偷鱼。"
    owner = (key[0],target)
    name = labels(db,key[0])(target,"对方")
    count = db.execute("SELECT count(*) FROM fishing_pond WHERE grp=? AND member=? AND storage='pond'",owner).fetchone()[0]
    if not count:
        return f"🌿 {name}的鱼塘空空如也，这次扑了个空。"
    eligible = """grp=? AND member=? AND storage='pond' AND NOT EXISTS
                  (SELECT 1 FROM pond_growth WHERE item=fishing_pond.id AND flagship=1)"""
    count = db.execute("SELECT count(*) FROM fishing_pond WHERE "+eligible,owner).fetchone()[0]
    if not count:
        return f"🌟 {name}塘里只有受保护的招牌鱼。"
    last = db.execute("SELECT last_attempt FROM fishing_raids WHERE grp=? AND member=?",key).fetchone()
    if last and last[0] is not None and now<last[0]+COOLDOWN:
        return f"🐾 刚去过鱼塘，{math.ceil(last[0]+COOLDOWN-now)} 秒后再来。"
    if guard_until(db,owner)>now:
        return f"🛡️ {name}的鱼塘有人守着，这一网没下水。"
    used,capacity,_ = fish_storage.occupancy(db,key,"bag")
    if used>=capacity:
        return f"🎒 鱼包已满。先发「{prefix}查看鱼包」腾一格。"
    db.execute("INSERT OR IGNORE INTO fishing_wallets(grp,member) VALUES(?,?)",key)
    db.execute("""INSERT INTO fishing_raids(grp,member,last_attempt) VALUES(?,?,?)
                  ON CONFLICT(grp,member) DO UPDATE SET last_attempt=excluded.last_attempt""",(*key,now))
    rng = random.Random(event["event_id"])
    roll = rng.randrange(100)
    if roll<SUCCESS:
        breeding.resolve(db,owner,now)
        pond_growth.settle(db,owner[0],now,owner[1])
        item = db.execute("SELECT id,fish,grams FROM fishing_pond WHERE "+eligible+" ORDER BY id LIMIT 1 OFFSET ?",(*owner,rng.randrange(count))).fetchone()
        pond_growth.leave(db,item["id"],now)
        db.execute("""UPDATE fishing_pond SET member=?,storage='bag'
                      WHERE id=? AND grp=? AND member=? AND storage='pond'""",(key[1],item["id"],*owner))
        if breeding.fry(db,item["id"]):
            db.execute("INSERT INTO breed_transfers(item,member,at) VALUES(?,?,?)",(item["id"],key[1],now))
        breed_metrics.refresh(db,owner,now)
        return (f"🐟 你在{name}的塘边轻轻一捞，网里一沉！\n"
                f"#{item['id']} {item['fish']}　{weight(item['grams'])}\n🎒 已收入你的鱼包。")
    if roll<SUCCESS+CAUGHT:
        coins = db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()[0]
        fine = min(coins,rng.randint(2,5))
        db.execute("UPDATE fishing_wallets SET coins=coins-? WHERE grp=? AND member=?",(fine,*key))
        db.execute("UPDATE fishing_wallets SET coins=coins+? WHERE grp=? AND member=?",(fine,*owner))
        result = f"🪙 赔给{name} {fine} 鱼币。" if fine else "口袋里没鱼币，只好空手溜走。"
        return "🪿 看塘鹅逮了个正着，扑着翅膀一顿胖揍！\n"+result
    return "💨 网刚伸进水里，鱼就游散了。\n你拎着空网悄悄溜走。"
