CREATE TABLE IF NOT EXISTS bot_owner (
 bot_id TEXT PRIMARY KEY REFERENCES account, owner_user_id TEXT NOT NULL UNIQUE,
 bound_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','transferred','revoked')),
 default_games INTEGER NOT NULL DEFAULT 1 CHECK(default_games IN (0,1))
);
CREATE TABLE IF NOT EXISTS group_binding (
 group_id TEXT PRIMARY KEY REFERENCES groups, bot_id TEXT NOT NULL REFERENCES bot_owner,
 bound_by TEXT, bound_at REAL NOT NULL, label TEXT NOT NULL,
 owner_user_id TEXT, owner_grant_status TEXT NOT NULL DEFAULT 'pending'
 CHECK(owner_grant_status IN ('pending','granted','revoked')), owner_granted_by TEXT,
 owner_granted_at REAL, owner_revoked_at REAL, checked REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS group_member_role (
 group_id TEXT NOT NULL REFERENCES group_binding, user_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','member','guest')), granted_by TEXT, granted_at REAL,
 PRIMARY KEY(group_id,user_id)
);
CREATE TABLE IF NOT EXISTS permission_audit_log (
 id INTEGER PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bot_owner, group_id TEXT, actor_id TEXT,
 action TEXT NOT NULL CHECK(action IN ('grant_group_owner','revoke_group_owner','group_owner_changed',
 'grant_admin','revoke_admin','transfer_owner')), target_id TEXT, detail TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS role_notices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id TEXT NOT NULL, destination TEXT NOT NULL, binding INTEGER,
 body TEXT NOT NULL, expires REAL NOT NULL, source TEXT, mention_user TEXT, UNIQUE(bot_id,source)
);
CREATE VIEW IF NOT EXISTS group_binding_state AS
 SELECT b.*,CASE WHEN g.paused=0 AND g.account=b.bot_id AND p.grp IS NOT NULL
 AND json_extract(g.config,'$.enabled') THEN 'active' ELSE 'disabled' END status FROM group_binding b
 JOIN groups g ON g.id=b.group_id LEFT JOIN directed_groups p ON p.grp=g.id AND p.account=g.account AND p.binding=g.binding;
