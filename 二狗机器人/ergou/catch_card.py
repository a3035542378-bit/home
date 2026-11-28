"""清爽图鉴钓获页。素材来自已确认的视觉稿，所有业务字段按快照排版。"""
from functools import lru_cache
from pathlib import Path
import os

from . import angler
from .game_cards import font
from .fishing_cards import ART, PLATES, SEALS

ASSETS = Path(__file__).with_name("assets")
INK = "#193c26"
RARITY = SEALS


@lru_cache(maxsize=48)
def face(size, bold=False):
    from PIL import ImageFont
    if not os.getenv("ERGOU_CARD_FONT"):
        for path,index in (("/System/Library/Fonts/Supplemental/Songti.ttc",1 if bold else 6),
                           ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",2)):
            if Path(path).is_file():
                return ImageFont.truetype(path,size,index=index)
    return font(size)


def field_page(card):
    from PIL import Image, ImageDraw
    page=Image.new("RGB",(720,1080))
    with Image.open(ASSETS/"field-paper.jpg") as paper:
        for x in range(0,720,paper.width):
            for y in range(0,1080,paper.height):
                page.paste(paper,(x,y))
    draw=ImageDraw.Draw(page)
    def write(x,y,text,size,*,width=650,bold=False,color=INK):
        text=str(text)
        f=face(size,bold)
        while size>20 and f.getlength(text)>width:
            size-=2
            f=face(size,bold)
        if f.getlength(text)>width:
            while text and f.getlength(text+"…")>width:
                text=text[:-1]
            text+="…"
        draw.text((x,y),text,font=f,fill=color,anchor="lt")

    with Image.open(ASSETS/"field-header.jpg") as header:
        page.paste(header,(23,12))
    fish=card["fish"]
    plate_path=ART/PLATES[fish] if fish in PLATES else None
    draw.rounded_rectangle((12,77,707,422),20,fill="#f8f8ed")
    if plate_path and plate_path.is_file():
        with Image.open(plate_path) as plate:
            plate.thumbnail((696,346),Image.Resampling.LANCZOS)
            page.paste(plate,(12+(696-plate.width)//2,77+(346-plate.height)//2))
    else:
        draw.ellipse((151,168,465,304),fill="#91a29a")
        draw.polygon([(441,231),(544,155),(540,306)],fill="#91a29a")
        write(215,344,"通用剪影 · 本种插画待收录",24)
    area=card.get("area")
    write(33,441,card["rarity"]+"鱼种"+(" / "+area if area else ""),31,color=RARITY.get(card["rarity"],INK))
    write(32,489,card["fish"],66,bold=True)
    write(34,573,f'渔获编号 #{card["item"]} · 品质 {card["quality"]} · {card["size"]}',28)
    draw.rounded_rectangle((16,623,703,751),16,fill="#dce4c9")
    draw.line((364,638,364,737),fill="#829471",width=1)
    for x,caption,value in ((39,"重量 / 公斤",f'{card["grams"]//1000}.{card["grams"]%1000:03d}'),
                            (393,"售价 / 鱼币",str(card["price"]))):
        write(x,639,caption,27)
        write(x,679,value,53,bold=True,width=303)
    draw.line((25,769,694,769),fill="#889779")
    casts=card["casts"]
    write(31,791,f"钓手 Lv.{angler.level(casts)}",34,bold=True)
    write(514,794,f"再抛 {angler.CASTS_PER_LEVEL-casts%angler.CASTS_PER_LEVEL} 竿升级",26,width=181)
    for y,title,pct in ((843,"鱼线",card["line"]),(894,"鱼竿",card["rod"])):
        write(31,y,f"{title}耐久 {pct}%",27,width=202)
        draw.rounded_rectangle((232,y+5,690,y+24),9,outline="#899d7d",width=1)
        if pct:
            end=232+458*pct//100
            draw.rounded_rectangle((232,y+5,end,y+24),min(9,(end-232)//2),fill="#799571")
    draw.line((24,943,695,943),fill="#889779")
    write(31,958,"鱼包 "+card["capacity"],32,bold=True)
    write(598,960,"已入包",27)
    draw.line((24,1008,695,1008),fill="#889779")
    write(31,1027,"群内发送："+card["step"],29)
    return page
