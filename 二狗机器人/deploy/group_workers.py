"""Take over one migrated group's directed text replies, then resume its workers."""
import argparse
import http.client
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
from urllib.parse import quote

from ergou import agent_wechat as wx, bridge
from ergou.db import audit, closing_db, transaction


DATABASE = Path("/var/lib/ergou/ergou.sqlite")
PRIVATE = Path("/var/lib/ergou/wechat")
SLOT = "ergou-listener"


def current(db, slot):
    return db.execute("""SELECT l.grp,l.account,g.binding,l.server_id FROM agent_wechat_links l
        JOIN groups g ON g.id=l.grp AND g.account=l.account JOIN account a ON a.id=g.account
        JOIN directed_groups d ON d.grp=g.id AND d.account=g.account AND d.binding=g.binding
        JOIN node_grants n ON n.grp=g.id AND n.account=g.account
        LEFT JOIN group_profile p ON p.grp=g.id
        WHERE l.slot=? AND g.paused=0 AND json_extract(g.config,'$.enabled')=1
        AND a.state!='SUSPENDED' AND NOT COALESCE(p.detached,0)""", (slot,)).fetchone()


def candidate(db, group):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_handoff'").fetchone():
        raise ValueError("未找到功能数据迁移时登记的点名授权")
    rows = db.execute("""SELECT h.grp,h.account,h.binding FROM migration_handoff h
        JOIN groups g ON g.id=h.grp AND g.account=h.account AND g.binding=h.binding
        JOIN account a ON a.id=g.account LEFT JOIN group_profile p ON p.grp=g.id
        WHERE (? IS NULL OR h.grp=?) AND g.paused=1 AND a.mode='adapter' AND a.state='SUSPENDED'
        AND json_extract(g.config,'$.enabled')=1 AND NOT COALESCE(p.detached,0) LIMIT 2""",
                      (group,group)).fetchall()
    if len(rows) != 1:
        raise ValueError("请选择一个迁移时已获点名授权的群；多个候选群请使用 --group-id")
    return dict(rows[0])


def take_over(db, client, secret, group=None):
    existing = current(db, client.slot)
    target = dict(existing) if existing else candidate(db, group)
    if (group is not None and target["grp"] != group
            or not wx.valid_id(target["grp"]) or not target["grp"].endswith("@chatroom")):
        raise ValueError("目标群与当前绑定不一致")
    server = client.get("/v1/status").get("serverId")
    resolved = target["grp"]
    if (not wx.valid_id(server) or client.identity() != target["account"]
            or not client.member(resolved, target["account"])):
        raise ValueError("扫码账号、群或微信服务身份未通过核对")
    if not existing:
        # This first page carries the account-wide event boundary independently
        # of list pagination. The event log's nextCursor is only a page offset.
        path = client.base + "/groups/" + quote(resolved,safe="") + "/members?limit=1"
        cursor = client.get(path).get("asOfEventCursor")
        if not wx.number(cursor) or int(cursor) >= 2**63:
            raise ValueError("插件未返回有效的当前事件游标，请重试接管")
    if client.get("/v1/status").get("serverId") != server:
        raise ValueError("核对期间微信服务身份已变化")
    with transaction(db):
        active = current(db, client.slot)
        if active:
            if not db.execute("SELECT 1 FROM nodes WHERE account=? AND secret_hash=?",
                              (active["account"],bridge.digest(secret))).fetchone():
                raise ValueError("运行账号的节点凭据与当前登记不一致")
            if (active["grp"],active["account"],active["binding"],active["server_id"]) == (
                    resolved,target["account"],target["binding"],server):
                return False
            raise ValueError("当前群或服务绑定已变更")
        if existing or candidate(db, resolved) != target:
            raise ValueError("接管期间绑定或授权已变化")
        account = target["account"]
        if db.execute("SELECT 1 FROM agent_wechat_links WHERE account=? OR slot=?", (account,client.slot)).fetchone():
            raise ValueError("当前槽位或账号已有其他登记")
        if db.execute("""SELECT 1 FROM nodes WHERE account=? UNION ALL
            SELECT 1 FROM inbox WHERE grp=? AND state='PENDING' UNION ALL
            SELECT 1 FROM outbox WHERE grp=? AND state IN ('PENDING','RETRY_WAIT','SENDING') UNION ALL
            SELECT 1 FROM directed_groups WHERE grp=? UNION ALL SELECT 1 FROM voice_approvals WHERE grp=? UNION ALL
            SELECT 1 FROM member_notice_approvals WHERE grp=? UNION ALL SELECT 1 FROM live_notices WHERE grp=?
            LIMIT 1""", (account,) + (resolved,)*6).fetchone():
            raise ValueError("迁移目标仍有节点、旧任务或外发授权，请核对迁移副本")
        bridge.enroll_in_transaction(db,account,resolved,secret,listen_only=True)
        db.execute("INSERT INTO agent_wechat_links VALUES(?,?,?,?,?)", (client.slot,account,resolved,server,cursor))
        db.execute("INSERT INTO directed_groups VALUES(?,?,?,?)",(resolved,account,target["binding"],time.time()))
        db.execute("UPDATE account SET state='WAITING_LOGIN' WHERE id=?", (account,))
        db.execute("UPDATE groups SET paused=0 WHERE id=?", (resolved,))
        db.execute("DELETE FROM migration_handoff WHERE grp=?", (resolved,))
        audit(db,"local-cli",resolved,"服务器接管点名文字回复","已核实扫码账号与群成员关系，从当前游标开始")
    return True


