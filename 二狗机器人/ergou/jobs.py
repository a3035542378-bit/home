import json
import random
import time
from datetime import datetime
from .db import BJ, allowed, audit, transaction
from .engine import ACTIVE, expire, queue


def claim(db, account, now=None, *, directed_group=None):
    from .native_voice import VERSION as voice_version
    now=time.time() if now is None else now
    with transaction(db):
        if directed_group is not None:
            db.execute("""UPDATE outbox SET state='CANCELLED',detail='本群成员通知授权已变化',body=''
                       WHERE grp=? AND account=? AND state IN ('PENDING','RETRY_WAIT')
                       AND id IN (SELECT task FROM native_member_deliveries)
                       AND id NOT IN (SELECT id FROM valid_member_deliveries)""",(directed_group,account))
        db.execute("UPDATE attempts SET ended=?,result='UNKNOWN' WHERE ended IS NULL AND task IN (SELECT id FROM outbox WHERE state='SENDING' AND lease<=?)",(now,now))
        db.execute("UPDATE outbox SET state='UNKNOWN',detail='发送租约到期' WHERE state='SENDING' AND lease<=?",(now,))
        db.execute("UPDATE outbox SET state='EXPIRED',body='' WHERE state IN ('PENDING','RETRY_WAIT') AND expires<=?",(now,))
        row=db.execute("""SELECT o.*,g.account active,g.binding current,g.paused,g.config,vi.seq voice_seq FROM outbox o
          JOIN groups g ON g.id=o.grp JOIN account a ON a.id=o.account
          LEFT JOIN inbox vi ON vi.event_id=o.biz AND vi.message_type='voice' AND vi.adapter_version=?
          WHERE o.account=? AND o.state IN ('RETRY_WAIT','PENDING') AND o.ready<=?
          AND ((? IS NULL AND a.state='ONLINE' AND vi.seq IS NULL) OR
               (o.grp=? AND a.state='LISTENING' AND EXISTS (SELECT 1 FROM nodes n WHERE n.account=o.account AND n.last_seen>?)
               AND ((vi.seq IS NOT NULL AND EXISTS (
                 SELECT 1 FROM valid_voice_events v WHERE v.seq=vi.seq AND v.state='AWAKE' AND v.source_time>?
                 AND v.source=vi.source AND v.member=vi.member AND v.grp=vi.grp AND v.account=vi.account
                 AND v.binding=vi.binding AND v.grp=o.grp AND v.account=o.account AND v.binding=o.binding))
                 OR (vi.seq IS NULL AND (EXISTS (
                 SELECT 1 FROM directed_events d JOIN inbox i ON i.event_id=d.biz
                 JOIN directed_groups p ON p.grp=i.grp AND p.account=i.account AND p.binding=i.binding
                 WHERE d.biz=o.biz AND i.grp=o.grp AND i.account=o.account AND i.binding=o.binding
                 AND d.source_time>=p.since AND d.source_time>?) OR EXISTS (
                 SELECT 1 FROM valid_live_notices v WHERE v.biz=o.biz AND v.grp=o.grp AND v.account=o.account
                 AND v.binding=o.binding AND v.body=o.body AND v.due<=?)
                 OR EXISTS(SELECT 1 FROM valid_member_deliveries m WHERE m.id=o.id))))))
          AND g.paused=0 ORDER BY o.ready,o.id LIMIT 1""",
          (voice_version,account,now,directed_group,directed_group,now-30,now-120,now-120,now)).fetchone()
        if not row:
            return False
        member=db.execute("SELECT 1 FROM membership WHERE account=? AND grp=?",(account,row["grp"])).fetchone()
        if not member or row["active"]!=row["account"] or row["current"]!=row["binding"] or not json.loads(row["config"])["enabled"]:
            db.execute("UPDATE outbox SET state='CANCELLED',detail='绑定或权限已变更' WHERE id=?",(row["id"],))
            return True
        if row["voice_seq"] is not None:
            from .voice_policy import active
            if active(db,row["grp"],account,row["binding"]) is None:
                db.execute("UPDATE outbox SET state='CANCELLED',body='',detail='本群语音授权或凭据已变化' WHERE id=?",(row["id"],))
                return True
        policy=db.execute("SELECT per_second FROM account_policy WHERE account=?",(account,)).fetchone()
        if not allowed(db,"send/grp/"+row["grp"],json.loads(row["config"]).get("send_rate",5),1,now) or not allowed(db,"send/acc/"+account,policy[0] if policy else 10,1,now):
            db.execute("UPDATE outbox SET ready=? WHERE id=?",(now+1,row["id"]))
            return True
        attempt=row["attempts"]+1
        lease=now+(120 if row["voice_seq"] is not None else 30)
        db.execute("UPDATE outbox SET state='SENDING',attempts=?,lease=? WHERE id=?",(attempt,lease,row["id"]))
        db.execute("INSERT INTO attempts VALUES(?,?,?,NULL,NULL)",(row["id"],attempt,now))
    return dict(row,attempt=attempt,lease=lease)


