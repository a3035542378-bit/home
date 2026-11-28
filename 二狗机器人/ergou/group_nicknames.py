"""为已授权群列表补充机器人微信昵称。"""
import logging
from urllib.parse import quote

from .wechat_login import LoginPlugin


def attach(rows):
    for row in rows:
        row["nickname"] = None
    active = [row for row in rows if row["joined"] and not row["detached"]]
    if not active:
        return
    try:
        plugin = LoginPlugin()
        account = plugin.request("GET")
        bot = account.get("ownUsername")
        group = next((row["id"] for row in active if row["account"] == bot), None)
        if not group or not account.get("authenticated"):
            return
        entry = plugin.request("GET", "/groups/" + quote(group,safe="") + "/members/" + quote(bot,safe=""))
        if (entry.get("groupId"),entry.get("username"),entry.get("state")) != (group,bot,"present"):
            return
        nickname = (entry.get("member") or {}).get("nickname")
        if isinstance(nickname,str) and nickname.strip():
            for row in rows:
                if row["account"] == bot:
                    row["nickname"] = nickname.strip()
    except (ValueError, RuntimeError, OSError) as exc:
        logging.getLogger(__name__).info("群列表微信昵称暂不可用 (%s)",type(exc).__name__)
