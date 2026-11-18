"""Loopback connector protocol. Each adapter instance authenticates as just one account."""
import hashlib
import json
import time
from .db import DEFAULT,audit,dump,transaction
from .engine import receive
from .jobs import claim,finish


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def enroll(db,account,group,secret,*,listen_only=False):
    with transaction(db):
        enroll_in_transaction(db,account,group,secret,listen_only=listen_only)


def enroll_in_transaction(db,account,group,secret,*,listen_only=False):
    """Register a node together with the caller's atomic link or transfer."""
    if not db.in_transaction:
        raise RuntimeError("节点登记需要事务")
    if (account=="sim-account" or not 1<=len(account)<=160 or not 1<=len(group)<=160 or len(secret)<32):
        raise ValueError("需要稳定账号与群标识，以及至少 32 字符的节点密钥")
    db.execute("INSERT OR IGNORE INTO account VALUES(?,'adapter','WAITING_LOGIN')",(account,))
    if db.execute("SELECT mode FROM account WHERE id=?",(account,)).fetchone()[0]!="adapter":
        raise ValueError("账号与模拟实例冲突")
    old=db.execute("SELECT secret_hash FROM nodes WHERE account=?",(account,)).fetchone()
    if old and old[0]!=digest(secret):raise ValueError("账号已登记，密钥不匹配")
    listener=db.execute("SELECT 1 FROM listener_nodes WHERE account=?",(account,)).fetchone()
    if old and bool(listener)!=listen_only:raise ValueError("已登记节点的收发模式与请求不符")
    db.execute("INSERT OR IGNORE INTO nodes(account,secret_hash) VALUES(?,?)",(account,digest(secret)))
    if listen_only:
        db.execute("INSERT OR IGNORE INTO listener_nodes VALUES(?)",(account,))
    db.execute("INSERT OR IGNORE INTO groups(id,account,config) VALUES(?,?,?)",(group,account,dump(DEFAULT)))
    db.execute("INSERT OR IGNORE INTO node_grants VALUES(?,?)",(account,group))
    audit(db,"local-cli",group,"登记接入节点",account)


def endpoint(db,op,secret,data):
    node=db.execute("SELECT * FROM nodes WHERE secret_hash=?",(digest(secret),)).fetchone()
    if not node:raise PermissionError("FORBIDDEN 无效接入节点")
    account=node["account"]
    listener=db.execute("SELECT 1 FROM listener_nodes WHERE account=?",(account,)).fetchone() is not None
    if listener and op in ("claim","result"):
        raise PermissionError("FORBIDDEN 当前节点仅接收消息")
    now=time.time()
    if op=="heartbeat":
        caps=data.get("capabilities",{})
        if not isinstance(caps,dict) or any(type(v) is not bool for v in caps.values()):raise ValueError("能力字段格式错误")
        version=data.get("adapter_version","")
        if not isinstance(version,str) or not 1<=len(version)<=160:raise ValueError("缺少适配器版本")
        groups=data.get("groups",[])
        if not isinstance(groups,list) or len(groups)>1000 or any(not isinstance(g,str) or len(g)>160 for g in groups):raise ValueError("群标识格式错误")
        state=data.get("state")
        if state not in ("STOPPED","STARTING","WAITING_LOGIN","ONLINE","LISTENING","RECONNECTING","NEED_USER_ACTION","SUSPENDED","ERROR"):raise ValueError("状态无效")
        if state in ("ONLINE","LISTENING"):
            expected_state="LISTENING" if listener else "ONLINE"
            if (data.get("actual_account")!=account or not caps.get("receive") or not caps.get("stable_ids")
                or caps.get("send")!=(not listener) or state!=expected_state):
                state="NEED_USER_ACTION"
        with transaction(db):
            permitted={r[0] for r in db.execute("SELECT grp FROM node_grants WHERE account=?",(account,))}
            joined=set(groups)&permitted
            if state=="LISTENING" and not joined:state="NEED_USER_ACTION"
            db.execute("UPDATE nodes SET last_seen=?,version=?,caps=? WHERE account=?",(now,version,dump(caps),account))
            db.execute("UPDATE account SET state=? WHERE id=?",(state,account))
            db.execute("DELETE FROM membership WHERE account=?",(account,))
            if state in ("ONLINE","LISTENING"):
                db.executemany("INSERT INTO membership VALUES(?,?)",[(account,g) for g in joined])
        return {"state":state}
    if op=="result":
        allowed={"ACKNOWLEDGED","UNKNOWN","RETRY_WAIT","FAILED"}
        if data.get("state") not in allowed or type(data.get("attempt")) is not int or not 1<=data["attempt"]<=4:
            raise ValueError("发送结果无效")
        changed=finish(db,account,int(data["task"]),data["attempt"],data["state"],"节点回执："+data["state"])
        return {"updated":changed}
    online=db.execute("SELECT state FROM account WHERE id=?",(account,)).fetchone()[0] in ("ONLINE","LISTENING")
    if not online or not node["last_seen"] or node["last_seen"]<=now-30:raise ValueError("ACCOUNT_OFFLINE 等待已验证的账号心跳")
    if op=="event":
        seq=receive(db,account,data["group_id"],data["sender_id"],data["source_message_id"],data["payload"],
                    kind=data.get("event_type","message"),message_type=data.get("message_type","text"),adapter_version=node["version"])
        return {"ingest_sequence":seq}
    if op=="claim":
        task=claim(db,account)
        if not isinstance(task,dict):return {"task":None}
        return {"task":{k:task[k] for k in ("id","biz","grp","binding","body","attempt","expires")}}
    raise ValueError("未知接入操作")

