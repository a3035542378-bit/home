"""Operating-console accounts and the local deployment bootstrap."""
import json

from . import admin
from .db import transaction


def _require_admin(actor):
    if not actor or actor["role"] != "系统管理员":
        raise PermissionError("FORBIDDEN 仅系统管理员可以管理后台账号")


def _groups(db):
    rows = db.execute("""SELECT g.id, COALESCE(NULLIF(p.alias,''),g.id) AS name
                         FROM groups g LEFT JOIN group_profile p ON p.grp=g.id
                         ORDER BY name,g.id""")
    return [dict(row) for row in rows]


def view(db, actor):
    _require_admin(actor)
    accounts = [
        dict(name=row["name"], role=row["role"], scopes=json.loads(row["scopes"]))
        for row in db.execute("SELECT name,role,scopes FROM users ORDER BY name")
    ]
    return dict(accounts=accounts, groups=_groups(db), roles=list(admin.ROLES))


def create(db, actor, data):
    _require_admin(actor)
    if not isinstance(data, dict) or set(data) != {"name", "password", "role", "scopes"}:
        raise ValueError("后台账号表单无效")
    name, password, role, scopes = (data[key] for key in ("name", "password", "role", "scopes"))
    if not isinstance(name, str) or not name.isprintable() or not 1 <= len(name.strip()) <= 80:
        raise ValueError("请输入 1–80 字符的账号名")
    name = name.strip()
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("密码应为 12–1024 个字符")
    if role not in admin.ROLES:
        raise ValueError("请选择有效的后台角色")
    if not isinstance(scopes, list) or any(not isinstance(group, str) for group in scopes):
        raise ValueError("授权群组无效")
    if role == "系统管理员" and scopes:
        raise ValueError("系统管理员拥有全部群组权限")
    if role != "系统管理员" and not scopes:
        raise ValueError("请至少选择一个授权群组")
    encoded = admin.password_hash(password)
    with transaction(db):
        if db.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            raise ValueError("CONFLICT 后台账号已存在")
        known = {row["id"] for row in db.execute("SELECT id FROM groups")}
        if set(scopes) - known:
            raise ValueError("所选群组不存在，请刷新后重试")
        admin.insert_user(db, name, encoded, role, sorted(set(scopes)), actor["name"])
    return view(db, actor)


def bootstrap(db, password):
    """Call only from the local deployment CLI. Never reset a migrated login."""
    with transaction(db):
        existing = db.execute("SELECT role FROM users WHERE name='admin'").fetchone()
        if existing:
            if existing["role"] != "系统管理员":
                raise ValueError("CONFLICT 已有同名账号，请核对其权限")
            return False
        if not isinstance(password, str) or not 6 <= len(password) <= 1024:
            raise ValueError("部署管理员初始密码应为 6–1024 个字符")
        admin.insert_user(db, "admin", admin.password_hash(password), "系统管理员", [], "local-cli")
        return True
