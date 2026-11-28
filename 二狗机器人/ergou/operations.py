"""Scoped administrative mutations. Successful retries return the original outcome."""
import time
from .db import audit,dump,transaction
from .admin import permitted
from .asset_roster import require_member


def grant_currency(db,group,data,key,reason):
    member=data.get("target")
    amount=data.get("points")
    currency=data.get("currency")
    limit=2**53-1
    if currency not in ("积分","鱼币"):
        raise ValueError("仅可发放积分或鱼币，水晶预留给支付购买")
    if not isinstance(member,str) or not member.isprintable() or not 1<=len(member)<=160 or member.strip()!=member:
        raise ValueError("请填写有效成员 ID")
    if type(amount) is not int or not 1<=amount<=limit:
        raise ValueError("发放数量必须为有效正整数")
    require_member(db,group,member)
    if currency=="鱼币":
        db.execute("INSERT OR IGNORE INTO fishing_wallets(grp,member) VALUES(?,?)",(group,member))
        balance=db.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",(group,member)).fetchone()[0]
    else:
        balance=db.execute("SELECT COALESCE(SUM(points),0) FROM ledger WHERE grp=? AND member=?",(group,member)).fetchone()[0]
    if balance+amount>limit:
        raise ValueError("余额超出支持范围")
    if currency=="鱼币":
        db.execute("UPDATE fishing_wallets SET coins=coins+? WHERE grp=? AND member=?",(amount,group,member))
    else:
        db.execute("""INSERT INTO ledger(grp,member,round,kind,points,rule_version,event,at,reason)
                      VALUES(?,?,0,'发放货币',?,'grant/1',?,?,?)""",(group,member,amount,key,time.time(),reason))
    return f"已向 {member} 发放 {amount} {currency}，余额 {balance+amount}"


def act(db,u,g,d):
    permitted(u,g,True)
    op=d.get("action")
    key=d.get("key")
    reason=d.get("reason")
    if not isinstance(key,str) or not 1<=len(key)<=120 or not isinstance(reason,str) or not 1<=len(reason.strip())<=200:
        raise ValueError("操作需要幂等键与原因")
    fields=[u["name"],op,reason,d.get("target"),d.get("points"),d.get("resolution")]
    if op=="发放货币":
        fields.append(d.get("currency"))
    signature=dump(fields)
    with transaction(db):
        old=db.execute("SELECT * FROM operations WHERE grp=? AND key=?",(g,key)).fetchone()
        if old:
            if old["signature"]!=signature:raise ValueError("CONFLICT 幂等键已用于其他操作")
            return old["result"]
        if op=="发放货币":
            result=grant_currency(db,g,d,key,reason)
        elif op in ("调分","冲正","撤销误冲正"):
            target=d["target"]
            if op!="调分":
                if not str(target).isascii() or not str(target).isdigit():
                    raise ValueError("需要本群原流水编号")
                target=int(target)
            delta=d.get("points")
            if u["role"]!="系统管理员":
                raise PermissionError("历史纠错需要系统管理员权限")
            if op=="撤销误冲正":
                row=db.execute("""SELECT r.member,r.points FROM ledger r JOIN ledger original
                    ON original.grp=r.grp AND original.member=r.member AND r.event='reverse/'||original.id
                    WHERE r.grp=? AND r.id=? AND r.kind='冲正' AND r.points=-original.points
                    AND original.points>0""",(g,target)).fetchone()
                event="restore/"+str(target)
                if not row or db.execute("SELECT 1 FROM ledger WHERE grp=? AND kind=? AND event=?",(g,op,event)).fetchone():
                    raise ValueError("原冲正不存在或已经补回")
                member,delta=row["member"],-row["points"]
            elif op=="冲正":
                row=db.execute("SELECT * FROM ledger WHERE id=? AND grp=?",(target,g)).fetchone()
                if not row or row["kind"] in ("冲正","撤销误冲正") or db.execute("SELECT 1 FROM ledger WHERE grp=? AND kind='冲正' AND event=?",(g,"reverse/"+str(target))).fetchone():
                    raise ValueError("原流水不存在或已冲正")
                member,delta,event=row["member"],-row["points"],"reverse/"+str(target)
            else:
                require_member(db,g,target)
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
            from .engine import reserve_requeued
            reserve_requeued(db, db.execute("SELECT * FROM inbox WHERE seq=?", (d["target"],)).fetchone())
            result="已重新入队"
        else:
            raise ValueError("未知管理操作")
        db.execute("INSERT INTO operations VALUES(?,?,?,?)",(key,g,signature,result))
        detail=reason
        if op=="发放货币":
            detail=result+"；"+reason
        elif op in ("冲正","撤销误冲正"):
            detail=f"依据流水 #{target}；新增{result}；{reason}"
        audit(db,u["name"],g,op,detail)
        return result

