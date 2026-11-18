import hashlib
import hmac
import json
import os
import secrets
import string
import time
from urllib.parse import urlsplit
from datetime import datetime
from .db import BJ, DEFAULT, allowed, audit, dump, transaction, window
from .engine import ranking
from .games import GAMES
from . import reports

ROLES=("系统管理员","运营管理员","群管理员","只读人员")


def password_hash(password):
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,600000)
    return salt.hex()+"."+digest.hex()


def insert_user(db,name,encoded,role,scopes,actor):
    """Insert and audit inside the caller's transaction."""
    db.execute("INSERT INTO users(name,password,role,scopes) VALUES(?,?,?,?)",
               (name,encoded,role,dump(scopes)))
    audit(db,actor,None,"创建后台用户",name)


def user(db,name,password,role,scopes):
    if role not in ROLES or len(password)<12 or not name or len(name)>80:
        raise ValueError("角色无效或密码少于 12 字符")
    encoded=password_hash(password)
    with transaction(db):
        insert_user(db,name,encoded,role,scopes,"local-cli")


def login(db,name,password,address):
    with transaction(db):
        if not allowed(db,"auth/"+address,12,60,time.time()):
            raise ValueError("RATE_LIMITED 请稍后再登录")
    u=db.execute("SELECT * FROM users WHERE name=?",(name,)).fetchone()
    salt,expected=(u["password"] if u else ("00"*16+"."+"00"*32)).split(".")
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),600000)
    if not hmac.compare_digest(digest.hex(),expected) or not u:
        raise PermissionError("登录失败")
    token=secrets.token_urlsafe(32)
    db.execute("INSERT INTO tokens VALUES(?,?,?)",(token_hash(token),name,time.time()+8*3600))
    return token


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def identity(db,token):
    return db.execute("SELECT u.name,u.role,u.scopes FROM users u JOIN tokens t ON t.name=u.name WHERE t.digest=? AND t.expires>?",(token_hash(token),time.time())).fetchone()


def permitted(u,group,write=False):
    if not u or (write and u["role"]=="只读人员") or (u["role"]!="系统管理员" and group not in json.loads(u["scopes"])):
        raise PermissionError("FORBIDDEN 超出授权范围")


def validate(patch):
    if not isinstance(patch,dict) or not patch or not set(patch)<=set(DEFAULT):
        raise ValueError("INVALID_ARGUMENT 配置项无效")
    for k,v in patch.items():
        if type(v) is not type(DEFAULT[k]):
            raise ValueError("配置类型错误："+k)
        if isinstance(v,str) and len(v)>500:
            raise ValueError("配置内容过长")
        if isinstance(v,list) and (len(v)>(len(GAMES) if k=="disabled_games" else 100) or any(not isinstance(w,str) or not 0<len(w)<=80 for w in v)):
            raise ValueError("列表内容无效")
    if "prefix" in patch and (not 1<=len(patch["prefix"])<=12 or any(c.isspace() for c in patch["prefix"])):
        raise ValueError("前缀须为 1–12 个非空白字符")
    if not 1<=patch.get("max_games",3)<=3 or not 0<=patch.get("reward",10)<=100:
        raise ValueError("并行局数应为 1–3，奖励应为 0–100")
    if patch.get("moderation","记录") not in ("记录","提醒","撤回","移出群聊") or any(not 0<=patch.get(k,0)<=23 for k in ("quiet_start","quiet_end")):
        raise ValueError("规则动作或静默时段无效")
    if "welcome" in patch:
        for _,name,spec,conv in string.Formatter().parse(patch["welcome"]):
            if name is not None and (name not in ("群","成员","nickname","时间","群规") or spec or conv):
                raise ValueError("欢迎语仅支持 {群}、{成员}、{nickname}、{时间}、{群规}")
    link=patch.get("rules_url","")
    if link:
        url=urlsplit(link)
        if url.scheme not in ("https","http") or not url.hostname or url.username or any(c.isspace() for c in link):
            raise ValueError("请输入完整的群规网页链接")
    if not 0<=patch.get("welcome_window",0)<=60 or not 0<=patch.get("daily_rewards",0)<=1000:
        raise ValueError("合并窗口或每日奖励次数超限")
    if not 1<=patch.get("send_rate",5)<=30 or not 1<=patch.get("command_rate",30)<=100:
        raise ValueError("发送或指令限额超出范围")
    if set(patch.get("disabled_games",[]))-set(GAMES):raise ValueError("停用游戏名称不存在")
    reserved=set("帮助 积分 周榜 月榜 总榜 群规 天气 快递 运势 游戏列表 开始 加入 退出 状态 结束 投票 抽签".split())
    for name,dest in patch.get("aliases",{}).items():
        if not 1<=len(name)<=12 or any(c.isspace() for c in name) or name in reserved or name in GAMES or name.upper().startswith("G") or dest not in reserved:
            raise ValueError("别名冲突或目标无效："+name)


