import argparse
import getpass
import json
import logging
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import admin, jobs, models, queries
from .db import BJ, backup, closing_db, demo, initialize, restore
from .engine import receive,step
from .web import server

LOG=logging.getLogger("ergou")


def worker(path,stop,role):
    with closing_db(path) as db:
        last_tick=last_clean=0
        chat=models.ChatWorker() if role=="chat" else None
        while not stop.is_set():
            try:
                if role=="chat":
                    busy=chat.work(db)
                elif role=="query":
                    busy=queries.work(db)
                elif role=="bulletin":
                    from . import bulletins
                    busy=bulletins.work(db)
                else:
                    busy=step(db)
                    sent=jobs.send_one(db,jobs.Simulation())
                    busy=busy or sent
                    now=time.time()
                    if now-last_tick>=1:
                        jobs.tick(db,now)
                        last_tick=now
                    if now-last_clean>=60:
                        jobs.cleanup(db,now)
                        last_clean=now
                        day=datetime.fromtimestamp(now,BJ)
                        if (day.hour,day.minute)>=(3,30):
                            folder=Path(path).parent/"backups"
                            folder.mkdir(exist_ok=True)
                            target=folder/f"{Path(path).stem}-{day:%Y%m%d}.sqlite"
                            if not target.exists():
                                backup(path,target)
                                for old in sorted(folder.glob(Path(path).stem+"-????????.sqlite"))[:-7]:
                                    old.unlink()
                if not busy:
                    stop.wait(.15)
            except (sqlite3.Error,OSError,ValueError) as exc:
                LOG.error("worker=%s error=%s",role,type(exc).__name__)
                stop.wait(1)


def main():
    p=argparse.ArgumentParser(description="微信二狗群聊工作台")
    p.add_argument("--db",default="data/ergou.sqlite")
    subs=p.add_subparsers(dest="cmd",required=True)
    init=subs.add_parser("init");init.add_argument("--demo",action="store_true")
    u=subs.add_parser("user");u.add_argument("name");u.add_argument("--role",choices=admin.ROLES,default="系统管理员");u.add_argument("--group",action="append",default=[])
    serve=subs.add_parser("serve");serve.add_argument("--port",type=int,default=8765)
    serve.add_argument("--duration",type=int,default=0,help="限时运行的秒数；默认持续运行")
    msg=subs.add_parser("say");msg.add_argument("text");msg.add_argument("--group",default="demo-group");msg.add_argument("--member",default="operator");msg.add_argument("--id")
    b=subs.add_parser("backup");b.add_argument("target")
    r=subs.add_parser("restore");r.add_argument("source")
    subs.add_parser("status")
    approve=subs.add_parser("confirm-notice",help="核对并确认一条真实微信定时文字")
    approve.add_argument("number",type=int)
    subs.add_parser("confirm-member-notice",help="按群和通知类型确认一项成员通知")
    subs.add_parser("confirm-voice",help="核对微信群、百度识别范围及语音回复授权")
    subs.add_parser("first-operator",help="为已绑定的微信测试群设置首个运营账号")
    bootstrap=subs.add_parser("bootstrap-admin",help="首次创建系统管理员 admin，已有账号保留原密码")
    bootstrap.add_argument("--password-stdin",action="store_true",help="从标准输入读取一行初始密码")
    plugin=subs.add_parser("plugin");plugin.add_argument("manifest")
    node=subs.add_parser("node");node.add_argument("account");node.add_argument("group")
    node.add_argument("--listen-only",action="store_true",help="登记只接收群消息的节点")
    args=p.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(message)s")
    if args.cmd=="restore":
        restore(args.source,args.db)
        print("恢复到隔离数据库；全部群已暂停")
        return
    if args.cmd=="init":
        initialize(args.db)
        if args.demo:
            demo(args.db)
        print("数据库已初始化："+args.db)
        return
    if not Path(args.db).is_file():
        p.error("请先执行 init")
    if args.cmd=="serve":
        if args.duration<0:p.error("运行时长不能为负数")
        initialize(args.db)
        httpd=server(args.db,args.port)
        stop=threading.Event()
        threads=[threading.Thread(target=worker,args=(args.db,stop,role),daemon=True) for role in ("business","query","chat","bulletin")]
        for thread in threads:thread.start()
        timer=threading.Timer(args.duration,httpd.shutdown) if args.duration else None
        if timer:timer.start()
        print(f"本机管理后台 http://127.0.0.1:{httpd.server_port}",flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if timer:timer.cancel()
            stop.set()
            httpd.server_close()
            for thread in threads:thread.join(9)
        return
    with closing_db(args.db) as db:
        if args.cmd=="bootstrap-admin":
            from .admin_accounts import bootstrap
            password=sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("admin 初始密码：")
            print("已创建 admin 系统管理员" if bootstrap(db,password) else "admin 系统管理员已存在")
            return
        if args.cmd=="confirm-voice":
            from .voice_policy import confirm_one
            confirm_one(db)
            return
        if args.cmd=="confirm-member-notice":
            from .member_notices import confirm_one
            confirm_one(db)
            return
        if args.cmd=="confirm-notice":
            from .live_notice import confirm_interactively
            confirm_interactively(db,args.number)
            return
        if args.cmd=="first-operator":
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                print("请使用已有账号登录运营后台。")
                return
            link=db.execute("SELECT grp FROM agent_wechat_links WHERE slot='ergou-listener'").fetchone()
            if not link:
                p.error("请先绑定微信接入账号")
            print("首次登录，请为运营账号 operator 设置密码。")
            password=getpass.getpass("密码（至少 12 字符）：")
            if password!=getpass.getpass("再次输入："):
                p.error("两次密码不一致")
            admin.user(db,"operator",password,"运营管理员",[link[0]])
            print("运营账号 operator 已就绪。")
        elif args.cmd=="user":
            password=getpass.getpass("管理员密码（至少 12 字符）：")
            if password!=getpass.getpass("再次输入："):
                p.error("两次密码不一致")
            admin.user(db,args.name,password,args.role,args.group)
            print("已创建用户")
        elif args.cmd=="say":
            seq=receive(db,"sim-account",args.group,args.member,args.id or uuid.uuid4().hex,{"text":args.text})
            while step(db):pass
            while queries.work(db):pass
            chat=models.ChatWorker()
            while chat.work(db):pass
            while jobs.send_one(db,jobs.Simulation()):pass
            row=db.execute("SELECT i.state,o.body FROM inbox i LEFT JOIN outbox o ON o.biz=i.event_id WHERE seq=?",(seq,)).fetchone()
            print(row["body"] or row["state"])
        elif args.cmd=="backup":
            print("SHA256",backup(args.db,args.target))
        elif args.cmd=="node":
            from .bridge import enroll
            enroll(db,args.account,args.group,getpass.getpass("节点密钥（至少 32 字符）："),listen_only=args.listen_only)
            print("接入节点已登记，等待账号身份与群成员关系验证")
        elif args.cmd=="plugin":
            from .plugins import install
            install(db,args.manifest)
            print("插件已激活，现有会话保留原规则")
        elif args.cmd=="status":
            for row in db.execute("SELECT id,mode,state FROM account"):
                print(*row)


if __name__=="__main__":
    main()

