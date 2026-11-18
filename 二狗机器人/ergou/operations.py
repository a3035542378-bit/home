"""Scoped administrative mutations. Successful retries return the original outcome."""
import time
from .db import audit,dump,transaction
from .admin import permitted


def act(db,u,g,d):
    permitted(u,g,True)
    op=d.get("action")
    key=d.get("key")
    reason=d.get("reason")
    if not isinstance(key,str) or not 1<=len(key)<=120 or not isinstance(reason,str) or not 1<=len(reason.strip())<=200:
        raise ValueError("操作需要幂等键与原因")
    signature=dump([u["name"],op,reason,d.get("target"),d.get("points"),d.get("resolution")])
    with transaction(db):
        old=db.execute("SELECT * FROM operations WHERE grp=? AND key=?",(g,key)).fetchone()
        if old:
            if old["signature"]!=signature:raise ValueError("CONFLICT 幂等键已用于其他操作")
            return old["result"]
        if op in ("调分","冲正"):
            target=d["target"]
            delta=d.get("points")
            if op=="冲正":
                row=db.execute("SELECT * FROM ledger WHERE id=? AND grp=?",(target,g)).fetchone()
                if not row or row["kind"]=="冲正" or db.execute("SELECT 1 FROM ledger WHERE grp=? AND kind='冲正' AND event=?",(g,"reverse/"+str(target))).fetchone():
                    raise ValueError("原流水不存在或已冲正")
                member,delta,event=row["member"],-row["points"],"reverse/"+str(target)
            else:
                member,event=target,key
            if not isinstance(member,str) or not 1<=len(member)<=160 or type(delta) is not int or not 0<abs(delta)<=1000:
                raise ValueError("成员或调整分值无效")
            cur=db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                           VALUES(?,?,0,?,?,'manual/1',?,?,?)""",(g,member,op,delta,event,time.time(),reason))
            result="流水 #"+str(cur.lastrowid)
        elif op=="核对发送":
            state={"确认送达":"ACKNOWLEDGED","结束跟进":"CANCELLED"}.get(d.get("resolution"))
            if state is None:raise ValueError("核对结果无效")
            changed=db.execute("UPDATE outbox SET state=?,detail='管理员核对' WHERE id=? AND grp=? AND state='UNKNOWN'",(state,d["target"],g)).rowcount
            if not changed:raise ValueError("CONFLICT 任务状态不适用")
            result=state
        elif op=="停用通知":
            changed=db.execute("UPDATE schedules SET enabled=0,version=version+1 WHERE id=? AND grp=?",(d["target"],g)).rowcount
            if not changed:raise ValueError("通知不存在")
            db.execute("UPDATE outbox SET state='CANCELLED' WHERE grp=? AND biz LIKE ? AND state IN ('PENDING','RETRY_WAIT')",(g,f"schedule/{int(d['target'])}/%"))
            result="通知已停用"
        elif op=="重试入站":
            changed=db.execute("UPDATE inbox SET state='PENDING',retries=0 WHERE seq=? AND grp=? AND state='FAILED' AND payload IS NOT NULL AND arrived>?",(d["target"],g,time.time()-120)).rowcount
            if not changed:raise ValueError("事件已过期或状态不适用")
            result="已重新入队"
        else:
            raise ValueError("未知管理操作")
        db.execute("INSERT INTO operations VALUES(?,?,?,?)",(key,g,signature,result))
        audit(db,u["name"],g,op,reason)
        return result

