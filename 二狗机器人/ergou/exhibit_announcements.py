"""图鉴日榜只投递结算事务生成并登记的那一条消息。"""
from datetime import datetime, time, timedelta
import hashlib

from .db import BJ
from .display_names import labels


def enqueue(db, group, period, now):
    target = db.execute("""SELECT account,binding FROM groups
        WHERE id=? AND json_extract(config,'$.exhibit_board_push')""",(group,)).fetchone()
    if not target:
        return
    rows = db.execute("""SELECT member,points FROM ledger WHERE grp=? AND kind='图鉴日榜'
        AND event=? ORDER BY id LIMIT 10""",(group,period)).fetchall()
    name = labels(db,group)
    lines = [f"🏆 {period} 图鉴榜结算（北京时间）"]
    for seat, row in enumerate(rows,1):
        tag = hashlib.sha256((group+"\0"+row["member"]).encode()).hexdigest()[:6]
        lines.append(f"第 {seat} 名　{name(row['member'],'钓友·'+tag)}　+{row['points']} 积分")
    lines.append(f"共到账 {sum(row['points'] for row in rows)} 积分。" if rows else "本期无人上榜，未发放积分。")
    body = "\n".join(lines)
    expires = datetime.combine(datetime.fromtimestamp(now,BJ).date()+timedelta(days=1),time.min,BJ).timestamp()
    task = db.execute("""INSERT INTO outbox(biz,account,grp,binding,body,state,created,expires,ready)
        VALUES(?,?,?,?,?,'PENDING',?,?,?) ON CONFLICT(biz) DO NOTHING RETURNING id""",
        (f"exhibit-board/{period}/{group}",target["account"],group,target["binding"],body,now,expires,now)).fetchone()
    if task:
        db.execute("INSERT INTO exhibit_board_notices(task,digest) VALUES(?,?)",
                   (task[0],hashlib.sha256(body.encode()).hexdigest()))


def matches(db,task):
    row=db.execute("""SELECT digest FROM valid_exhibit_board_notices
        WHERE id=? AND biz=? AND grp=? AND account=? AND binding=?""",
        (task["id"],task["biz"],task["grp"],task["account"],task["binding"])).fetchone()
    return bool(row and row[0]==hashlib.sha256(task["body"].encode()).hexdigest())


def revoke(db,group):
    db.execute("""UPDATE exhibit_board_notices SET revoked=1 WHERE task IN
        (SELECT id FROM outbox WHERE grp=? AND state IN ('PENDING','RETRY_WAIT','SENDING'))""",(group,))
    db.execute("""UPDATE outbox SET state='CANCELLED',body='',detail='已关闭本群图鉴榜公告'
        WHERE grp=? AND state IN ('PENDING','RETRY_WAIT') AND id IN (SELECT task FROM exhibit_board_notices)""",(group,))
