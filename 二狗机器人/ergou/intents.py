"""Local command parsing for addressed text and speech transcripts."""
import hashlib
import re
from datetime import datetime

from .db import BJ
from .games import GAMES

SIGNS="白羊 金牛 双子 巨蟹 狮子 处女 天秤 天蝎 射手 摩羯 水瓶 双鱼".split()


def interpret(text,cfg):
    phrase=text.strip().rstrip("。！!？?").strip()
    if not phrase:
        return text
    request=re.sub(r"^(?:请问|麻烦|可以帮我|请帮我|帮我|我想|请)","",phrase)
    game=re.sub(r"^(?:玩一局|玩个|玩|开始玩|来一局|来个)","",request)
    if game in GAMES:
        return "开始 "+game
    match=re.fullmatch(r"(?:查询|查一下|查查|查|看看|看下)?(.{2,16}?)(?:今天|现在|今日)?的?天气(?:怎么样|如何|好吗)?",request)
    if match:
        city=match[1]
        if city in ("今天","今日","现在"):
            return "天气 "+cfg.get("city","")
        city=re.sub(r"^(?:今天|今日|现在)","",city)
        return "天气 "+city
    for sign in SIGNS:
        if re.fullmatch(sign+r"座(?:今日|今天)?(?:的)?运势(?:如何|怎么样)?",request):
            return "星座 "+sign+"座"
    if request in ("查天气","今天天气怎么样","查一下天气"):
        return "天气 "+cfg.get("city","")
    if request in ("查积分","看看我的积分","我的积分","我有多少积分"):
        return "积分"
    if request.startswith("查快递"):
        return "快递 "+request[3:].strip()
    return phrase


def horoscope(sign,stamp):
    name=sign.strip().removesuffix("座")
    if name not in SIGNS:
        return "告诉我你的星座，例如「二狗 双鱼座今日运势」。"
    day=datetime.fromtimestamp(stamp,BJ).strftime("%Y-%m-%d")
    tips=("和老朋友聊聊近况。","给手头最重要的小事留十分钟。","出门散步时留意一件新鲜事。",
          "把想说的感谢告诉对方。","遇到犹豫的事，先列出两个选择。","给自己的爱好留一点时间。")
    i=hashlib.sha256((day+name).encode()).digest()[0]%len(tips)
    return f"{name}座 · {day} · 今日趣味签：{tips[i]}（本地娱乐内容）"
