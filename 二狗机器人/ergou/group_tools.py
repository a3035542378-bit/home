"""Group-scoped operations, message statistics and point redemptions."""
import json
import time
from datetime import datetime, timedelta

from . import admin
from .db import BJ, audit, transaction


SCHEMA = """
CREATE TABLE IF NOT EXISTS group_profile (
 grp TEXT PRIMARY KEY REFERENCES groups, alias TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 0,
 detached INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reward_offers (
 grp TEXT NOT NULL REFERENCES groups, name TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>0),
 PRIMARY KEY(grp,name)
);
CREATE TABLE IF NOT EXISTS redemptions (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, name TEXT NOT NULL,
 price INTEGER NOT NULL, seq INTEGER NOT NULL UNIQUE REFERENCES inbox, ledger_id INTEGER NOT NULL UNIQUE REFERENCES ledger,
 created REAL NOT NULL, fulfilled REAL, operator TEXT
);
CREATE INDEX IF NOT EXISTS redemptions_by_group ON redemptions(grp,fulfilled,id);
"""


def aliases(db, groups):
    authorized=set(groups)
    return {r["grp"]:r["alias"] for r in db.execute("SELECT grp,alias FROM group_profile WHERE alias<>''")
            if r["grp"] in authorized}


def _analytics(db, group, now):
    midnight=datetime.fromtimestamp(now,BJ).replace(hour=0,minute=0,second=0,microsecond=0)
    start=midnight-timedelta(days=6)
    counts={r[0]:r for r in db.execute("""SELECT date(arrived,'unixepoch','+8 hours') day,
                COUNT(*) received, SUM(state NOT IN ('PENDING','FAILED')) processed, COUNT(DISTINCT member) users
                FROM inbox WHERE grp=? AND kind='message' AND arrived BETWEEN ? AND ? GROUP BY day""",
                (group,start.timestamp(),now))}
    daily=[]
    for index in range(7):
        day=(start+timedelta(days=index)).date().isoformat()
        _,received,processed,users=counts.get(day,(day,0,0,0))
        daily.append(dict(day=day,received=received,processed=processed,users=users))
    keywords=[dict(r) for r in db.execute("""SELECT h.keyword,COUNT(*) hits FROM inbox i
             JOIN reply_rule_hits h ON h.seq=i.seq WHERE i.grp=? AND i.arrived BETWEEN ? AND ?
             GROUP BY h.keyword ORDER BY hits DESC,h.keyword LIMIT 10""",(group,midnight.timestamp(),now))]
    failures=[dict(r) for r in db.execute("""SELECT * FROM (
        SELECT arrived at,seq id,'入站处理' kind,COALESCE(result,state) detail FROM inbox WHERE grp=? AND state='FAILED'
        UNION ALL SELECT i.arrived,i.seq,'模型请求',c.state FROM chat_requests c JOIN inbox i USING(seq)
            WHERE i.grp=? AND c.state IN ('FAILED','EXPIRED') AND NOT EXISTS
              (SELECT 1 FROM service_failures f WHERE f.seq=i.seq AND f.kind='模型请求')
        UNION ALL SELECT i.arrived,i.seq,q.kind,q.state FROM queries q JOIN inbox i ON i.seq=q.id
            WHERE i.grp=? AND q.state IN ('FAILED','EXPIRED') AND NOT EXISTS
              (SELECT 1 FROM service_failures f WHERE f.seq=i.seq AND f.kind=q.kind)
        UNION ALL SELECT at,COALESCE(seq,id),kind,reason FROM service_failures WHERE grp=?
        UNION ALL SELECT created,id,'发送回复',COALESCE(detail,state) FROM outbox
            WHERE grp=? AND state IN ('FAILED','UNKNOWN')
        ) ORDER BY at DESC,id DESC LIMIT 40""",(group,)*5)]
    return daily,keywords,failures


def settings(db, user, group):
    admin.permitted(user,group)
    row=db.execute("""SELECT COALESCE(p.alias,'') alias,COALESCE(p.version,0) version,
            COALESCE(p.detached,0) detached,g.binding FROM groups g LEFT JOIN group_profile p ON p.grp=g.id
            WHERE g.id=?""",(group,)).fetchone()
    if not row:
        raise ValueError("群不存在")
    daily,keywords,errors=_analytics(db,group,time.time())
    offers=[dict(r) for r in db.execute("SELECT name,price FROM reward_offers WHERE grp=? ORDER BY price,name",(group,))]
    # Pending orders are always addressable, including those beyond the recent history window.
    orders=[dict(r) for r in db.execute("""SELECT r.id,r.member,r.name,r.price,r.created,r.fulfilled,
               EXISTS(SELECT 1 FROM ledger WHERE grp=r.grp AND kind='冲正' AND event='reverse/'||r.ledger_id) refunded
               FROM redemptions r WHERE r.grp=? ORDER BY (fulfilled IS NULL AND refunded=0) DESC,
               CASE WHEN fulfilled IS NULL AND refunded=0 THEN r.id END,r.id DESC LIMIT 100""",(group,))]
    return dict(row,group=group,offers=offers,orders=orders,daily=daily,keywords=keywords,errors=errors)


