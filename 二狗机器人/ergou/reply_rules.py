"""Group-scoped, ordered keyword replies for addressed messages."""
import json
import math
import unicodedata
from urllib.parse import urlsplit

from .db import audit, dump, transaction


def permit(user, group):
    from .admin import permitted
    permitted(user, group, True)
    if user["role"] not in ("运营管理员", "系统管理员"):
        raise PermissionError("FORBIDDEN 仅运营管理员或系统管理员可编辑自定义回复")


def settings(db, user, group):
    permit(user, group)
    row = db.execute("SELECT version,rules FROM reply_rule_sets WHERE grp=?", (group,)).fetchone()
    return {"version": row["version"], "rules": json.loads(row["rules"])} if row else {"version": 0, "rules": []}


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def validate_rules(rules):
    if not isinstance(rules, list) or len(rules) > 64:
        raise ValueError("每群最多可设置 64 条自定义回复")
    validated = []
    for index, rule in enumerate(rules, 1):
        if not isinstance(rule, dict):
            raise ValueError(f"第 {index} 条规则格式不正确")
        keyword, mode = rule.get("keyword"), rule.get("mode")
        threshold = rule.get("threshold", 0.8)
        kind, content = rule.get("kind"), rule.get("content")
        if not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 80:
            raise ValueError(f"第 {index} 条请输入 1–80 字的触发词")
        if mode not in ("exact", "contains", "similar"):
            raise ValueError(f"第 {index} 条请选择匹配方式")
        if type(threshold) not in (int, float) or not 0.1 <= threshold <= 1:
            raise ValueError(f"第 {index} 条相似度阈值应为 0.1–1")
        if kind not in ("text", "link", "image") or not isinstance(content, str) or not 1 <= len(content.strip()) <= 1200:
            raise ValueError(f"第 {index} 条请选择类型并填写 1–1200 字的回复")
        content = content.strip()
        if kind != "text":
            try:
                url = urlsplit(content)
                valid = url.scheme in ("http", "https") and url.hostname and url.username is None
                valid = valid and not any(c.isspace() or ord(c) < 32 or c == "\\" for c in content)
                if url.port is not None:
                    valid = valid and url.port > 0
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"第 {index} 条请输入完整的 HTTP 或 HTTPS 链接")
            if kind == "image" and url.scheme != "https":
                raise ValueError(f"第 {index} 条图片需要 HTTPS 链接")
        validated.append(dict(keyword=keyword.strip(), mode=mode, threshold=threshold, kind=kind, content=content))
    return validated


def configure(db, user, group, data):
    permit(user, group)
    version = data.get("version")
    if type(version) is not int or version < 0:
        raise ValueError("规则版本无效")
    rules = validate_rules(data.get("rules"))
    with transaction(db):
        row = db.execute("SELECT version FROM reply_rule_sets WHERE grp=?", (group,)).fetchone()
        if (row[0] if row else 0) != version:
            raise ValueError("CONFLICT 本群回复规则已更新，请重新载入后再保存")
        db.execute("INSERT OR REPLACE INTO reply_rule_sets VALUES(?,?,?)", (group, version + 1, dump(rules)))
        audit(db, user["name"], group, "保存自定义回复", f"v{version + 1}，共 {len(rules)} 条")
    return {"version": version + 1, "rules": rules}


def matches(text, rule):
    keyword = normalize(rule["keyword"])
    if rule["mode"] == "contains":
        return keyword in text
    if rule["mode"] == "exact":
        return keyword == text
    # A substitution costs one edit, including a Chinese-character typo.
    # Trim impossible candidates before calculating the edit distance.
    tolerance = math.floor(max(len(text), len(keyword)) * (1 - rule["threshold"]) + 1e-9)
    if abs(len(text) - len(keyword)) > tolerance:
        return False
    if tolerance == 0:
        return keyword == text
    previous = list(range(len(keyword) + 1))
    for pos, char in enumerate(text, 1):
        current = [pos]
        for column, other in enumerate(keyword, 1):
            current.append(min(previous[column] + 1, current[-1] + 1,
                               previous[column - 1] + (char != other)))
        if min(current) > tolerance:
            return False
        previous = current
    return previous[-1] <= tolerance


def matching_rule(db, group, cmd):
    row = db.execute("SELECT rules FROM reply_rule_sets WHERE grp=?", (group,)).fetchone()
    if not row:
        return None
    text = normalize(cmd)
    if text:
        return next((rule for rule in json.loads(row[0]) if matches(text, rule)), None)


def match(db, event, cmd):
    rule = matching_rule(db, event["grp"], cmd)
    if rule is None:
        return None
    db.execute("INSERT OR IGNORE INTO reply_rule_hits VALUES(?,?)", (event["seq"], rule["keyword"]))
    if rule["kind"] == "image" and urlsplit(rule["content"]).scheme == "https":
        db.execute("""INSERT OR IGNORE INTO simulation_reply_images(seq,url)
                      SELECT i.seq,? FROM inbox i JOIN account a ON a.id=i.account
                      WHERE i.seq=? AND i.grp=? AND a.mode='simulation'""",
                   (rule["content"], event["seq"], event["grp"]))
    return ("图片：" if rule["kind"] == "image" else "") + rule["content"]


def simulation_media(db, group, seq):
    row = db.execute("""SELECT m.url FROM simulation_reply_images m JOIN inbox i ON i.seq=m.seq
                        JOIN account a ON a.id=i.account JOIN outbox o ON o.biz=i.event_id
                        WHERE i.grp=? AND i.seq=? AND a.mode='simulation'""", (group, seq)).fetchone()
    return {"type": "image", "url": row[0]} if row else None
