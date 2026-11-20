import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8), "Asia/Shanghai")
DEFAULT = dict(enabled=True, prefix="二狗", rules="友善交流，尊重隐私。", welcome="欢迎{成员}加入{群}！",
               reward=10, max_games=3, words=[], allowlist=[], moderation="记录", city="",
               bots=[], games=True, polls=True, draws=True, quiet_start=0, quiet_end=0,
               welcome_window=0,daily_rewards=0,aliases={},disabled_games=[],exact_words=[],
               fishing_cooldown_seconds=20,weekly_push=False,send_rate=5,command_rate=30,rules_url="")
SCHEMA = Path(__file__).with_name("schema.sql")


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def connect(path):
    db = sqlite3.connect(path, timeout=3, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    return db


def initialize(path):
    from .group_tools import SCHEMA as group_tools_schema
    from .moderation import SCHEMA as moderation_schema
    from .bulletins import SCHEMA as bulletin_schema
    from .member_policy import SCHEMA as policy_schema
    from .native_roster import SCHEMA as roster_schema
    from .member_notices import SCHEMA as deliveries_schema
    from .voice_policy import SCHEMA as voice_policy_schema
    from .native_voice import SCHEMA as voice_events_schema
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing_db(path) as db:
        version=db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3):
            raise ValueError("数据库版本不兼容")
        db.execute("PRAGMA journal_mode=WAL")
        columns={r[1] for r in db.execute("PRAGMA table_info(schedules)")}
        migrate=""
        if columns and "until" not in columns:
            migrate+="ALTER TABLE schedules ADD COLUMN until REAL;\n"
        if columns and "version" not in columns:
            migrate+="ALTER TABLE schedules ADD COLUMN version INTEGER NOT NULL DEFAULT 1;\n"
        waters={r[1] for r in db.execute("PRAGMA table_info(fishing_waters)")}
        if waters and "area" not in waters:
            migrate+="ALTER TABLE fishing_waters ADD COLUMN area TEXT NOT NULL DEFAULT '外海';\n"
        pond_columns={r[1] for r in db.execute("PRAGMA table_info(fishing_pond)")}
        if pond_columns and "storage" not in pond_columns:
            migrate+="ALTER TABLE fishing_pond ADD COLUMN storage TEXT NOT NULL DEFAULT 'pond' CHECK(storage IN ('pond','bag'));\n"
        backfill="INSERT OR IGNORE INTO participation SELECT game,member,joined FROM players;" if version<3 else ""
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fishing_species'").fetchone():
            # 只补录升级前的鱼获，之后转手的鱼不计入新主人的垂钓纪录。
            backfill+="""
INSERT OR IGNORE INTO fishing_species(grp,member,fish,best_grams)
 SELECT grp,member,fish,max(grams) FROM (
 SELECT grp,member,fish,grams FROM fishing_pond
 UNION ALL SELECT grp,member,best_name,best_grams FROM fishing_records
 ) GROUP BY grp,member,fish;"""
        from .fish_grades import base_grade
        db.create_function("fish_base_grade", 2, base_grade)
        for table, field, grams in (("fishing_pond", "grade", "grams"), ("fishing_exhibits", "grade", "grams"),
                                    ("fishing_species", "best_grade", "best_grams")):
            fields = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            if fields and field not in fields:
                migrate += f"ALTER TABLE {table} ADD COLUMN {field} INTEGER CHECK({field} BETWEEN 0 AND 5);\n"
                migrate += f"ALTER TABLE {table} ADD COLUMN {field}_upgraded INTEGER NOT NULL DEFAULT 0;\n"
            if field not in fields:
                backfill += f"UPDATE {table} SET {field}=fish_base_grade(fish,{grams}) WHERE {field} IS NULL;\n"
        old_link = db.execute("SELECT sql FROM sqlite_master WHERE name='agent_wechat_links'").fetchone()
        if old_link and "UNIQUE(account)" in old_link[0]:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("PRAGMA legacy_alter_table=ON")
            migrate += "ALTER TABLE agent_wechat_links RENAME TO single_group_links;\n"
            backfill += "INSERT INTO agent_wechat_links SELECT * FROM single_group_links; DROP TABLE single_group_links;"
        db.executescript("\n".join(("BEGIN IMMEDIATE;",migrate,SCHEMA.read_text(encoding="utf-8"),
                                    group_tools_schema,moderation_schema,bulletin_schema,policy_schema,roster_schema,
                                    deliveries_schema,voice_policy_schema,voice_events_schema,backfill,"COMMIT;")))


@contextmanager
def closing_db(path):
    db = connect(path)
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def audit(db, actor, group, action, detail):
    db.execute("INSERT INTO audit(at,actor,grp,action,detail) VALUES(?,?,?,?,?)",
               (time.time(), actor, group, action, detail))


def record_failure(db, group, seq, kind, reason):
    """Callers supply fixed, operator-readable categories, never a raw exception."""
    db.execute("""INSERT INTO service_failures(grp,seq,kind,reason,at) VALUES(?,?,?,?,?)
                  ON CONFLICT(seq,kind) DO UPDATE SET reason=excluded.reason,at=excluded.at""",
               (group,seq,kind,reason,time.time()))


