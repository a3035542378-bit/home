"""Local command parsing for addressed text and speech transcripts."""
import hashlib
import re
from datetime import datetime

from .db import BJ
from .games import GAMES

SIGNS="白羊 金牛 双子 巨蟹 狮子 处女 天秤 天蝎 射手 摩羯 水瓶 双鱼".split()

# 只映射完整指令。尤其是卖鱼和移动展品，不按聊天正文中的子串触发。
ITEM_WORDS = {
    "放入图鉴": ("放入图鉴", "收入图鉴", "收录图鉴", "录入图鉴", "存入图鉴", "加入图鉴", "收藏图鉴", "收藏到图鉴", "收进图鉴", "放进图鉴", "点亮图鉴"),
    "放入鱼塘": ("放入鱼塘", "收入鱼塘", "存入鱼塘", "放进鱼塘", "移入鱼塘", "放到鱼塘", "存塘"),
    "卖鱼": ("卖鱼", "出售", "出售鱼", "卖出", "卖掉"),
}
ITEM_ACTION = {word: action for action, words in ITEM_WORDS.items() for word in words}
ACTION = "(?:" + "|".join(map(re.escape, ITEM_ACTION)) + ")"
NUMBER = r"[1-9][0-9]{0,17}"
ITEM_AFTER = re.compile(rf"({ACTION})\s*(?:#|编号)?\s*({NUMBER})(?:号鱼|号)?")
ITEM_BEFORE = re.compile(rf"(?:把|将)?\s*(?:#|编号)?\s*({NUMBER})(?:号鱼|号)?\s*({ACTION})")
MOBILE_CHARS = str.maketrans("＃０１２３４５６７８９", "#0123456789")

ACTIONS = {
    "抛杆": "抛竿", "甩竿": "抛竿", "甩杆": "抛竿", "钓一竿": "抛竿",
    "鱼包扩容": "升级鱼包", "扩容鱼包": "升级鱼包", "鱼塘扩容": "升级鱼塘", "扩容鱼塘": "升级鱼塘",
    "鱼竿升级": "升级鱼竿", "鱼线升级": "升级鱼线", "鱼竿强化": "强化鱼竿",
    "抽签报名": "抽签 报名", "报名抽签": "抽签 报名", "退出抽签": "抽签 退出",
}

LOOKUPS = {
    "巨物预告": "巨物鱼讯", "巨物事件": "巨物鱼讯", "巨物鱼讯": "巨物鱼讯", "全图鉴": "全图鉴",
    "钓鱼信息": "钓鱼信息", "个人钓鱼信息": "钓鱼信息", "钓鱼档案": "钓鱼信息",
    "钓鱼状态": "钓鱼信息", "鱼币余额": "钓鱼信息",
    "鱼包": "鱼包", "背包": "鱼包", "鱼背包": "鱼包", "鱼塘": "鱼塘",
    "图鉴": "图鉴", "鱼类图鉴": "图鉴", "钓鱼图鉴": "图鉴", "鱼获": "我的鱼获",
    "鱼竿": "我的鱼竿", "鱼线": "鱼线", "鱼饵": "鱼饵", "鱼市": "鱼市",
    "水域": "水域", "海域": "水域", "钓场": "水域", "钓场地图": "水域",
    "钓手等级": "钓手等级", "鱼塘保护": "鱼塘保护",
    "资产榜": "资产榜", "资产排行榜": "资产榜", "财富榜": "资产榜",
    "重量榜": "重量榜", "重量排行榜": "重量榜", "鱼重榜": "重量榜",
    "积分": "积分", "积分榜": "总榜", "总榜": "总榜", "周榜": "周榜", "月榜": "月榜",
    "群规": "群规", "群规则": "群规", "游戏列表": "游戏列表",
    "可兑换奖励": "兑换列表", "兑换列表": "兑换列表", "功能列表": "菜单", "菜单": "菜单",
}


def command_alias(text):
    """仅把能明确识别的说法还原为已有指令，其余原样交给现有路由。"""
    phrase = text.strip().translate(MOBILE_CHARS)
    phrase = re.sub(r"^(?:请帮我|麻烦帮我|帮我|请)\s*", "", phrase)
    action = phrase.rstrip("。！!").strip()
    if action in ACTIONS:
        return ACTIONS[action]
    if action in ACTIONS.values():
        return action
    bait = re.fullmatch(r"(?:抛竿|抛杆|甩竿|甩杆|钓鱼)\s*(免费|高级|顶级)(?:鱼饵|饵)", action)
    if bait:
        return f"抛竿 {bait[1]}鱼饵"
    question = action.endswith(("?", "？"))
    item_text = action.rstrip("？?").strip() if question else action
    item = ITEM_AFTER.fullmatch(item_text)
    if item:
        return ITEM_ACTION[item[1]] if question else f"{ITEM_ACTION[item[1]]}#{item[2]}"
    item = ITEM_BEFORE.fullmatch(item_text)
    if item:
        return ITEM_ACTION[item[2]] if question else f"{ITEM_ACTION[item[2]]}#{item[1]}"
    if action in ITEM_ACTION:
        return ITEM_ACTION[action]
    lookup = re.sub(r"^(?:查看|查询|看看|看下|查一下|打开)?\s*(?:我的|本群)?\s*", "",
                    phrase.rstrip("。！!？?").strip())
    if lookup in LOOKUPS:
        return LOOKUPS[lookup]
    page = re.fullmatch(r"(鱼包|背包|鱼塘|图鉴|鱼类图鉴|钓鱼图鉴)\s*(?:第\s*)?([1-9][0-9]{0,3})\s*页?", lookup)
    if page:
        return f"{LOOKUPS[page[1]]} {page[2]}"
    return text


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
