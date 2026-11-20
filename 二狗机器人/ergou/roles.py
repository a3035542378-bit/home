"""按机器人领养关系与当前微信群身份鉴权，变更与指令在同一事务内提交。"""
import json
import re
import time
from datetime import datetime
from .db import BJ
from .display_names import labels

LEVEL = {"owner":5,"group_owner_granted":4,"admin":3,"member":2,"group_owner_pending":2,"guest":1}
REQUIRED = {"授权群主":5,"取消群主授权":5,"查看群主状态":4,"群主授权列表":5,"授权管理员":4,
            "取消管理员":4,"主人转移":5,"本群设置":4,"全局配置":5,"禁言":3,"踢人":3}
GAME_CONTROL = re.compile(r"(?:结束\s*(G[0-9]+)|(G[0-9]+)\s*重置)",re.I)


def owner(db, bot):
    return db.execute("SELECT * FROM bot_owner WHERE bot_id=? AND status='active'",(bot,)).fetchone()


def active(db,bot,group):
    return db.execute("""SELECT g.binding FROM groups g JOIN directed_groups p ON p.grp=g.id AND p.account=g.account
      AND g.binding=p.binding WHERE g.account=? AND g.id=? AND NOT g.paused AND json_extract(g.config,'$.enabled')""",
      (bot,group)).fetchone()


def role(db,bot,group,user):
    top=owner(db,bot)
    if top and top["owner_user_id"]==user:
        return "owner"
    room=db.execute("SELECT * FROM group_binding WHERE group_id=? AND bot_id=?",(group,bot)).fetchone()
    if not active(db,bot,group) or not room:
        return "guest"
    if user==room["owner_user_id"]:
        return "group_owner_granted" if room["owner_grant_status"]=="granted" and room["checked"]>time.time()-30 else "group_owner_pending"
    record=db.execute("SELECT role FROM group_member_role WHERE group_id=? AND user_id=?",(group,user)).fetchone()
    if record and record[0]=="admin" and room["checked"]<=time.time()-30:
        return "member"
    return record[0] if record else "member"


def require(db,bot,group,user,level):
    current=role(db,bot,group,user)
    if LEVEL[current]<level:
        raise ValueError("本群群主尚未获得主人授权，无法使用管理指令。" if current=="group_owner_pending" else {3:"权限不足，需要本群已授权的管理员。",4:"权限不足，需要主人或已授权的群主。",5:"权限不足，仅二狗主人可以操作。"}[level])
    return current


def log(db,bot,group,actor,action,target,detail=""):
    db.execute("INSERT INTO permission_audit_log(bot_id,group_id,actor_id,action,target_id,detail,created_at) VALUES(?,?,?,?,?,?,?)",
               (bot,group,actor,action,target,detail,time.time()))


def sync(db,bot,group,uid,name,*,departed=False,notify=True):
    now=time.time()
    room=db.execute("SELECT * FROM group_binding WHERE group_id=? AND bot_id=?",(group,bot)).fetchone()
    if room and not uid and not departed:
        db.execute("UPDATE group_binding SET checked=0 WHERE group_id=?",(group,))
        return
    if not room:
        db.execute("""INSERT INTO group_binding(group_id,bot_id,bound_at,label,owner_user_id,checked)
                      VALUES(?,?,?,?,?,?)""",(group,bot,now,name,uid,now if uid else 0))
    elif uid==room["owner_user_id"]:
        db.execute("UPDATE group_binding SET checked=?,label=? WHERE group_id=?",(now,name,group))
        return
    else:
        db.execute("""UPDATE group_binding SET owner_user_id=?,owner_grant_status=?,owner_granted_by=NULL,
                    owner_granted_at=NULL,owner_revoked_at=?,checked=?,label=? WHERE group_id=?""",
                   (uid,"pending" if uid else "revoked",now,now,name,group))
        db.execute("DELETE FROM group_member_role WHERE group_id=? AND user_id IN (?,?)",(group,room["owner_user_id"],uid))
        if room["owner_user_id"] or room["owner_grant_status"]=="revoked":
            log(db,bot,group,None,"group_owner_changed",uid,room["owner_user_id"])
    binding=active(db,bot,group)
    if notify and binding and (uid or departed):
        who=labels(db,group)(uid) if uid else ""
        text=(f"👑 当前群主 {who} · 待授权\n主人发「二狗授权群主」可开通本群管理权限。" if uid else "👑 原群主已离群，群主授权已失效。")
        db.execute("INSERT INTO role_notices(bot_id,destination,binding,body,expires,mention_user) VALUES(?,?,?,?,?,?)",
                   (bot,group,binding[0],text,now+120,uid))


def parse(cmd):
    return next((action for action in REQUIRED if cmd==action or cmd.startswith((action+" ",action+"@",action+"＠"))),None)