def configure(db,u,group,version,patch):
    permitted(u,group,True)
    validate(patch)
    with transaction(db):
        row=db.execute("SELECT config,version FROM groups WHERE id=?",(group,)).fetchone()
        if not row or row["version"]!=version:
            raise ValueError("CONFLICT 配置已更新，请刷新")
        config=json.loads(row["config"])|patch
        db.execute("INSERT OR IGNORE INTO config_history VALUES(?,?,?,?)",(group,version,time.time(),row["config"]))
        db.execute("INSERT INTO config_history VALUES(?,?,?,?)",(group,version+1,time.time(),dump(config)))
        db.execute("UPDATE groups SET config=?,version=version+1 WHERE id=?",(dump(config),group))
        audit(db,u["name"],group,"保存群配置",f"v{version} → v{version+1}，字段 "+",".join(sorted(patch)))
        return version+1


VIEWS={
 "群消息接收记录":"""SELECT seq 序号,arrived 接收时间,source 来源消息ID,member 发送成员ID,
                    adapter_version 接入组件,state 处理状态 FROM inbox
                    WHERE grp=? AND kind='message' ORDER BY seq DESC LIMIT 200""",
 "运行告警":"""SELECT kind 告警,CASE WHEN recovered IS NULL THEN '待处理' ELSE '已恢复' END 状态,
              opened 首次发现,recovered 恢复时间 FROM group_alert WHERE grp=?
              ORDER BY recovered IS NOT NULL,opened DESC,id DESC LIMIT 200""",
 "会话":"SELECT code 编号,game 玩法,state 状态,owner 发起人,reason 结局 FROM games WHERE grp=? ORDER BY id DESC LIMIT 200",
 "积分":"SELECT member 成员,SUM(points) 积分 FROM ledger WHERE grp=? GROUP BY member ORDER BY 积分 DESC,member LIMIT 200",
 "积分流水":"SELECT member 成员,points 变动,kind 类型,reason 原因,at 时间 FROM ledger WHERE grp=? ORDER BY id DESC LIMIT 200",
 "发送任务":"SELECT id 编号,state 状态,attempts 尝试,detail 结果 FROM outbox WHERE grp=? ORDER BY id DESC LIMIT 200",
 "入站异常":"SELECT seq 序号,trace 跟踪号,state 状态,result 原因 FROM inbox WHERE grp=? AND state IN ('REJECTED','FAILED','RATE_LIMITED') ORDER BY seq DESC LIMIT 200",
 "定时通知":"""SELECT s.id 编号,version 版本,CASE t.kind WHEN 'weather' THEN '天气' WHEN 'news' THEN '香港要闻'
             WHEN 'weather_news' THEN '天气与香港要闻' ELSE '文字通知' END 类型,body 内容,period 周期,due 下次执行,
             until 结束时间,enabled 启用,CASE
             WHEN NOT EXISTS(SELECT 1 FROM groups g JOIN listener_nodes l ON l.account=g.account WHERE g.id=s.grp) THEN '按群设置执行'
             WHEN EXISTS(SELECT 1 FROM valid_live_notices v WHERE v.schedule=s.id) THEN '已确认一次'
             WHEN s.period='一次' AND t.kind IS NULL THEN '需本机逐条确认' ELSE '当前微信绑定不主动发送此类型' END 微信授权,
             (SELECT result FROM runs WHERE schedule=s.id ORDER BY due DESC LIMIT 1) 最近执行
             FROM schedules s LEFT JOIN bulletin_types t ON t.schedule=s.id WHERE grp=? ORDER BY s.id DESC LIMIT 200""",
 "规则命中":"SELECT h.seq 事件,h.version 规则版本,h.result 处置,COALESCE(a.outcome,'已记录') 执行结果 FROM hits h LEFT JOIN moderation_actions a ON a.seq=h.seq WHERE h.grp=? ORDER BY h.id DESC LIMIT 200",
 "审计":"SELECT actor 操作人,action 操作,detail 说明,at 时间 FROM audit WHERE grp=? ORDER BY id DESC LIMIT 200",
 "后台权限":"SELECT name 用户,role 角色 FROM users WHERE EXISTS (SELECT 1 FROM json_each(scopes) WHERE value=?) ORDER BY name",
 "撤回记录":"SELECT seq 编号,at 时间 FROM recalls WHERE grp=? ORDER BY seq DESC LIMIT 200",
}