def node_secret(private, create):
    target = private / "ergou-node-secret"
    if create and not target.exists():
        with tempfile.NamedTemporaryFile(dir=private,delete=False) as out:
            temporary = out.name
            try:
                out.write(secrets.token_urlsafe(48).encode("ascii"))
                out.flush()
                os.fsync(out.fileno())
            except BaseException:
                out.close()
                os.unlink(temporary)
                raise
        try:
            os.link(temporary,target)
        except FileExistsError:
            pass
        finally:
            os.unlink(temporary)
    return target.read_text(encoding="ascii").strip()


class DirectedListener(wx.Listener):
    def __init__(self, db, client, secret, private, binding):
        super().__init__(db, client, secret, private)
        self.binding = binding

    def linked(self):
        active = current(self.db,self.client.slot)
        return bool(active and (active["grp"],active["account"],active["binding"],active["server_id"])
                    == (self.group,self.account,self.binding,self.server))

    def consume(self, event):
        if not self.linked():
            raise wx.LinkRemoved()
        return super().consume(event)

    def heartbeat(self, state):
        if not self.linked():
            raise wx.LinkRemoved()
        return super().heartbeat(state)


def run(db, action, private, group=None):
    active = current(db,SLOT)
    stream=db.execute("SELECT * FROM binding_streams WHERE slot=?", (SLOT,)).fetchone()
    if action != "take-over" and not active and not stream:
        return "当前没有可恢复的服务器点名授权"
    read = (private/"ergou-read-token").read_text(encoding="ascii").strip()
    if not read:
        raise ValueError("缺少微信读取令牌")
    client = wx.Client(6174,SLOT,read)
    if action in ("take-over","replies"):
        sender = (private/"ergou-send-token").read_text(encoding="ascii").strip()
        if not sender:
            raise ValueError("缺少微信发送令牌")
    secret = node_secret(private, action=="take-over" and not active)
    if action == "take-over":
        changed = take_over(db,client,secret,group)
        return "已接管点名文字回复，请启动监听与回复服务" if changed else "当前群已接管，既有游标与授权保留"
    from . import group_stream
    if not stream:
        db.execute("""INSERT OR IGNORE INTO binding_streams SELECT slot,account,server_id,cursor
                      FROM agent_wechat_links WHERE slot=? AND grp=?""",(SLOT,active["grp"]))
        stream=db.execute("SELECT * FROM binding_streams WHERE slot=?",(SLOT,)).fetchone()
    if action == "listen":
        group_stream.Stream(db,client,secret,private,stream).run()
    else:
        group_stream.replies(db,client,secret,sender,stream)
    return "工作进程已停止"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,default=DATABASE)
    parser.add_argument("--private-dir",type=Path,default=PRIVATE)
    sub = parser.add_subparsers(dest="action",required=True)
    transfer = sub.add_parser("take-over",help="旧实例收发工作进程已停止后，首次接管指定群")
    transfer.add_argument("--group-id",help="从迁移时已获点名授权的群中选择")
    admins=sub.add_parser("binding-admin",help="按稳定微信 ID 管理独立的跨群绑定名单")
    admins.add_argument("operation",choices=("grant","revoke"))
    admins.add_argument("member")
    sub.add_parser("listen")
    sub.add_parser("replies")
    args = parser.parse_args()
    try:
        if not args.db.is_file():
            raise ValueError("未找到迁移数据库")
        with closing_db(args.db) as db:
            if args.action=="binding-admin":
                stream=db.execute("SELECT account FROM binding_streams WHERE slot=?", (SLOT,)).fetchone()
                if not stream or not wx.valid_id(args.member) or args.member==stream["account"]:
                    raise ValueError("需要已登记账号和独立微信用户的稳定 ID")
                with transaction(db):
                    if args.operation=="grant":
                        db.execute("INSERT OR IGNORE INTO binding_admins VALUES(?,?)",(stream["account"],args.member))
                    else:
                        db.execute("DELETE FROM binding_admins WHERE account=? AND member=?",(stream["account"],args.member))
                    audit(db,"local-cli",None,"绑定管理员名单变更",args.operation+" "+args.member)
                print("绑定权限名单已更新")
                return
            print(run(db,args.action,args.private_dir,getattr(args,"group_id",None)))
    except (OSError,ValueError,RuntimeError,sqlite3.Error,http.client.HTTPException) as exc:
        parser.exit(1,f"微信工作进程未启动：{exc}\n")


if __name__ == "__main__":
    main()
