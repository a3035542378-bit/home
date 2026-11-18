"""Prepare dynamic scheduled notices outside the scheduler's write transaction."""
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from . import queries
from .db import BJ, allowed, transaction


SCHEMA = """
CREATE TABLE IF NOT EXISTS bulletin_types(
 schedule INTEGER PRIMARY KEY REFERENCES schedules, kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bulletin_jobs(
 schedule INTEGER NOT NULL, due REAL NOT NULL, account TEXT NOT NULL, binding INTEGER NOT NULL,
 version INTEGER NOT NULL, expires REAL NOT NULL, lease REAL NOT NULL DEFAULT 0,
 PRIMARY KEY(schedule,due), FOREIGN KEY(schedule,due) REFERENCES runs(schedule,due)
);
"""
NEWS_HOST = "www.news.gov.hk"
NEWS_PATH = "/tc/common/html/topstories.rss.xml"


def parse(data):
    kind = data.get("kind", "text")
    body = data.get("body", "")
    if not isinstance(body, str):
        raise ValueError("通知内容格式无效")
    body = body.strip()
    if kind in ("weather", "weather_news"):
        if not re.fullmatch(r"[\w .·-]{1,64}", body):
            raise ValueError("天气通知需要有效城市名（最多 64 字）")
    elif kind == "news":
        body = "香港政府新闻网重点新闻"
    elif kind != "text" or not 0 < len(body) <= 1000:
        raise ValueError("请选择通知类型并填写活动内容")
    return kind, body


def set_kind(db, schedule, kind):
    if kind == "text":
        db.execute("DELETE FROM bulletin_types WHERE schedule=?", (schedule,))
    else:
        db.execute("INSERT OR REPLACE INTO bulletin_types VALUES(?,?)", (schedule, kind))


def stage(db, schedule, group, due, now):
    if not db.execute("SELECT 1 FROM bulletin_types WHERE schedule=?", (schedule["id"],)).fetchone():
        return False
    db.execute("INSERT OR IGNORE INTO bulletin_jobs(schedule,due,account,binding,version,expires) VALUES(?,?,?,?,?,?)",
               (schedule["id"], due, group["account"], group["binding"], schedule["version"], now+120))
    db.execute("UPDATE runs SET result='CONTENT_PENDING' WHERE schedule=? AND due=?", (schedule["id"], due))
    return True


def headlines(xml):
    if len(xml) > 524288 or b"<!DOCTYPE" in xml.upper():
        raise queries.ProviderError("新闻源数据异常")
    try:
        items = ET.fromstring(xml).findall("./channel/item")
    except ET.ParseError:
        raise queries.ProviderError("新闻源格式异常") from None
    lines = []
    for item in items:
        title = " ".join(item.findtext("title", "").split())[:100]
        link = item.findtext("link", "").strip()
        try:
            url = urlsplit(link)
        except ValueError:
            continue
        if title and url.scheme in ("http", "https") and url.netloc == NEWS_HOST and len(link) <= 600:
            lines.append(f"{title}\n{link}")
            if len(lines) == 3:
                break
    if not lines:
        raise queries.ProviderError("新闻源暂无可用标题")
    return "香港政府新闻网 · 重点新闻\n" + "\n".join(lines)