def view(db,u,group,name):
    permitted(u,group)
    if name in ("后台权限","撤回记录") and u["role"]!="系统管理员":
        raise PermissionError("FORBIDDEN 仅系统管理员")
    if name=="游戏目录":
        return [dict(编号=g.id,游戏=g.name,品类=g.category,规则=g.prompt) for g in GAMES.values()]
    if name=="外部服务":
        return [dict(服务="天气",供应商="Open-Meteo",凭据="非商业免费接口"),
                dict(服务="国内快递",供应商="快递鸟 1002",凭据="已配置" if os.getenv("ERGOU_KDN_ID") and os.getenv("ERGOU_KDN_KEY") else "待配置"),
                dict(服务="国际快递",供应商="DHL",凭据="已配置" if os.getenv("ERGOU_DHL_KEY") else "待配置")]
    if name=="周报":
        return [reports.weekly(db, group, window("周榜",time.time()))]
    if name=="周报归档":
        return reports.archive(db, group)
    if name=="上周采集缺口":
        end=window("周榜",time.time())
        gaps=reports.missing_intervals(db,group,end-reports.WEEK,end)
        def bj_time(minute):
            return datetime.fromtimestamp(minute*60,BJ).strftime("%Y-%m-%d %H:%M")
        return [dict(起始时间=bj_time(a),结束时间=bj_time(b),未覆盖分钟=b-a) for a,b in gaps]
    if name not in VIEWS:
        raise ValueError("视图不存在")
    return [dict(r) for r in db.execute(VIEWS[name],(group,))]


def schedule(db,u,group,data):
    permitted(u,group,True)
    dt=datetime.fromisoformat(data["time"])
    due=(dt.replace(tzinfo=BJ) if dt.tzinfo is None else dt).timestamp()
    until=None
    if data.get("until"):
        end=datetime.fromisoformat(data["until"])
        until=(end.replace(tzinfo=BJ) if end.tzinfo is None else end).timestamp()
        if until<due:raise ValueError("结束时间早于首次执行时间")
    period=data["period"]
    from . import bulletins
    kind,body=bulletins.parse(data)
    if period not in ("一次","每日","每周") or type(data.get("catchup",False)) is not bool:
        raise ValueError("通知参数无效")
    with transaction(db):
        values=(body,period,due,data.get("catchup",False),until)
        if data.get("id") is not None:
            task=int(data["id"])
            changed=db.execute("""UPDATE schedules SET body=?,period=?,due=?,catchup=?,until=?,enabled=1,version=version+1
                               WHERE grp=? AND id=? AND version=?""",(*values,group,task,data.get("version"))).rowcount
            if not changed:raise ValueError("CONFLICT 未找到通知或版本已变更")
            bulletins.set_kind(db,task,kind)
            audit(db,u["name"],group,"更新定时通知",str(task))
            return task
        cur=db.execute("INSERT INTO schedules(grp,body,period,due,catchup,until) VALUES(?,?,?,?,?,?)",(group,*values))
        bulletins.set_kind(db,cur.lastrowid,kind)
        audit(db,u["name"],group,"创建定时通知",str(cur.lastrowid))
        return cur.lastrowid