def demo(path, groups=("demo-group",)):
    with closing_db(path) as db, transaction(db):
        db.execute("INSERT OR IGNORE INTO account VALUES('sim-account','simulation','ONLINE')")
        for group in groups:
            db.execute("INSERT OR IGNORE INTO membership VALUES('sim-account',?)", (group,))
            db.execute("INSERT OR IGNORE INTO groups(id,account,config) VALUES(?,'sim-account',?)", (group, dump(DEFAULT)))
            db.execute("INSERT OR IGNORE INTO managers VALUES(?,'operator')", (group,))


def window(period, now):
    day = datetime.fromtimestamp(now, BJ).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "周榜":
        return (day - timedelta(days=day.weekday())).timestamp()
    if period == "月榜":
        return day.replace(day=1).timestamp()
    return 0


def allowed(db, key, limit, seconds, now):
    row = db.execute("SELECT * FROM throttles WHERE key=?", (key,)).fetchone()
    if row and row["start"] + seconds > now:
        if row["used"] >= limit:
            return False
        db.execute("UPDATE throttles SET used=used+1 WHERE key=?", (key,))
    else:
        db.execute("INSERT OR REPLACE INTO throttles VALUES(?,?,1)", (key, now))
    return True


def backup(path, target):
    target = Path(target)
    with target.open("xb"):
        pass
    try:
        with closing_db(path) as src, closing_db(target) as dst:
            src.backup(dst)
            dst.execute("PRAGMA secure_delete=ON")
            with transaction(dst):
                for table in ("voice_test_tickets","voice_verifications"):
                    if dst.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
                        dst.execute(f"DELETE FROM {table}")
                if dst.execute("SELECT 1 FROM sqlite_master WHERE name='voice_approvals'").fetchone():
                    dst.execute("DELETE FROM voice_approvals")
                    dst.execute("DELETE FROM voice_credentials")
                for table in ("native_voice_events","chat_voice_context"):
                    if not dst.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
                        continue
                    dst.execute(f"""UPDATE inbox SET state='IGNORED',payload=NULL,result='语音授权未随备份恢复'
                                   WHERE state='PENDING' AND seq IN (SELECT seq FROM {table})""")
                    dst.execute(f"""UPDATE queries SET state='CANCELLED',argument=NULL WHERE state IN ('RUNNING','PENDING')
                                   AND id IN (SELECT seq FROM {table})""")
                    dst.execute(f"""UPDATE outbox SET body='',state=CASE
                                   WHEN state IN ('PENDING','RETRY_WAIT') THEN 'CANCELLED'
                                   WHEN state='SENDING' THEN 'UNKNOWN' ELSE state END
                                   WHERE biz IN (SELECT i.event_id FROM inbox i JOIN {table} v ON v.seq=i.seq)""")
                    dst.execute(f"DELETE FROM {table}")
                if dst.execute("SELECT 1 FROM sqlite_master WHERE name='member_notice_approvals'").fetchone():
                    dst.execute("DELETE FROM member_notice_approvals")
                    dst.execute("DELETE FROM native_rosters")
                if dst.execute("SELECT 1 FROM sqlite_master WHERE name='live_notices'").fetchone():
                    dst.execute("DELETE FROM live_notices")
                if dst.execute("SELECT 1 FROM sqlite_master WHERE name='local_turns'").fetchone():
                    dst.execute("DELETE FROM local_turns")
                if dst.execute("SELECT 1 FROM sqlite_master WHERE name='chat_models'").fetchone():
                    dst.execute("DELETE FROM chat_models")
                    dst.execute("DELETE FROM chat_requests")
                    dst.execute("DELETE FROM directed_groups")
                dst.execute("DELETE FROM tokens")
                dst.execute("UPDATE inbox SET payload=NULL WHERE state!='PENDING'")
                dst.execute("UPDATE outbox SET body='' WHERE state IN ('ACKNOWLEDGED','CANCELLED','EXPIRED')")
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("备份校验失败")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    with target.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def restore(source, target):
    if Path(target).exists():
        raise ValueError("恢复目标必须是新文件，避免覆盖运行中的实例")
    if not Path(source).is_file():
        raise ValueError("备份不存在")
    with closing_db(source) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] not in (1,2,3) or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("备份版本或完整性校验失败")
    backup(source, target)
    initialize(target)
    with closing_db(target) as db, transaction(db):
        db.execute("UPDATE groups SET paused=1")
        db.execute("UPDATE account SET state='SUSPENDED'")
        db.execute("UPDATE outbox SET state='UNKNOWN',detail='备份时间点后的投递情况待核对' WHERE state IN ('PENDING','SENDING','RETRY_WAIT')")
        db.execute("UPDATE inbox SET state='EXPIRED',payload=NULL WHERE state='PENDING' AND arrived<?", (time.time()-86400,))
        audit(db, "restore", None, "隔离恢复", "账号与绑定暂停，等待核对")

