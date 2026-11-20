"""Music search links, local recipes, and read-only Chinese Wikipedia lookups."""
import json
import re
import time
from urllib.parse import urlencode

from . import bulletins, queries

WIKI_API = "https://zh.wikipedia.org/w/api.php"
RECIPES = {
    "番茄炒蛋": ("番茄2个、鸡蛋2个、油、盐", "番茄切块，鸡蛋打散。热锅放油，将鸡蛋炒至凝固后盛出。炒软番茄，倒回鸡蛋翻匀，加盐调味。"),
    "蒜蓉西兰花": ("西兰花1小颗、蒜2瓣、油、盐", "西兰花洗净切小朵，放入沸水焯至断生后沥干。锅中加油炒香蒜末，倒入西兰花翻炒，加盐调味。"),
    "醋溜土豆丝": ("土豆2个、米醋1勺、油、盐", "土豆切细丝，用清水洗去表面淀粉后沥干。热锅放油翻炒土豆丝至熟，沿锅边淋醋，加盐炒匀。"),
    "香菇豆腐": ("豆腐1块、鲜香菇4朵、生抽、油", "香菇去蒂切片，豆腐切块。炒香香菇，加半碗清水和少许生抽，放入豆腐，小火煨至入味后收汁。"),
    "黄瓜拌木耳": ("黄瓜1根、干木耳5克、蒜、醋、生抽", "木耳用清水泡发后洗净，放入沸水煮熟，沥干放凉。黄瓜洗净拍碎切段，和木耳、蒜末、醋、生抽拌匀。"),
    "南瓜小米粥": ("南瓜150克、小米50克、水约600毫升", "南瓜去皮切丁，小米淘洗干净。水开后加入南瓜、小米，小火煮约25分钟，中途搅拌，煮至米粒软烂。"),
    "青椒炒蛋": ("青椒2个、鸡蛋2个、油、盐", "青椒洗净去籽切丝，鸡蛋打散。炒熟蛋液后盛出。下青椒翻炒至熟，倒回鸡蛋，加盐炒匀。"),
    "葱油拌面": ("面条1人份、小葱2根、生抽、油", "小葱洗净擦干切段，冷油下锅，小火煎出香味后关火。面条另锅煮熟沥水，趁热拌入葱油和生抽。"),
}


def normalize(text):
    match = re.fullmatch(r"(?:请帮我|帮我|请)?(点一首|点首|点歌|搜歌|查菜谱|菜谱|查百科|百科)[\s:：]*(.*)", text)
    if not match:
        return text
    word, argument = match.groups()
    kind = {"点一首":"点歌","点首":"点歌","搜歌":"点歌","查菜谱":"菜谱","查百科":"百科"}.get(word,word)
    return (kind + " " + argument.strip()).strip()


def term(argument):
    if (not isinstance(argument,str) or not 1<=len(argument.strip())<=64
            or not argument.strip().isprintable()):
        raise ValueError("请输入 1–64 字的查询词")
    return argument.strip()


def local(kind, argument):
    if kind=="点歌":
        if not argument:
            return "想听哪首歌？例如「二狗点歌 茉莉花」。"
        song = term(argument)
        return "🎵 在 Apple Music 搜索歌曲或歌手「" + song + "」\nhttps://music.apple.com/cn/search?" + urlencode({"term":song})
    if kind!="菜谱":
        raise ValueError("无效的本地查询类型")
    menu = "、".join(RECIPES)
    if not argument:
        return "二狗的家常菜谱："+menu+"。可以告诉我菜名或食材。"
    ingredient = term(argument).replace("西红柿","番茄").replace("马铃薯","土豆")
    if ingredient in RECIPES:
        names = [ingredient]
    else:
        names = [name for name,(ingredients,_) in RECIPES.items() if ingredient in name or ingredient in ingredients]
    if not names:
        return "本地菜谱还没有这个菜名或食材。现有："+menu+"。"
    if len(names)>1:
        return "🍳 可以做这些菜\n"+"\n".join(f"【菜谱 {name}】看食材和做法" for name in names)
    name = names[0]
    ingredients,steps = RECIPES[name]
    return f"🍳 {name}\n食材：{ingredients}。\n做法：{steps}"


def search_link(keyword):
    return "https://zh.wikipedia.org/w/index.php?" + urlencode({"search":keyword})


def _page(params, deadline):
    params=dict(action="query",format="json",formatversion=2,prop="extracts",exintro=1,explaintext=1,exchars=200,**params)
    url = WIKI_API + "?" + urlencode(params)
    raw = bulletins.public_get(url,131072,min(6,deadline-time.monotonic()),
                               user_agent="ErgouGroupBot/1.0 (Chinese Wikipedia article search)")
    try:
        data = json.loads(raw)
        if not isinstance(data,dict):
            raise ValueError()
        if "error" in data:
            raise queries.ProviderError("供应商暂不可用")
        pages = data.get("query",{}).get("pages",[])
        if not isinstance(pages,list) or ("query" not in data and "batchcomplete" not in data):
            raise ValueError()
        if not pages:
            return None
        page = pages[0]
        if page.get("missing") or page.get("invalid") or page.get("ns",0)!=0:
            return None
        page_id,title = page["pageid"],page["title"]
        if type(page_id) is not int or page_id<=0 or not isinstance(title,str) or not title.strip():
            raise ValueError()
        summary = " ".join(page.get("extract","").split())[:240]
        return (f"📚 中文维基百科 · {title[:120]}\n"+(summary+"\n" if summary else "")+
                f"https://zh.wikipedia.org/?curid={page_id}")
    except queries.ProviderError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError):
        raise queries.ProviderError("供应商数据格式异常") from None


def encyclopedia(argument, deadline, *, check=None):
    keyword = term(argument)
    if "|" not in keyword:
        exact=_page({"titles":keyword,"redirects":1,"converttitles":1},deadline)
        if exact:
            return exact
    if check:
        check()
    article=_page(dict(generator="search",gsrsearch=keyword,gsrnamespace=0,gsrlimit=1),deadline)
    return "相关条目 · "+article if article else "暂未找到相关词条，试试中文维基百科搜索页：\n"+search_link(keyword)
