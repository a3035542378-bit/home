"""Metrics for a completed Beijing calendar week; interval ends are exclusive."""
from datetime import datetime
import json

from .db import BJ

WEEK = 7 * 86400


def missing_intervals(db, group, start, end):
    first = int(start // 60)
    after = int(end // 60)
    rows = db.execute("""
        SELECT minute FROM observation
        WHERE grp=? AND minute>=? AND minute<? ORDER BY minute
    """, (group, first, after))
    gaps = []
    cursor = first
    for (minute,) in rows:
        if minute > cursor:
            gaps.append((cursor, minute))
        cursor = minute + 1
    if cursor < after:
        gaps.append((cursor, after))
    return gaps


def weekly(db, group, end):
    start = end - WEEK
    params = (group, start, end)
    messages = db.execute("""
        SELECT COUNT(*) 消息数,COUNT(DISTINCT member) 已观测成员 FROM inbox
        WHERE grp=? AND arrived>=? AND arrived<? AND kind='message' AND message_type='text'
          AND state IN ('DONE','CHAT','REJECTED','RATE_LIMITED')
    """, params).fetchone()
    players = db.execute("""
        SELECT COUNT(*) 参与人次,COUNT(DISTINCT p.member) 参与人数
        FROM participation p JOIN games g ON g.id=p.game
        WHERE g.grp=? AND p.joined>=? AND p.joined<?
    """, params).fetchone()
    games = db.execute("""
        SELECT COUNT(*) FILTER (WHERE state='FINISHED') 完成局数,
               COUNT(*) FILTER (WHERE state='CANCELLED') 取消局数
        FROM games WHERE grp=? AND ended>=? AND ended<?
    """, params).fetchone()
    avg_players = db.execute("""
        SELECT AVG((SELECT COUNT(*) FROM participation p WHERE p.game=g.id AND p.joined<:end))
        FROM games g WHERE g.grp=:grp AND g.started>=:start AND g.started<:end
    """,
        {"grp":group, "start":start, "end":end}).fetchone()[0]
    gaps = missing_intervals(db, group, start, end)
    missed = sum(right - left for left, right in gaps)
    return dict(周期=datetime.fromtimestamp(start,BJ).date().isoformat(),
                **dict(messages), **dict(players), **dict(games),
                当周开局平均参与人数=round(avg_players,2) if avg_players is not None else None,
                在线采样分钟=WEEK//60-missed, 未覆盖分钟=missed, 缺口段数=len(gaps),
                最长缺口分钟=max((b-a for a,b in gaps),default=0), 覆盖="按在线分钟采样，仅统计实际收到文本")


def archive(db, group):
    fields = ("周期","消息数","已观测成员","参与人次","参与人数","完成局数","取消局数",
              "当周开局平均参与人数","在线采样分钟","未覆盖分钟","缺口段数","最长缺口分钟","覆盖")
    rows = db.execute("SELECT report FROM weekly WHERE grp=? ORDER BY start DESC LIMIT 200", (group,))
    return [{key:report.get(key) for key in fields} for row in rows for report in json.loads(row[0])]
