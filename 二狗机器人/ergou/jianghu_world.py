"""江湖天下命令分发；使用第一章相同的群权限、事务与事件身份。"""

from . import jianghu_adventure as adventure
from . import jianghu_trade as trade
from . import jianghu_society as society
from . import jianghu_contests as contests

COMMANDS = (
    adventure.PERSONAL
    | adventure.GUIDES.keys()
    | trade.EXACT
    | society.EXACT
    | contests.ACTIONS
    | {"第二章", "第三章"}
)
PATTERNS = (
    adventure.LEARN,
    trade.GOODS,
    trade.PAGE,
    trade.RESPEC,
    society.TARGET,
    society.ANSWER,
)


def matches(cmd):
    return cmd in COMMANDS or any(pattern.fullmatch(cmd) for pattern in PATTERNS)


def handle(db, key, p, event, cmd, prefix, rng):
    if cmd == "江湖钱庄":
        from . import roles

        text = adventure.guide(cmd, prefix)
        if roles.LEVEL[roles.role(db, event["account"], key[0], key[1])] >= 4:
            text += "\n【赐金条 @群友 1】给本群玩家发一根金条"
        return text
    if cmd in adventure.GUIDES:
        return adventure.guide(cmd, prefix)
    if p["completed_at"] is None:
        return f"🏮 先办完第一章的镖信，再闯荡江湖天下。\n{prefix}面板"
    db.execute(
        "INSERT OR IGNORE INTO jh_world(grp,member,born) VALUES(?,?,?)",
        (*key, p["first_win_at"]),
    )
    w = adventure.world(db, key)
    if (
        cmd in trade.EXACT
        or trade.GOODS.fullmatch(cmd)
        or trade.RESPEC.fullmatch(cmd)
        or trade.PAGE.fullmatch(cmd)
    ):
        return trade.handle(db, key, p, w, event, cmd, prefix, rng)
    if (
        cmd in society.EXACT
        or society.TARGET.fullmatch(cmd)
        or society.ANSWER.fullmatch(cmd)
    ):
        return society.handle(db, key, p, w, event, cmd, prefix, rng)
    if cmd in contests.ACTIONS:
        return contests.handle(db, key, p, w, event, cmd, prefix, rng)
    return adventure.handle(db, key, p, w, event, cmd, prefix, rng)