def handle(db,bot,group,actor,cmd,target=None):
    action=parse(cmd)
    current=require(db,bot,group,actor,REQUIRED[action])
    if REQUIRED[action]==5 and current!="owner":
        raise ValueError("仅二狗主人可操作。")
    args=cmd[len(action):].strip()
    room=db.execute("SELECT * FROM group_binding WHERE group_id=? AND bot_id=?",(group,bot)).fetchone()
    name=labels(db,group)
    def clock(stamp):
        return datetime.fromtimestamp(stamp,BJ).strftime("%m-%d %H:%M") if stamp else ""
    if action=="群主授权列表":
        page=int(args) if re.fullmatch(r"[1-9]\d{0,5}",args) else 1
        rows=db.execute("""SELECT * FROM group_binding WHERE bot_id=? ORDER BY group_id LIMIT 9 OFFSET ?""",(bot,(page-1)*8)).fetchall()
        lines=[f"📋 群主授权列表 · 第 {page} 页"]
        for r in rows[:8]:
            icon="✅" if r["owner_grant_status"]=="granted" else "⏳"
            lines.append(f"{icon} {r['label']} · {labels(db,r['group_id'])(r['owner_user_id'])} {clock(r['owner_granted_at'])}")
            lines.append(f"　群编号 {db.execute('SELECT rowid FROM group_binding WHERE group_id=?',(r['group_id'],)).fetchone()[0]}")
        return "\n".join(lines+([f"下页　二狗群主授权列表 {page+1}"] if len(rows)>8 else []))
    if action=="全局配置":
        if args:
            choices={"新群游戏 开启":1,"新群游戏 关闭":0}
            if args not in choices:
                raise ValueError("用法　二狗全局配置 新群游戏 开启 / 关闭")
            db.execute("UPDATE bot_owner SET default_games=? WHERE bot_id=?",(choices[args],bot))
        return "新激活群的游戏默认"+("开启" if owner(db,bot)["default_games"] else "关闭")
    if not room or not active(db,bot,group):
        raise ValueError("本群尚未激活或群主资料未就绪。")
    uid=room["owner_user_id"]
    if action=="查看群主状态":
        status="已授权 ✅" if room["owner_grant_status"]=="granted" else "待授权"
        detail=f"\n授权人　{name(room['owner_granted_by'])}\n时间　{clock(room['owner_granted_at'])}" if room["owner_granted_at"] and status.startswith("已") else ""
        return f"👑 {name(uid)} · {status}{detail}"
    if action in ("授权群主","取消群主授权"):
        if not uid or room["checked"]<time.time()-30:
            raise ValueError("暂时无法核实当前微信群主，请稍后再试。")
        if (args and not target) or (target and target!=uid):
            raise ValueError("请使用微信 @ 当前群主，或直接发送指令。")
        grant=action=="授权群主"
        if grant!=(room["owner_grant_status"]=="granted"):
            now=time.time()
            db.execute("""UPDATE group_binding SET owner_grant_status=?,owner_granted_by=?,owner_granted_at=?,
                         owner_revoked_at=? WHERE group_id=? AND owner_user_id=?""",
                       ("granted" if grant else "pending",actor if grant else None,now if grant else None,None if grant else now,group,uid))
            log(db,bot,group,actor,"grant_group_owner" if grant else "revoke_group_owner",uid)
        return ("✅ 已授权群主 " if grant else "已取消群主授权，退回待授权 · ")+name(uid)
    if action=="本群设置":
        cfg=json.loads(db.execute("SELECT config FROM groups WHERE id=?",(group,)).fetchone()[0])
        switches={"游戏":"games","投票":"polls","抽签":"draws"}
        if args:
            parts=args.split()
            if len(parts)!=2 or parts[0] not in switches or parts[1] not in ("开启","关闭"):
                raise ValueError("例如　二狗本群设置 游戏 关闭")
            cfg[switches[parts[0]]]=parts[1]=="开启"
            db.execute("UPDATE groups SET config=?,version=version+1 WHERE id=?",(json.dumps(cfg,ensure_ascii=False),group))
        return "⚙️ 本群设置\n"+"　".join(k+("开" if cfg[v] else "关") for k,v in switches.items())
    if not target or target==bot:
        raise ValueError("请用微信的 @ 功能选择一位本群成员。")
    if action=="主人转移":
        if target==actor:
            raise ValueError("对方已经是主人。")
        if db.execute("SELECT 1 FROM bot_owner WHERE owner_user_id=?",(target,)).fetchone():
            raise ValueError("对方已有领养绑定。")
        db.execute("UPDATE bot_owner SET owner_user_id=?,bound_at=? WHERE bot_id=? AND owner_user_id=?",(target,time.time(),bot,actor))
        log(db,bot,group,actor,"transfer_owner",target)
        return "👑 主人已转移给 "+name(target)
    if action in ("禁言","踢人"):
        return "当前微信节点未开通此项群管执行权限。"
    if target in (uid,owner(db,bot)["owner_user_id"]):
        raise ValueError("主人和微信群主使用专属身份。")
    if action=="授权管理员":
        changed=db.execute("""INSERT INTO group_member_role VALUES(?,?,'admin',?,?)
            ON CONFLICT(group_id,user_id) DO UPDATE SET role='admin',granted_by=excluded.granted_by,
            granted_at=excluded.granted_at WHERE role!='admin'""",(group,target,actor,time.time())).rowcount
    else:
        changed=db.execute("DELETE FROM group_member_role WHERE group_id=? AND user_id=? AND role='admin'",(group,target)).rowcount
    if changed:
        log(db,bot,group,actor,"grant_admin" if action=="授权管理员" else "revoke_admin",target)
    return ("✅ 已授权管理员 " if action=="授权管理员" else "已取消管理员 ")+name(target)
