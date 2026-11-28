"""鱼获结算的只读快照，以及可离线重放的手记卡片。"""
import io
import os
import re
from functools import lru_cache
from pathlib import Path
from .fishing_waters import SPECIES


ART = Path(__file__).with_name("art")
PLATES = {"鲤鱼":"carp.jpg","泥鳅":"loach.jpg","白条":"sharpbelly.jpg",
          "黄颡鱼":"yellow-catfish.jpg","鲫鱼":"crucian.jpg","鲈鱼":"bass.jpg","虹鳟":"rainbow-trout.jpg",
          "金色锦鲤":"golden-koi.jpg","桂花鱼":"mandarin.jpg","长鳍金枪鱼":"../assets/albacore-plate.jpg"}
SEALS = {"普通":"#53695b","稀有":"#365d83","珍品":"#865333","史诗":"#725172","传说":"#8b6322"}
GIFT_ART={"小雏菊":"daisies","奶茶":"tea","蛋糕":"cake","小鱼玩偶":"plush","星星瓶":"stars","玫瑰花束":"roses"}
PAPER, INK, GREEN, SEPIA = "#faf5e9", "#303c37", "#42685c", "#815b37"


class JournalReply(str):
    def __new__(cls, text, *, heading, title, subtitle, species=None, facts=(), entries=(), notes=(), commands=()):
        reply = super().__new__(cls, text)
        reply.card = dict(heading=heading, title=title, subtitle=subtitle, species=species,
                          facts=facts, entries=entries, notes=notes, commands=commands)
        return reply


def sheet(body, prefix, heading, title, subtitle, *, facts=(), entries=(), species=None, lines=()):
    """保留操作费用、条件和当前群前缀，列表页沿用同一组微信指令。"""
    notes=[]
    commands=[]
    for line in lines:
        for part in line.splitlines():
            match=re.fullmatch(r"【([^】]+)】(.*)",part)
            if match:
                commands.append((prefix+match[1],match[2]))
            elif part.startswith(prefix):
                commands.append(part)
            elif part.strip():
                notes.append(part)
    return JournalReply(body,heading=heading,title=title,subtitle=subtitle,facts=facts,entries=entries,
                        species=species,notes=notes,commands=commands)


