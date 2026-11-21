"""Local command parsing for addressed text and speech transcripts."""
import hashlib
import re
from datetime import datetime

from .db import BJ
from .games import GAMES
from .fishing_waters import WATERS

SIGNS="白羊 金牛 双子 巨蟹 狮子 处女 天秤 天蝎 射手 摩羯 水瓶 双鱼".split()

# 只映射完整指令。尤其是卖鱼和移动展品，不按聊天正文中的子串触发。
ITEM_WORDS = {
    "放入图鉴": ("放入图鉴", "收入图鉴", "收录图鉴", "录入图鉴", "存入图鉴", "加入图鉴", "收藏图鉴", "收藏到图鉴", "收进图鉴", "放进图鉴", "点亮图鉴"),
    "放入鱼塘": ("放入鱼塘", "收入鱼塘", "存入鱼塘", "放进鱼塘", "移入鱼塘", "放到鱼塘", "存塘"),
    "卖鱼": ("卖", "卖鱼", "出售", "出售鱼", "卖出", "卖掉"),
}
ITEM_ACTION = {word: action for action, words in ITEM_WORDS.items() for word in words}
ACTION = "(?:" + "|".join(map(re.escape, ITEM_ACTION)) + ")"
NUMBER = r"[1-9][0-9]{0,17}"
ITEM_AFTER = re.compile(rf"({ACTION})\s*(?:#|编号)?\s*({NUMBER})(?:号鱼|号)?")
ITEM_BEFORE = re.compile(rf"(?:把|将)?\s*(?:#|编号)?\s*({NUMBER})(?:号鱼|号)?\s*({ACTION})")
MOBILE_CHARS = str.maketrans("＃０１２３４５６７８９", "#0123456789")

ACTIONS = {
    "图鉴排行榜": "图鉴榜",
    "抛杆": "抛竿", "甩竿": "抛竿", "甩杆": "抛竿", "钓一竿": "抛竿",
    "升级背包": "升级鱼包", "背包扩容": "升级鱼包", "鱼包扩容": "升级鱼包", "扩容鱼包": "升级鱼包", "鱼塘扩容": "升级鱼塘", "扩容鱼塘": "升级鱼塘",
    "更换鱼线":"买鱼线", "换鱼线":"买鱼线", "维修鱼竿":"修理鱼竿", "修竿":"修理鱼竿",
    "鱼竿升级": "升级鱼竿", "鱼线升级": "升级鱼线", "鱼竿强化": "强化鱼竿",
    "抽签报名": "抽签 报名", "报名抽签": "抽签 报名", "退出抽签": "抽签 退出",
}

WATER_ALIASES = dict.fromkeys(("切换钓场","换钓场","换图","切换水域","切换海域"), "切换水域")
WATER_REQUEST = re.compile(r"(?:想|我想)?(?:要)?(?:更换|切换|切|换|前往|去)(?:去|到|个|一下)?"
                           r"(?:一个|别的|新的|其他|高级|下一个)?(?:钓鱼场|钓场|渔场|场地|地图|图|水域|海域|场)"
                           r"(?:去|到|为)?\s*(.*)")
HELP_REQUEST = re.compile(r"(?:想看|查看|打开|看看|看下|介绍一下|教我)?(?:一下)?(?:钓鱼.*(?:菜单|帮助|玩法|怎么玩)|(?:怎么玩|怎么|如何)钓鱼)")
BAG_REQUEST = re.compile(r"(?:我想|想)?(?:查看|看一下|看看|看下|打开|瞅瞅|查查)?(?:一下)?(?:我的)?(?:鱼包|背包)(?:里(?:面)?)?(?:有啥|有什么鱼?|有哪些鱼|都有啥|装了什么)?")
FISHING_LOOKUPS = {
    **dict.fromkeys(("钓鱼菜单","钓鱼帮助","怎么钓鱼"), "钓鱼玩法"),
    **dict.fromkeys(("鱼包","背包","看鱼","鱼背包"), "查看鱼包"),
}