def public_get(url, limit, timeout, *, user_agent=None):
    if timeout <= 0:
        raise queries.ProviderError("外部请求超时")
    try:
        if os.name == "nt":
            # The Windows deployment uses the system TLS trust store (Schannel).
            curl = Path(os.environ["SystemRoot"]) / "System32" / "curl.exe"
            result = subprocess.run([str(curl), "--disable", "--fail", "--silent", "--proto", "=https",
                                     "--max-time", str(round(timeout, 3)), "--max-filesize", str(limit),
                                     *(["--user-agent",user_agent] if user_agent else []),url],
                                    capture_output=True, timeout=timeout+1, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            raw = result.stdout
        else:
            req=Request(url,headers={"User-Agent":user_agent}) if user_agent else url
            with urlopen(req, timeout=timeout) as response:
                raw = response.read(limit+1)
    except (OSError, subprocess.SubprocessError):
        raise queries.ProviderError("外部内容服务连接超时或失败") from None
    if len(raw)>limit:
        raise queries.ProviderError("供应商响应超限")
    return raw


def news():
    return headlines(public_get("https://"+NEWS_HOST+NEWS_PATH, 524288, 6))


def weather_request(url, params, deadline):
    if url not in (queries.GEO, queries.FORECAST):
        raise queries.ProviderError("天气服务地址无效")
    raw = public_get(url+"?"+urlencode(params), 131072, min(4,deadline-time.monotonic()))
    return json.loads(raw)


def eligibility(db, row, now):
    group = db.execute("SELECT * FROM groups WHERE id=?", (row["grp"],)).fetchone()
    config = json.loads(group["config"])
    version = db.execute("SELECT version FROM schedules WHERE id=?", (row["schedule"],)).fetchone()[0]
    hour = datetime.fromtimestamp(now, BJ).hour
    start, end = config["quiet_start"], config["quiet_end"]
    quiet = start <= hour < end if start <= end else hour >= start or hour < end
    if (group["paused"] or not config["enabled"] or quiet or version != row["version"] or now >= row["expires"]
            or group["account"] != row["account"] or group["binding"] != row["binding"]
            or db.execute("SELECT 1 FROM listener_nodes WHERE account=?", (group["account"],)).fetchone()):
        return None
    return group


def finish(db, row, result):
    db.execute("UPDATE runs SET result=? WHERE schedule=? AND due=?", (result, row["schedule"], row["due"]))
    db.execute("DELETE FROM bulletin_jobs WHERE schedule=? AND due=?", (row["schedule"], row["due"]))


def work(db):
    from .engine import queue
    now = time.time()
    with transaction(db):
        row = db.execute("""SELECT j.*,s.grp,s.body,t.kind FROM bulletin_jobs j JOIN schedules s ON s.id=j.schedule
                            LEFT JOIN bulletin_types t ON t.schedule=s.id WHERE j.lease<=? ORDER BY j.due,j.schedule LIMIT 1""",
                         (now,)).fetchone()
        if not row:
            return False
        if not eligibility(db, row, now) or not row["kind"]:
            finish(db, row, "SKIPPED")
            return True
        weather = None
        if row["kind"] in ("weather", "weather_news"):
            cached = db.execute("SELECT reply FROM weather_cache WHERE city=? AND at>?", (row["body"], now-600)).fetchone()
            if cached:
                weather = cached[0]
            else:
                day = datetime.fromtimestamp(now, BJ).date().isoformat()
                if not allowed(db, "外部查询/天气"+day, 500, 86400, now):
                    finish(db, row, "WEATHER_QUOTA")
                    return True
        lease = now+30
        db.execute("UPDATE bulletin_jobs SET lease=? WHERE schedule=? AND due=?", (lease, row["schedule"], row["due"]))
    try:
        parts = []
        if row["kind"] in ("weather", "weather_news"):
            parts.append(weather or queries.lookup("天气", row["body"], weather_request))
        if row["kind"] in ("news", "weather_news"):
            parts.append(news())
        result = "QUEUED"
    except queries.ProviderError as exc:
        result = "FAILED "+str(exc)[:80]
    with transaction(db):
        owner = db.execute("SELECT lease FROM bulletin_jobs WHERE schedule=? AND due=?", (row["schedule"], row["due"])).fetchone()
        if not owner or owner[0] != lease:
            return True
        now = time.time()
        group = eligibility(db, row, now)
        if not group:
            result = "SKIPPED"
        elif result == "QUEUED":
            if row["kind"] in ("weather", "weather_news") and weather is None:
                db.execute("INSERT OR REPLACE INTO weather_cache VALUES(?,?,?)", (row["body"], now, parts[0]))
            queue(db, group, f"schedule/{row['schedule']}/{row['due']}", "\n\n".join(parts), now, row["expires"]-now)
        finish(db, row, result)
    return True
