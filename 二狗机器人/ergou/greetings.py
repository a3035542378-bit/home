from datetime import datetime
from .db import BJ


def welcome(cfg,member,group,stamp):
    values={"成员":member,"nickname":member,"群":group,"时间":datetime.fromtimestamp(stamp,BJ).strftime("%H:%M"),
            "群规":cfg["rules"][:120]}
    message=cfg["welcome"].format_map(values)
    link=cfg.get("rules_url")
    return message+"\n群规："+link if link else message
