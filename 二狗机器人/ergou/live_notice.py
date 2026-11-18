"""Local confirmation for one exact, scheduled WeChat text."""
import time
from datetime import datetime

from .db import BJ, audit, transaction


def preview(db, number):
    row=db.execute("""SELECT s.*,g.account,g.binding,p.since,l.server_id FROM schedules s
                    JOIN groups g ON g.id=s.grp JOIN directed_groups p ON p.grp=g.id AND p.account=g.account
                    AND p.binding=g.binding JOIN agent_wechat_links l ON l.grp=s.grp AND l.account=g.account
                    WHERE s.id=? AND s.period='一次' AND s.enabled=1 AND g.paused=0
                    AND NOT EXISTS(SELECT 1 FROM bulletin_types t WHERE t.schedule=s.id)""",(number,)).fetchone()
    if not row or row["due"]<=time.time():
        raise ValueError("仅可确认已绑定群内尚未到期的一次性固定文字通知")
    return dict(row)


def approve(db, snapshot):
    with transaction(db):
        row=preview(db,snapshot["id"])
        if row!=snapshot:
            raise ValueError("CONFLICT 通知内容、时间或绑定已经变化，请重新核对")
        key=f"schedule/{row['id']}/{row['due']}"
        db.execute("""INSERT OR REPLACE INTO live_notices VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (row["id"],row["grp"],row["account"],row["binding"],row["since"],row["server_id"],
                    row["version"],row["due"],row["body"],key,time.time()))
        audit(db,"local-cli",row["grp"],"确认单次微信通知",f"#{row['id']} v{row['version']}")
    return key


def confirm_interactively(db,number):
    row=preview(db,number)
    due=datetime.fromtimestamp(row["due"],BJ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"微信群 {row['grp']}\n发送时间 {due}（北京时间）\n通知 #{number} v{row['version']}\n正文\n{row['body']}")
    print("错过后十分钟内补发" if row["catchup"] else "错过执行窗口后跳过")
    if input("要发送这条通知，请输入「确认发送」：").strip()=="确认发送":
        approve(db,row)
        print("已确认。修改正文、时间或绑定会使本次确认失效。")
    else:
        print("已取消。")


def matches(db, group, key, body):
    return db.execute("""SELECT 1 FROM valid_live_notices WHERE grp=? AND biz=? AND body=?""",
                      (group,key,body)).fetchone() is not None
