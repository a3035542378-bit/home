import hashlib
import json
import random
from datetime import datetime
from .db import BJ, dump


def poll(db, e, args, manager):
    group, member, now = e["grp"], e["member"], e["arrived"]
    if args.startswith("创建 "):
        if not manager:
            raise ValueError("FORBIDDEN 群管理员可创建")
        fields = [f.strip() for f in args[3:].split("|")]
        if len(fields) < 3 or len(fields) > 10 or any(not f or len(f)>80 for f in fields):
            raise ValueError("用法：投票 创建 [多选 ]主题|选项一|选项二（最多九项）")
        title, *opts = fields
        if len(set(opts)) != len(opts):
            raise ValueError("选项重复")
        multi = title.startswith("多选 ")
        cur = db.execute("INSERT INTO polls(grp,title,options,multi,owner,deadline) VALUES(?,?,?,?,?,?)",
                         (group,title.removeprefix("多选 "),dump(opts),multi,member,now+600))
        return f"🗳️ 投票 V{cur.lastrowid:02}　{title.removeprefix('多选 ')}\n⏳ 10 分钟后截止\n\n" + "\n".join(f"{i}. {s}" for i,s in enumerate(opts,1))
    parts = args.split()
    if not parts or not parts[0].startswith("V") or not parts[0][1:].isdigit():
        raise ValueError("用法：投票 V01 [1,2]，省略选项查看结果")
    row = db.execute("SELECT * FROM polls WHERE id=? AND grp=?", (parts[0][1:],group)).fetchone()
    if not row:
        raise ValueError("投票不存在")
    opts = json.loads(row["options"])
    if len(parts) > 1:
        if now >= row["deadline"]:
            raise ValueError("投票已截止")
        digits = parts[1].split(",")
        if len(parts)!=2 or any(v not in [str(i) for i in range(1,len(opts)+1)] for v in digits):
            raise ValueError("选项编号无效")
        choices = sorted(set(map(int,digits)))
        if not row["multi"] and len(choices)!=1:
            raise ValueError("单选投票只能选一项")
        db.execute("INSERT OR REPLACE INTO ballots VALUES(?,?,?)",(row["id"],member,dump(choices)))
    votes = [json.loads(r[0]) for r in db.execute("SELECT choices FROM ballots WHERE poll=?", (row["id"],))]
    counts = [sum(i in ballot for ballot in votes) for i in range(1,len(opts)+1)]
    return f"🗳️ {row['title']}　V{row['id']:02}\n👥 {len(votes)} 人参与\n\n" + "\n".join(f"{i}. {s}　{n}票" for i,(s,n) in enumerate(zip(opts,counts),1))


def draw(db,e,args,manager):
    group,member=e["grp"],e["member"]
    if args == "报名":
        db.execute("INSERT OR IGNORE INTO candidates VALUES(?,?)",(group,member))
        return "🎟️ 已加入本群报名池"
    if args == "退出":
        db.execute("DELETE FROM candidates WHERE grp=? AND member=?",(group,member))
        return "🎟️ 已退出报名池"
    if not manager:
        raise ValueError("FORBIDDEN 群管理员可执行抽取")
    parts=args.split(maxsplit=2)
    if not parts or parts[0] not in ("开始","重抽") or (parts[0]=="重抽" and len(parts)!=3):
        raise ValueError("用法：抽签 开始 [人数] 或 抽签 重抽 人数 原因")
    pool=[r[0] for r in db.execute("SELECT member FROM candidates WHERE grp=? ORDER BY member",(group,))]
    if len(parts)>1 and not parts[1].isdigit():
        raise ValueError("人数必须是整数")
    n=int(parts[1]) if len(parts)>1 else 1
    if not 1 <= n <= len(pool):
        raise ValueError("抽取人数超过候选范围或为零")
    winners=random.Random(e["event_id"]).sample(pool,n)
    cur=db.execute("INSERT INTO draws(grp,event,member,at,pool,winners,reason) VALUES(?,?,?,?,?,?,?)",
                   (group,e["event_id"],member,e["arrived"],dump(pool),dump(winners),parts[2] if len(parts)>2 else "首次抽取"))
    from .display_names import labels
    name=labels(db,group)
    return f"🎉 抽签 D{cur.lastrowid}　共 {n} 人\n"+"\n".join(f"{i}. {name(uid)}" for i,uid in enumerate(winners,1))


def fortune(member, now):
    day=datetime.fromtimestamp(now,BJ).date().isoformat()
    value=hashlib.sha256((member+day).encode()).digest()[0]
    return "🍀 今日娱乐签\n"+("宜散步，留意路边的花。","宜读书，记下一句喜欢的话。","宜整理，给桌面腾点空间。","宜问候一位老友。")[value%4]



def poll_guide(db,event,manager,prefix):
    poll=db.execute("SELECT id,title,deadline FROM polls WHERE grp=? ORDER BY id DESC LIMIT 1",(event["grp"],)).fetchone()
    if not poll:
        if manager:
            return f"本群暂无投票。发送即创建午餐投票\n{prefix}投票 创建 午餐|饭|面"
        return f"本群暂无投票，可请群管理员发起。查看其他功能\n{prefix}菜单"
    code=f"V{poll['id']:02}"
    lines=[f"🗳 最近的投票 · {poll['title']}","免费查看选项和票数",f"{prefix}投票 {code}"]
    if poll["deadline"]>event["arrived"]:
        lines.extend(["投给第 1 项，发送即计票",f"{prefix}投票 {code} 1"])
    return "\n".join(lines)