@lru_cache(maxsize=16)
def font(size, heading=False):
    from PIL import ImageFont
    paths = [os.getenv("ERGOU_CARD_FONT"), "C:/Windows/Fonts/simkai.ttf" if heading else "C:/Windows/Fonts/msyh.ttc",
             "/System/Library/Fonts/Hiragino Sans GB.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    for path in paths:
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise OSError("卡片需要中文字体")


def wrap(text, face, limit):
    # 汉字与超长昵称都可逐字换行；按实际字体宽度计算。
    for paragraph in str(text).splitlines():
        line = ""
        for char in paragraph:
            if line and face.getlength(line + char) > limit:
                yield line
                line = ""
            line += char
        if line:
            yield line


def render(card):
    """生成单张 JPEG。过长的历史清单、缺字体和损坏素材均沿用文字。"""
    try:
        return _render(card)
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return None


def _render(card):
    from PIL import Image, ImageDraw
    width, margin = 900, 52
    content = width - 2 * margin
    operations = []
    def write(text, x, y, size, color=INK, limit=content, heading=False):
        face = font(size, heading)
        for line in wrap(text, face, limit):
            operations.append(("text", (x, y), line, face, color))
            y += size + 12
        return y

    def rule(y):
        operations.append(("line", (margin, y, width-margin, y), "#c9bca2"))
        return y + 20

    def illustration(species, x, y, w, h):
        file=ART / PLATES[species] if species in PLATES else None
        operations.append(("art" if file and file.is_file() else "silhouette", (x,y),file,(w,h)))

    y = write("二狗  /  " + card["heading"], margin, 35, 27, GREEN)
    if card.get("player"):
        y = write(card["player"], margin, y, 25, GREEN)
    y = rule(y + 5)
    y = write(card["title"], margin, y, 65, heading=True)
    y = write(card["subtitle"], margin, y, 31, SEPIA)
    if card.get("gift") in GIFT_ART:
        operations.append(("art",(margin,y),ART/("gift-"+GIFT_ART[card["gift"]]+".jpg"),(content,320)))
        y+=340
    species=card.get("species")
    rarity=SPECIES[species][-1] if species in SPECIES else None
    if species:
        if rarity:
            y=write("藏印  ·  "+rarity+"鱼种",margin,y+5,27,SEALS[rarity])
        illustration(card["species"], margin, y+8, content, content//2)
        y += content//2 + 26
        if species not in PLATES or not (ART / PLATES[species]).is_file():
            y=write("通用剪影  ·  本种插画待收录",margin,y,26,GREEN)
    for i in range(0, len(card["facts"]), 2):
        bottom = y
        for col, (label, value) in enumerate(card["facts"][i:i+2]):
            x = margin + col * (content//2)
            pos = write(label, x, y, 24, GREEN, content//2-14)
            end=write(value, x, pos, 38, INK, content//2-14)
            if "耐久" in label or label=="鱼线 / 鱼竿":
                values=re.findall(r"(\d{1,3})%",str(value))
                for percent in values:
                    operations.append(("meter",(x,end,x+content//2-32,end+7),min(100,int(percent))))
                    end+=15
            bottom = max(bottom,end)
        y = bottom + 15
    for species, detail in card["entries"]:
        y = rule(y + 4)
        x = margin
        if species in GIFT_ART:
            operations.append(("art",(x,y),ART/("gift-"+GIFT_ART[species]+".jpg"),(140,90)))
            x+=155
        elif species in SPECIES:
            illustration(species, x, y, 164, 82)
            x += 186
            if species not in PLATES or not (ART / PLATES[species]).is_file():
                detail+="  ·  通用剪影"
        color=SEALS[SPECIES[species][-1]] if species in SPECIES else INK
        end = write(species, x, y, 38, color, heading=True, limit=width-margin-x)
        end = write(detail, x, end, 29, SEPIA, width-margin-x)
        y = max(end, y+84) + 6
    if card["notes"]:
        y = rule(y+4)
        for note in card["notes"]:
            clean = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27bf\ufe0f]", "", note).strip()
            y = write(clean, margin, y, 29)
    if card["commands"]:
        y = rule(y + 7)
        y = write("在群里发送", margin, y, 25, GREEN)
        for command in card["commands"]:
            if isinstance(command,(list,tuple)):
                command, purpose = command
                y = write(purpose, margin, y+2, 24, SEPIA)
            y = write(command, margin, y+2, 34)
    if y > 3100:
        return None
    image = Image.new("RGB", (width, y+40), PAPER)
    draw = ImageDraw.Draw(image)
    if rarity:
        draw.rounded_rectangle((12,12,width-13,image.height-13),radius=12,outline=SEALS[rarity],width=3)
    for op, *args in operations:
        if op == "text":
            xy, line, face, color = args
            draw.text(xy, line, font=face, fill=color, anchor="lt")
        elif op == "line":
            draw.line(args[0], fill=args[1], width=2)
        elif op=="meter":
            (x,y,right,bottom),value=args
            draw.rectangle((x,y,right,bottom),fill="#ded8c7")
            if value:
                draw.rectangle((x,y,x+(right-x)*value//100,bottom),fill=GREEN)
        elif op=="silhouette":
            (x,y),_,(w,h)=args
            draw.ellipse((x+w*.12,y+h*.30,x+w*.72,y+h*.72),fill="#91a29a")
            draw.polygon([(x+w*.64,y+h*.50),(x+w*.89,y+h*.26),(x+w*.85,y+h*.75)],fill="#91a29a")
        else:
            xy, path, size = args
            with Image.open(path) as plate:
                plate.thumbnail(size, Image.Resampling.LANCZOS)
                image.paste(plate,(xy[0]+(size[0]-plate.width)//2,xy[1]+(size[1]-plate.height)//2))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=87, optimize=True)
    return buf.getvalue()
