"""Local operations metrics and alert transitions. No message content is selected."""
import time

from . import voice_policy


CONNECTIONS = """
    SELECT g.id,g.account,g.binding,g.paused,json_extract(g.config,'$.enabled') AS enabled,
           a.mode,a.state,n.last_seen,profile.detached,m.grp IS NOT NULL AS joined,
           receiver.account IS NOT NULL AS listener,grant.grp IS NOT NULL AS granted,
           link.slot IS NOT NULL AND grant.grp IS NOT NULL AND p.grp IS NOT NULL AS directed,
           EXISTS (SELECT 1 FROM active_native_member_notices notice
                   WHERE notice.grp=g.id AND notice.account=g.account AND notice.binding=g.binding) AS notices,
           EXISTS (SELECT 1 FROM active_native_voice voice
                   WHERE voice.grp=g.id AND voice.account=g.account AND voice.binding=g.binding) AS voice_consent
    FROM groups g JOIN account a ON a.id=g.account
    LEFT JOIN group_profile profile ON profile.grp=g.id
    LEFT JOIN membership m ON m.grp=g.id AND m.account=g.account
    LEFT JOIN nodes n ON n.account=g.account
    LEFT JOIN listener_nodes receiver ON receiver.account=g.account
    LEFT JOIN node_grants grant ON grant.grp=g.id AND grant.account=g.account
    LEFT JOIN agent_wechat_links link ON link.grp=g.id AND link.account=g.account
    LEFT JOIN directed_groups p ON p.grp=g.id AND p.account=g.account AND p.binding=g.binding
"""


def _connection_status(db, row, now):
    if row["detached"]:
        return "detached", "本群已解绑", "重新绑定并核实群成员身份后才能恢复服务。"
    if row["paused"]:
        return "paused", "群绑定已暂停", "后台已暂停处理本群消息。"
    if not row["enabled"]:
        return "disabled", "本群已停用", "群配置中的机器人开关已关闭。"
    simulation = row["mode"] == "simulation"
    state = row["state"]
    if not simulation and state in ("ONLINE", "LISTENING", "RECONNECTING"):
        if row["last_seen"] is None:
            return "waiting_heartbeat", "等待接入心跳", "尚未收到当前账号的接入心跳。"
        if row["last_seen"] <= now - 30:
            return "stale", "接入心跳超时", "过去 30 秒未收到当前账号的新心跳。"
    if state != ("LISTENING" if row["listener"] else "ONLINE"):
        status = {"STOPPED":"已停止", "STARTING":"启动中", "WAITING_LOGIN":"等待登录",
                  "RECONNECTING":"重连中", "NEED_USER_ACTION":"等待人工处理", "SUSPENDED":"已暂停",
                  "ERROR":"出现错误"}.get(state, "未就绪")
        return "offline", "账号" + status, "请核对当前绑定账号的登录与连接状态。"
    if not simulation and not row["granted"]:
        return "ungranted", "缺少本群接入授权", "当前节点没有本群的接入授权。"
    if not row["joined"]:
        return "not_joined", "等待核实群成员身份", "当前绑定账号的群成员关系尚未核实。"
    if simulation:
        return "simulation", "模拟群已就绪", "消息由本地模拟适配器处理。"
    if not row["listener"]:
        return "online", "收发节点在线", "当前节点已上报本群成员关系和收发能力。"
    capabilities = []
    if row["directed"]:
        capabilities.append("点名文字回复")
    if row["notices"]:
        capabilities.append("成员通知")
    if row["voice_consent"] and voice_policy.active(db, row["id"], row["account"], row["binding"]) is not None:
        capabilities.append("语音唤醒回复")
    if capabilities:
        return ("directed" if row["directed"] else "limited", "本群监听在线",
                "当前绑定已授权" + "、".join(capabilities) + "。实际投递结果可查看发送回执。")
    return "listen_only", "本群仅监听", "当前绑定可接收群消息，尚无可用的发送授权。"


def _health(db, row, now):
    mode, title, detail = _connection_status(db, row, now)
    return dict(mode=mode, title=title, detail=detail, last_seen=row["last_seen"],
                directed=bool(row["directed"]), serviceable=mode in ("simulation", "online", "directed", "limited"))


def group_health(db, group, now=None):
    row = db.execute(CONNECTIONS + " WHERE g.id=?", (group,)).fetchone()
    if not row:
        raise ValueError("群不存在")
    return _health(db, row, time.time() if now is None else now)


def overview(db, user):
    groups = db.execute(CONNECTIONS + " WHERE ?='系统管理员' OR g.id IN (SELECT value FROM json_each(?))",
                        (user["role"], user["scopes"])).fetchall()
    now = time.time()
    serviceable = sum(_health(db, row, now)["serviceable"] for row in groups)
    return {"configured": len(groups), "serviceable": serviceable}


def sample_alerts(db, now):
    """Called inside the maintenance transaction. Preserve each incident's full interval."""
    conditions = db.execute("""
        SELECT g.id, '账号离线' FROM groups g JOIN account a ON a.id=g.account
         LEFT JOIN nodes n ON n.account=g.account
         WHERE (a.state NOT IN ('ONLINE','LISTENING') OR
               (a.mode='adapter' AND (n.last_seen IS NULL OR n.last_seen<=?)))
           AND json_extract(g.config,'$.enabled')
        UNION ALL SELECT id, '群绑定暂停' FROM groups WHERE paused=1
        UNION ALL SELECT DISTINCT grp, '发送结果未知' FROM outbox WHERE state='UNKNOWN'
        UNION ALL SELECT DISTINCT grp, '入站积压超过一分钟' FROM inbox
         WHERE state='PENDING' AND arrived<=?
        """, (now - 30, now - 60))
    active = set(map(tuple, conditions))
    previous = set(map(tuple, db.execute("SELECT grp,kind FROM group_alert WHERE recovered IS NULL")))
    db.executemany("INSERT INTO group_alert(grp,kind,opened) VALUES(?,?,?)",
                   [(group, kind, now) for group, kind in active - previous])
    db.executemany("UPDATE group_alert SET recovered=? WHERE grp=? AND kind=? AND recovered IS NULL",
                   [(now, group, kind) for group, kind in previous - active])
    db.execute("DELETE FROM group_alert WHERE recovered<?", (now - 90 * 86400,))
