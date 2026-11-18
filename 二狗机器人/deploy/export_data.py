"""Export portable ErGou configuration and game history into a fresh database."""
import argparse
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from ergou import db


# Explicit destination columns and source projections prevent new columns or
# new tables in a live database from silently expanding the transfer.
TABLES = {
    "account": ("id,mode,state", "id,mode,'SUSPENDED'"),
    "groups": ("id,account,binding,paused,version,config", "id,account,binding,1,version,portable_config(config)"),
    "group_profile": ("grp,alias,version,detached", None),
    "games": ("id,grp,code,game,owner,state,rules,board,started,deadline,ended,reason",
              """id,grp,code,game,owner,
                 CASE WHEN state IN ('RUNNING','PAUSED','WAITING_PLAYERS') THEN 'ABORTED' ELSE state END,
                 rules,board,started,deadline,
                 CASE WHEN state IN ('RUNNING','PAUSED','WAITING_PLAYERS') THEN :now ELSE ended END,
                 CASE WHEN state IN ('RUNNING','PAUSED','WAITING_PLAYERS') THEN '迁移时结束' ELSE reason END"""),
    "participation": ("game,member,joined", None),
    "players": ("game,member,joined", None),
    "ledger": ("id,grp,member,game,round,kind,points,rule_version,event,at,reason", None),
    "draws": ("id,grp,event,member,at,pool,winners,reason", None),
    "reward_offers": ("grp,name,price", None),
    "reply_rule_sets": ("grp,version,rules", None),
    "schedules": ("id,grp,body,period,due,catchup,enabled,until,version",
                  "id,grp,body,period,due,catchup,0,until,version"),
    "bulletin_types": ("schedule,kind", None),
    "smart_controls": ("grp,version,enabled,generation,admins", "grp,version,enabled,generation,'[]'"),
    "chat_models": ("grp,version,provider,model", None),
    "member_notice_settings": ("grp,kind,enabled,version", "grp,kind,0,version"),
    "voice_settings": ("grp,enabled,version", "grp,0,version"),
}


def _portable_config(raw):
    fields = json.loads(raw)
    if not isinstance(fields, dict):
        raise ValueError("群配置格式无效")
    config = {key: fields.get(key, value) for key, value in db.DEFAULT.items()}
    config.update(allowlist=[], weekly_push=False)
    return db.dump(config)


def _handoff(source, target, tables):
    target.execute("""CREATE TABLE migration_handoff (
                      grp TEXT PRIMARY KEY,account TEXT NOT NULL,binding INTEGER NOT NULL)""")
    if not {"agent_wechat_links", "directed_groups", "node_grants", "listener_nodes", "group_profile"} <= tables:
        return
    rows = source.execute("""SELECT g.id,g.account,g.binding FROM groups g
        JOIN account a ON a.id=g.account AND a.mode='adapter'
        JOIN directed_groups d ON d.grp=g.id AND d.account=g.account AND d.binding=g.binding
        JOIN agent_wechat_links l ON l.grp=g.id AND l.account=g.account
        JOIN node_grants n ON n.grp=g.id AND n.account=g.account
        JOIN listener_nodes h ON h.account=g.account
        LEFT JOIN group_profile p ON p.grp=g.id
        WHERE g.paused=0 AND COALESCE(p.detached,0)=0 AND json_extract(g.config,'$.enabled')=1""")
    target.executemany("INSERT INTO migration_handoff VALUES(?,?,?)", rows)


def _alias(target, alias):
    if not isinstance(alias, str) or not alias.isprintable() or not 1 <= len(alias.strip()) <= 80:
        raise ValueError("群昵称应为 1–80 个字符")
    rows = target.execute("""SELECT g.id FROM groups g JOIN account a ON a.id=g.account
                             WHERE a.mode='adapter'""").fetchall()
    if len(rows) != 1:
        raise ValueError("指定群昵称要求源库恰好有一个真实微信群")
    target.execute("""INSERT INTO group_profile(grp,alias) VALUES(?,?)
                      ON CONFLICT(grp) DO UPDATE SET alias=excluded.alias WHERE group_profile.alias=''""",
                   (rows[0][0], alias.strip()))


def _schedule_projection(source, columns):
    # Older databases predate the optional end date and optimistic version.
    existing = {row[1] for row in source.execute("PRAGMA table_info(schedules)")}
    fallback = {"version": "1", "until": "NULL"}
    selected = []
    for col in columns.split(","):
        if col == "enabled":
            selected.append("0")
        elif col in existing:
            selected.append(col)
        else:
            selected.append(fallback[col])
    return ",".join(selected)


def export(source_path, target_path, group_alias=None):
    source_path = Path(source_path).resolve(strict=True)
    target_path = Path(target_path).resolve()
    if any(Path(str(target_path) + suffix).exists() for suffix in ("", "-wal", "-shm", "-journal")):
        raise FileExistsError("迁移目标必须是全新文件")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target_path.parent) as folder:
        staging = Path(folder) / "export.sqlite"
        staging.touch(mode=0o600)
        db.initialize(staging)
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source, db.closing_db(staging) as target:
            source.execute("BEGIN")
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"account", "groups", "games", "ledger", "schedules"} <= tables:
                raise ValueError("源文件缺少二狗数据库的业务表")
            source.create_function("portable_config", 1, _portable_config)
            now = time.time()
            with db.transaction(target):
                for name, (columns, projection) in TABLES.items():
                    if name not in tables:
                        continue
                    if name == "schedules":
                        projection = _schedule_projection(source, columns)
                    rows = source.execute(f"SELECT {projection or columns} FROM {name}", {"now": now})
                    marks = ",".join("?" for _ in columns.split(","))
                    target.executemany(f"INSERT INTO {name}({columns}) VALUES({marks})", rows)
                _handoff(source, target, tables)
                if group_alias is not None:
                    _alias(target, group_alias)
                if target.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("迁移后的业务数据关联校验失败")
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("迁移数据库完整性校验失败")
            counts = {table: target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in (*TABLES, "migration_handoff")}
            target.execute("PRAGMA journal_mode=DELETE")
        # Hard-link publication is atomic and fails if another writer creates
        # the requested destination while this process is exporting.
        os.link(staging, target_path)
    return counts


def main():
    parser = argparse.ArgumentParser(description="导出群配置与业务历史到全新的暂停状态数据库")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--group-alias")
    args = parser.parse_args()
    try:
        counts = export(args.source, args.destination, args.group_alias)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"导出失败：{exc}\n")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