def _text(value,label,maxlen):
    if not isinstance(value,str) or len(value)>maxlen or any(ord(c)<32 for c in value):
        raise ValueError(label+"格式无效")
    return value.strip()


def _detach(db,group,binding):
    if db.execute("SELECT 1 FROM outbox WHERE grp=? AND state IN ('SENDING','UNKNOWN')",(group,)).fetchone():
        raise ValueError("CONFLICT 请先核对本群在途或结果未知的发送，再解绑")
    db.execute("UPDATE groups SET paused=1,binding=binding+1 WHERE id=? AND binding=?",(group,binding))
    db.execute("UPDATE group_profile SET detached=1 WHERE grp=?",(group,))
    for table in ("node_grants","membership","agent_wechat_links","directed_groups","welcomes"):
        db.execute(f"DELETE FROM {table} WHERE grp=?",(group,))
    db.execute("UPDATE outbox SET state='CANCELLED',body='' WHERE grp=? AND state IN ('PENDING','RETRY_WAIT')",(group,))
    db.execute("UPDATE schedules SET enabled=0,version=version+1 WHERE grp=? AND enabled=1",(group,))
    db.execute("""UPDATE games SET state='ABORTED',ended=?,reason='群已解绑' WHERE grp=?
                  AND state IN ('RUNNING','PAUSED','WAITING_PLAYERS')""",(time.time(),group))
    db.execute("""UPDATE inbox SET state='IGNORED',result='群已解绑',payload=NULL WHERE grp=? AND state='PENDING'""",(group,))
    db.execute("""UPDATE queries SET state='CANCELLED',argument=NULL WHERE id IN
                  (SELECT seq FROM inbox WHERE grp=?) AND state IN ('PENDING','RUNNING')""",(group,))
    db.execute("""UPDATE chat_requests SET state='CANCELLED',prompt=NULL WHERE seq IN
                  (SELECT seq FROM inbox WHERE grp=?) AND state IN ('PENDING','RUNNING')""",(group,))


def configure(db,user,group,data):
    admin.permitted(user,group,True)
    if user["role"] not in ("系统管理员","运营管理员"):
        raise PermissionError("FORBIDDEN 此操作需要运营管理员权限")
    action=data.get("action")
    with transaction(db):
        group_row=db.execute("SELECT binding FROM groups WHERE id=?",(group,)).fetchone()
        if not group_row:
            raise ValueError("群不存在")
        db.execute("INSERT OR IGNORE INTO group_profile(grp) VALUES(?)",(group,))
        profile=db.execute("SELECT version,detached FROM group_profile WHERE grp=?",(group,)).fetchone()
        if type(data.get("version")) is not int or profile["version"]!=data["version"]:
            raise ValueError("CONFLICT 群运营配置已变更，请刷新后重试")
        if action=="alias":
            alias=_text(data.get("alias"),"群昵称",50)
            db.execute("UPDATE group_profile SET alias=? WHERE grp=?",(alias,group))
            detail="编辑群昵称"
        elif action=="detach":
            if data.get("confirm")!=group or data.get("binding")!=group_row["binding"]:
                raise ValueError("请确认目标群和当前绑定版本")
            if profile["detached"]:
                raise ValueError("此群已解绑")
            _detach(db,group,group_row["binding"])
            detail="解绑群"
        elif action in ("offer","removeOffer"):
            name=_text(data.get("name"),"奖励名称",40)
            if not name:
                raise ValueError("奖励名称不能为空")
            if action=="offer":
                price=data.get("price")
                if type(price) is not int or not 1<=price<=1000000:
                    raise ValueError("兑换积分须为 1 至 1000000 的整数")
                count=db.execute("SELECT COUNT(*) FROM reward_offers WHERE grp=? AND name<>?",(group,name)).fetchone()[0]
                if count>=40:
                    raise ValueError("每群最多设置 40 项可兑换奖励")
                db.execute("INSERT OR REPLACE INTO reward_offers VALUES(?,?,?)",(group,name,price))
            else:
                db.execute("DELETE FROM reward_offers WHERE grp=? AND name=?",(group,name))
            detail="设置兑换规则" if action=="offer" else "下架兑换规则"
        elif action=="fulfill":
            order=data.get("id")
            if type(order) is not int or not db.execute("""UPDATE redemptions SET fulfilled=?,operator=?
                    WHERE id=? AND grp=? AND fulfilled IS NULL AND NOT EXISTS (SELECT 1 FROM ledger WHERE grp=?
                    AND kind='冲正' AND event='reverse/'||redemptions.ledger_id)""",
                    (time.time(),user["name"],order,group,group)).rowcount:
                raise ValueError("CONFLICT 订单不在本群、已核销或积分已冲正")
            detail="核销兑换单 #"+str(order)
        else:
            raise ValueError("群运营操作无效")
        db.execute("UPDATE group_profile SET version=version+1 WHERE grp=?",(group,))
        audit(db,user["name"],group,detail,"群运营工作台")
    return settings(db,user,group)