def send_one(db, adapter, now=None):
    """Adapter is bound to one specific account. Any uncertain call stays UNKNOWN."""
    row=claim(db,adapter.account,now)
    if not isinstance(row,dict):
        return row
    try:
        state,detail=adapter.send(row)
    except Exception:
        state,detail="UNKNOWN","调用结果不明"
    finish(db,adapter.account,row["id"],row["attempt"],state,detail,now)
    return True


def finish(db,account,task,attempt,state,detail,now=None):
    now=time.time() if now is None else now
    if state not in ("ACKNOWLEDGED","RETRY_WAIT","FAILED","UNKNOWN"):
        state,detail="UNKNOWN","未识别的适配器状态"
    if state=="RETRY_WAIT" and attempt>=4:
        state,detail="FAILED","明确未发送；重试次数已用尽"
    finished=time.time()
    with transaction(db):
        changed=db.execute("""UPDATE outbox SET state=?,detail=?,ready=?,lease=NULL,ack_at=? WHERE id=? AND account=? AND state='SENDING' AND attempts=?""",
                   (state,detail,now+2**min(attempt,4)+random.random(),finished if state=="ACKNOWLEDGED" else None,task,account,attempt)).rowcount
        if changed:
            db.execute("UPDATE attempts SET ended=?,result=? WHERE task=? AND n=? AND ended IS NULL",(finished,state,task,attempt))
        return bool(changed)


class Simulation:
    account="sim-account"

    def send(self,row):
        return "ACKNOWLEDGED","模拟适配器确认"


def switch(db,group,target,actor,key=None):
    with transaction(db):
        import json
        signature=json.dumps(["switch",target,actor])
        if key:
            old=db.execute("SELECT signature,result FROM operations WHERE grp=? AND key=?",(group,key)).fetchone()
            if old:
                if old["signature"]!=signature:raise ValueError("CONFLICT 操作键已使用")
                return old["result"]
        row=db.execute("SELECT * FROM groups WHERE id=?",(group,)).fetchone()
        if not row:
            raise ValueError("群不存在")
        if not db.execute("SELECT 1 FROM account a JOIN membership m ON a.id=m.account WHERE a.id=? AND m.grp=? AND a.state='ONLINE'",(target,group)).fetchone():
            raise ValueError("ACCOUNT_OFFLINE 目标账号不在线或未加入此群")
        if row["account"]==target and not row["paused"]:
            return "已是当前绑定"
        db.execute("UPDATE groups SET paused=1 WHERE id=?",(group,))
        if db.execute("SELECT 1 FROM outbox WHERE grp=? AND binding=? AND state IN ('SENDING','UNKNOWN')",(group,row["binding"])).fetchone():
            audit(db,actor,group,"暂停切换","等待核对在途或未知发送")
            return "暂停中，需核对在途或未知发送"
        db.execute("UPDATE outbox SET state='CANCELLED' WHERE grp=? AND state IN ('PENDING','RETRY_WAIT')",(group,))
        db.execute(f"UPDATE games SET state='ABORTED',ended=?,reason='绑定切换，原局中止' WHERE grp=? AND state IN {ACTIVE}",(time.time(),group))
        db.execute("UPDATE groups SET binding=binding+1,account=?,paused=0 WHERE id=?",(target,group))
        audit(db,actor,group,"切换账号",target)
        if key:db.execute("INSERT INTO operations VALUES(?,?,?,?)",(key,group,signature,"已切换"))
        return "已切换"


