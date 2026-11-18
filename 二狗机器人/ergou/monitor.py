"""Local operations metrics and alert transitions. No message content is selected."""
import time


def overview(db, user):
    groups = db.execute("""
        SELECT g.id, g.paused, json_extract(g.config,'$.enabled') AS enabled, a.state,
               m.grp IS NOT NULL AS joined, a.mode, n.last_seen
        FROM groups g JOIN account a ON a.id=g.account
        LEFT JOIN membership m ON m.grp=g.id AND m.account=g.account
        LEFT JOIN nodes n ON n.account=g.account
        WHERE ?='系统管理员' OR g.id IN (SELECT value FROM json_each(?))
        """, (user["role"], user["scopes"])).fetchall()
    now = time.time()
    serviceable = sum(bool(row["enabled"] and not row["paused"] and row["joined"]
                           and row["state"] == "ONLINE" and (row["mode"] == "simulation"
                           or (row["last_seen"] or 0) > now - 30)) for row in groups)
    return {"configured": len(groups), "serviceable": serviceable}


def sample_alerts(db, now):
    """Called inside the maintenance transaction. Preserve each incident's full interval."""
    conditions = db.execute("""
        SELECT g.id, '账号离线' FROM groups g JOIN account a ON a.id=g.account
         WHERE a.state NOT IN ('ONLINE','LISTENING') AND json_extract(g.config,'$.enabled')
        UNION ALL SELECT id, '群绑定暂停' FROM groups WHERE paused=1
        UNION ALL SELECT DISTINCT grp, '发送结果未知' FROM outbox WHERE state='UNKNOWN'
        UNION ALL SELECT DISTINCT grp, '入站积压超过一分钟' FROM inbox
         WHERE state='PENDING' AND arrived<=?
        """, (now - 60,))
    active = set(map(tuple, conditions))
    previous = set(map(tuple, db.execute("SELECT grp,kind FROM group_alert WHERE recovered IS NULL")))
    db.executemany("INSERT INTO group_alert(grp,kind,opened) VALUES(?,?,?)",
                   [(group, kind, now) for group, kind in active - previous])
    db.executemany("UPDATE group_alert SET recovered=? WHERE grp=? AND kind=? AND recovered IS NULL",
                   [(now, group, kind) for group, kind in previous - active])
    db.execute("DELETE FROM group_alert WHERE recovered<?", (now - 90 * 86400,))
