"""Group-facing labels. Keep stable IDs in storage and permission checks."""
import http.client
import json
import logging
import time
from urllib.parse import quote


def refresh(db,client,group,members):
    binding=db.execute("SELECT binding FROM groups WHERE id=?",(group,)).fetchone()[0]
    now=time.time()
    for uid in dict.fromkeys(members):
        saved=db.execute("SELECT checked FROM asset_display_names WHERE grp=? AND binding=? AND member=?",
                         (group,binding,uid)).fetchone()
        if saved and saved[0]>now-300:
            continue
        path=client.base+"/groups/"+quote(group,safe="")+"/members/"+quote(uid,safe="")
        try:
            data=client.get(path)
        except (ValueError,OSError,http.client.HTTPException) as exc:
            logging.getLogger(__name__).warning("暂未取得榜单昵称 (%s)",type(exc).__name__)
            break
        m=data.get("member") or {}
        if (data.get("groupId"),data.get("username"),data.get("state"),m.get("username"))!=(group,uid,"present",uid):
            continue
        name=next((" ".join(v.split()) for v in (m.get("roomDisplayName"),m.get("nickname"))
                   if isinstance(v,str) and v.strip() and v.strip()!=uid),"")
        db.execute("INSERT OR REPLACE INTO asset_display_names VALUES(?,?,?,?,?)",(group,binding,uid,name[:80],now))


def labels(db,group):
    roster=db.execute("""SELECT r.members FROM native_rosters r JOIN groups g ON g.id=r.grp
                         AND g.binding=r.binding AND g.account=r.account WHERE r.grp=?""",(group,)).fetchone()
    names=json.loads(roster[0]) if roster else {}
    names.update(dict(db.execute("""SELECT n.member,n.name FROM asset_display_names n JOIN groups g ON g.id=n.grp
                                      AND g.binding=n.binding WHERE n.grp=? AND n.name!=''""",(group,))))
    def display(uid,suggested=None):
        for value in (names.get(uid),suggested):
            if isinstance(value,str) and value.strip() and value.strip()!=uid:
                return " ".join(value.split())[:80]
        return "一位群成员"
    return display