def tick(db,now=None):
    now=time.time() if now is None else now
    with transaction(db):
        for batch in db.execute("SELECT grp,due,account,binding FROM welcomes WHERE due<=? GROUP BY grp,due,account,binding LIMIT 50",(now,)).fetchall():
            args=tuple(batch)
            people=[r[0] for r in db.execute("SELECT name FROM welcomes WHERE grp=? AND due=? AND account=? AND binding=? ORDER BY member",args)]
            g=db.execute("SELECT * FROM groups WHERE id=?",(batch["grp"],)).fetchone()
            cfg=json.loads(g["config"])
            from .member_policy import active
            if (now-batch["due"]<120 and g["account"]==batch["account"] and g["binding"]==batch["binding"]
                    and not g["paused"] and cfg["enabled"] and "join" in active(db,g["id"],g["account"],g["binding"])):
                names="、".join(people[:12])+("等 "+str(len(people))+" 位成员" if len(people)>12 else "")
                from .greetings import welcome
                body=welcome(cfg,names,g["id"],now)
                queue(db,g,"welcome/"+str(args),body,batch["due"])
            db.execute("DELETE FROM welcomes WHERE grp=? AND due=? AND account=? AND binding=?",args)
        db.execute("UPDATE account SET state='RECONNECTING' WHERE state IN ('ONLINE','LISTENING') AND id IN (SELECT account FROM nodes WHERE last_seen<?)",(now-30,))
        db.execute("UPDATE account SET state='NEED_USER_ACTION' WHERE state='RECONNECTING' AND id IN (SELECT account FROM nodes WHERE last_seen<?)",(now-300,))
        db.execute("""UPDATE games SET state='EXPIRED',ended=deadline,reason='到时结束' WHERE state='RUNNING'
            AND deadline<=? AND NOT EXISTS (SELECT 1 FROM inbox i WHERE i.grp=games.grp AND i.state='PENDING' AND i.arrived<games.deadline)""",(now,))
        for s in db.execute("SELECT * FROM schedules WHERE enabled=1 AND due<=? ORDER BY due LIMIT 100",(now,)).fetchall():
            group=db.execute("SELECT * FROM groups WHERE id=?",(s["grp"],)).fetchone()
            cfg=json.loads(group["config"])
            interval={"每日":86400,"每周":604800,"一次":0}[s["period"]]
            first=s["due"]
            due=first + ((int((now-first)//interval)*interval) if interval else 0)
            if s["until"] is not None and due>s["until"]:
                db.execute("UPDATE schedules SET enabled=0 WHERE id=?",(s["id"],))
                continue
            limit=600 if s["catchup"] else 2
            h=datetime.fromtimestamp(now,BJ).hour
            a,b=cfg["quiet_start"],cfg["quiet_end"]
            quiet=(a<=h<b if a<=b else h>=a or h<b)
            send=not quiet and cfg["enabled"] and not group["paused"] and now-due<limit
            if send and db.execute("SELECT 1 FROM listener_nodes WHERE account=?",(group["account"],)).fetchone():
                from .live_notice import matches
                send=matches(db,s["grp"],f"schedule/{s['id']}/{due}",s["body"])
            if first!=due:
                db.execute("INSERT OR IGNORE INTO runs VALUES(?,?,'SKIPPED_RANGE')",(s["id"],first))
            result="QUEUED" if send else "SKIPPED"
            added=db.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?)",(s["id"],due,result)).rowcount
            if send and added:
                from . import bulletins
                if not bulletins.stage(db,s,group,due,now):
                    queue(db,group,f"schedule/{s['id']}/{due}",s["body"],now,max(1,min(120,due+limit-now)))
            future=bool(interval) and (s["until"] is None or due+interval<=s["until"])
            db.execute("UPDATE schedules SET enabled=?,due=? WHERE id=?",(future,due+interval,s["id"]))


def cleanup(db,now):
    from .retention import CACHE
    from .monitor import sample_alerts
    CACHE.purge(now)
    with transaction(db):
        sample_alerts(db,now)
        db.execute("DELETE FROM tokens WHERE expires<=?",(now,))
        db.execute("DELETE FROM voice_test_tickets WHERE expires<=?",(now,))
        db.execute("DELETE FROM weather_cache WHERE at<?",(now-600,))
        db.execute("""UPDATE native_voice_events SET state='EXPIRED' WHERE source_time<=?
                   AND state IN ('PENDING','PROCESSING')""",(now-120,))
        db.execute("DELETE FROM native_voice_events WHERE source_time<=?",(now-86400,))
        db.execute("""DELETE FROM local_turns WHERE NOT EXISTS (SELECT 1 FROM local_turns recent
                    WHERE recent.grp=local_turns.grp AND recent.member=local_turns.member AND recent.at>?)""",(now-1800,))
        db.execute("DELETE FROM throttles WHERE start<?",(now-86400*2,))
        db.execute("UPDATE outbox SET body='' WHERE created<? AND state NOT IN ('PENDING','RETRY_WAIT','SENDING')",(now-86400,))
        db.execute("""DELETE FROM simulation_reply_images WHERE seq IN
                    (SELECT i.seq FROM inbox i JOIN outbox o ON o.biz=i.event_id
                     WHERE o.created<? AND o.state NOT IN ('PENDING','RETRY_WAIT','SENDING'))""",(now-86400,))
        db.execute("DELETE FROM audit WHERE at<?",(now-365*86400,))
        db.execute("""INSERT OR IGNORE INTO observation SELECT g.id,? FROM groups g JOIN account a ON a.id=g.account
                   JOIN membership m ON m.account=g.account AND m.grp=g.id WHERE a.state IN ('ONLINE','LISTENING') AND g.paused=0 AND json_extract(g.config,'$.enabled')""",(int(now//60),))
        db.execute("DELETE FROM observation WHERE minute<?",(int(now//60)-90*1440,))
        from . import reports
        from .db import dump,window
        monday=window("周榜",now)
        if now>=monday+9*3600:
            prior=monday-7*86400
            rows=db.execute("SELECT id FROM groups WHERE id NOT IN (SELECT grp FROM weekly WHERE start=?) LIMIT 20",(prior,)).fetchall()
            for row in rows:
                report=[reports.weekly(db,row[0],monday)]
                db.execute("INSERT OR IGNORE INTO weekly VALUES(?,?,?)",(row[0],prior,dump(report)))
                g=db.execute("SELECT * FROM groups WHERE id=?",(row[0],)).fetchone()
                cfg=json.loads(g["config"])
                if cfg.get("weekly_push") and cfg["enabled"] and not g["paused"] and now<monday+9*3600+600:
                    queue(db,g,f"weekly/{row[0]}/{prior}","上周群报 · "+" · ".join(f"{k} {v}" for k,v in report[0].items()),now)

