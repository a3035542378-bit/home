"""On-demand roster evidence for administrative grants."""
import json
import time

from .agent_wechat import ListenerBusy,listener_lock,listener_lock_path
from .db import transaction,dump
from .native_roster import MIN_REFRESH

SCHEMA="""
CREATE TABLE IF NOT EXISTS asset_roster_requests(
 grp TEXT PRIMARY KEY REFERENCES groups, requested REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_rosters(
 grp TEXT PRIMARY KEY REFERENCES groups, account TEXT NOT NULL, binding INTEGER NOT NULL,
 slot TEXT NOT NULL, server TEXT NOT NULL, session TEXT NOT NULL, operation TEXT NOT NULL,
 observed REAL NOT NULL, members TEXT NOT NULL
);
"""


def lease_name(slot,group):
    return dump(["asset-roster",slot,group])


def verified(db,group):
    now=time.time()
    row=db.execute("""SELECT r.* FROM asset_rosters r JOIN groups g ON g.id=r.grp AND g.account=r.account
        AND g.binding=r.binding JOIN agent_wechat_links l ON l.grp=g.id AND l.slot=r.slot
        AND l.account=g.account AND l.server_id=r.server JOIN account a ON a.id=g.account
        JOIN nodes n ON n.account=a.id JOIN node_grants ng ON ng.grp=g.id AND ng.account=a.id
        LEFT JOIN group_profile f ON f.grp=g.id
        JOIN membership m ON m.grp=g.id AND m.account=a.id
        WHERE r.grp=? AND NOT coalesce(f.detached,0) AND json_extract(g.config,'$.enabled')=1 AND a.state='LISTENING' AND g.paused=0 AND n.last_seen>? AND n.last_seen<=?
        AND r.observed>? AND r.observed<=?""",(group,now-30,now,now-MIN_REFRESH,now)).fetchone()
    if row:
        try:
            with listener_lock(db,lease_name(row["slot"],group)):
                return None
        except ListenerBusy:
            with listener_lock_path(db,lease_name(row["slot"],group)).open("rb") as handle:
                handle.seek(1)
                if handle.read(33)==row["session"].encode("ascii"):
                    return json.loads(row["members"])
    return None


def candidates(db,group,simulation):
    if simulation:
        return {r[0]:r[0] for r in db.execute("SELECT member FROM simulation_members WHERE grp=? ORDER BY member",(group,))}
    with transaction(db):
        members=verified(db,group)
        if members is None:
            db.execute("INSERT INTO asset_roster_requests VALUES(?,?) ON CONFLICT(grp) DO UPDATE SET requested=excluded.requested",
                       (group,time.time()))
        return members


def require_member(db,group,member):
    mode=db.execute("SELECT a.mode FROM groups g JOIN account a ON a.id=g.account WHERE g.id=?",(group,)).fetchone()
    if mode and mode[0]=="simulation":
        if db.execute("SELECT 1 FROM simulation_members WHERE grp=? AND member=?",(group,member)).fetchone():
            return
    else:
        members=verified(db,group)
        if members is None:
            raise ValueError("名册无效，请刷新本群成员关系后重试")
        if member in members:
            return
    raise ValueError("目标成员不在当前群名册")