CHECKIN_POINTS = 3


def check_in(db, event, cfg, prefix):
    from . import fishing_bait
    from .display_names import mention_sender
    key = (event["grp"], event["member"])
    # 一条不可变流水同时是签到凭据和奖励；唯一索引裁决同日竞争。
    credited = db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                             VALUES(?,?,0,'签到',?,'checkin/1',?,?,'每日签到')
                             ON CONFLICT DO NOTHING RETURNING id""",
                          (*key,CHECKIN_POINTS,event["event_id"],event["arrived"])).fetchone()
    points = fishing_bait.balance(db,key)
    if credited is None:
        mention_sender(db,event)
        return f"今天已经签过啦，本群积分 {points} 分。"
    receipt = f"✅ 签到到账 +{CHECKIN_POINTS} 积分，本群余额 {points} 分。"
    if cfg["games"] and "钓鱼" not in cfg.get("disabled_games",[]):
        cost = fishing_bait.BAITS["高级鱼饵"].points
        if points < cost:
            return f"{receipt}\n离高级鱼饵还差 {cost-points} 分。"
        return f"{receipt}\n够用一次高级鱼饵啦，查看用法\n{prefix}鱼饵"
    if db.execute("SELECT 1 FROM reward_offers WHERE grp=? LIMIT 1",(key[0],)).fetchone():
        return f"{receipt}\n查看本群兑换奖励\n{prefix}兑换列表"
    return f"{receipt}\n查看本群积分\n{prefix}积分"


def redeem(db,event,arg,prefix="二狗"):
    """Runs inside the inbox transaction together with the reply and ledger debit."""
    group,member=event["grp"],event["member"]
    name=arg.strip()
    balance=db.execute("SELECT COALESCE(SUM(points),0) FROM ledger WHERE grp=? AND member=?",(group,member)).fetchone()[0]
    if not name:
        available=db.execute("SELECT name,price FROM reward_offers WHERE grp=? ORDER BY price,name",(group,)).fetchall()
        if not available:
            return f"本群暂未上架兑换奖励。先查自己的积分\n{prefix}积分"
        lines = [f"{r['name']}　{r['price']} 分" for r in available]
        cheapest = available[0]
        if cheapest["price"] > balance:
            next_step = f"还差 {cheapest['price']-balance} 分可兑最便宜的一项。查积分\n{prefix}积分"
        else:
            next_step = f"发送即扣 {cheapest['price']} 分，兑换「{cheapest['name']}」\n{prefix}兑换 {cheapest['name']}"
        return "\n".join([f"🎁 本群可兑换 · 余额 {balance} 分", *lines, next_step])
    existing=db.execute("SELECT * FROM redemptions WHERE seq=?",(event["seq"],)).fetchone()
    if existing:
        return f"兑换单 #{existing['id']} · {existing['name']} · {existing['price']} 分"
    offer=db.execute("SELECT price FROM reward_offers WHERE grp=? AND name=?",(group,name)).fetchone()
    if not offer:
        raise ValueError(f"本群没有这项奖励。查看可兑换的奖励：\n{prefix}兑换列表")
    price=offer[0]
    if balance<price:
        cheaper=db.execute("SELECT 1 FROM reward_offers WHERE grp=? AND price<=? LIMIT 1",(group,balance)).fetchone()
        if cheaper:
            step=f"{prefix}兑换列表\n另有积分足够的奖励。"
        else:
            cfg=json.loads(db.execute("SELECT config FROM groups WHERE id=?",(group,)).fetchone()[0])
            step=(f"{prefix}游戏列表\n想攒积分，可以看看本群游戏。" if cfg["games"] and cfg["reward"]>0
                  else f"{prefix}积分")
        raise ValueError(f"🎁 「{name}」还差 {price-balance} 分，未扣积分。\n{step}\n需要 {price} 分，你在本群有 {balance} 分。")
    debit=db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                VALUES(?,?,0,'兑换',?,'redeem/1',?,?,?)""",(group,member,-price,event["event_id"],event["arrived"],name)).lastrowid
    order=db.execute("INSERT INTO redemptions(grp,member,name,price,seq,ledger_id,created) VALUES(?,?,?,?,?,?,?)",
                     (group,member,name,price,event["seq"],debit,event["arrived"])).lastrowid
    return f"🎁 兑换成功 · {name}\n已扣 {price} 分，剩余 {balance-price} 分。\n把兑换单 #{order} 发给群运营领取。"