LOOKUPS = {
    **FISHING_LOOKUPS,
    "升品玩法": "鱼获品级", "鱼获品级": "鱼获品级",
    "巨物预告": "巨物鱼讯", "巨物事件": "巨物鱼讯", "巨物鱼讯": "巨物鱼讯", "全图鉴": "全图鉴",
    "钓鱼信息": "钓鱼信息", "个人钓鱼信息": "钓鱼信息", "钓鱼档案": "钓鱼信息",
    "钓鱼状态": "钓鱼信息", "鱼币余额": "钓鱼信息",
    "鱼塘": "鱼塘",
    "史诗图鉴": "史诗图鉴", "传说图鉴": "传说图鉴",
    "巨物图鉴": "巨物图鉴", "珍品图鉴": "珍品图鉴", "稀有图鉴": "稀有图鉴", "普通图鉴": "普通图鉴",
    "图鉴": "图鉴", "鱼类图鉴": "图鉴", "钓鱼图鉴": "图鉴", "鱼获": "我的鱼获",
    "鱼钩": "我的鱼竿", "我的鱼钩": "我的鱼竿", "鱼竿": "我的鱼竿", "鱼线": "鱼线", "鱼饵": "鱼饵", "鱼市": "鱼市",
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
    if not action:
        return text
    verb, *args = action.split(maxsplit=1)
    if verb in WATER_ALIASES:
        return " ".join([WATER_ALIASES[verb], *args])
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
    if lookup in WATER_ALIASES:
        return WATER_ALIASES[lookup]
    if lookup in LOOKUPS:
        return LOOKUPS[lookup]
    page = re.fullmatch(r"(鱼包|背包|鱼塘|图鉴|鱼类图鉴|钓鱼图鉴|全图鉴|普通图鉴|稀有图鉴|珍品图鉴|史诗图鉴|传说图鉴|巨物图鉴)\s*(?:第\s*)?([1-9][0-9]{0,3})\s*页?", lookup)
    if page:
        return f"{LOOKUPS[page[1]]} {page[2]}"
    # 优先保留扩容、整包出售和翻页。口语导航缺少明确地名时只展示选择。
    water = WATER_REQUEST.fullmatch(action.rstrip("？?").strip())
    if water:
        area = water[1].strip()
        return "切换水域 " + area if area in WATERS else "切换水域"
    if lookup.startswith("去") and lookup[1:].strip() in WATERS:
        return "切换水域 " + lookup[1:].strip()
    if HELP_REQUEST.fullmatch(lookup):
        return "钓鱼玩法"
    if BAG_REQUEST.fullmatch(lookup):
        return "查看鱼包"
    return text


def navigation_hint(text):
    """精确指令全部未命中后，关键词组合只打开只读面板。"""
    if any(word in text for word in ("换","切","去")) and any(word in text for word in ("场","图","水域")):
        return "切换水域"
    if "钓鱼" in text and any(word in text for word in ("菜单","帮助","玩法","怎么玩")):
        return "钓鱼玩法"
    if "鱼包" in text or "背包" in text:
        return "查看鱼包"
    return None


def interpret(text,cfg):
    phrase=text.strip().rstrip("。！!？?").strip()
    if not phrase:
        return text
    request=re.sub(r"^(?:请问|麻烦|可以帮我|请帮我|帮我|我想|请)","",phrase)
    game=re.sub(r"^(?:玩一局|玩个|玩|开始玩|来一局|来个)","",request)
    if game in GAMES:
        return "开始 "+game
    match=re.fullmatch(r"(?:查看|查询|查一下|查查|查|看看|看下)?(.{2,16}?)(?:今天|现在|今日)?的?天气(?:怎么样|如何|好吗)?",request)
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


def horoscope(sign,stamp,prefix="二狗"):
    name=sign.strip().removesuffix("座")
    if name not in SIGNS:
        return f"🌟 星座查询\n把示例换成你的星座\n{prefix}星座 双鱼座"
    day=datetime.fromtimestamp(stamp,BJ).strftime("%Y-%m-%d")
    tips=("和老朋友聊聊近况。","给手头最重要的小事留十分钟。","出门散步时留意一件新鲜事。",
          "把想说的感谢告诉对方。","遇到犹豫的事，先列出两个选择。","给自己的爱好留一点时间。")
    i=hashlib.sha256((day+name).encode()).digest()[0]%len(tips)
    return f"🌟 {name}座 · {day}\n今日趣味签：{tips[i]}（本地娱乐内容）"
