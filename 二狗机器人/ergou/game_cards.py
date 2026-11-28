"""游戏回执展示。只消费结算快照，渲染器不接收数据库连接。"""
from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path

from .fish_receipts import mass

PALETTE = {"普通":"#74d9ce","稀有":"#78bbff","珍品":"#ffbd74","史诗":"#c7a2ff","传说":"#ffdc77"}
INK = "#eff6ee"
MUTED = "#a3c4c9"


class CardReply(str):
    def __new__(cls, body, kind, **fields):
        obj = super().__new__(cls, body)
        obj.snapshot = dict(kind=kind, **fields)
        if hasattr(body,"card"):
            obj.card=body.card
            obj.snapshot["journal"]=body.card
        return obj


@lru_cache(maxsize=24)
def font(size):
    from PIL import ImageFont
    paths = (os.getenv("ERGOU_CARD_FONT"), "/System/Library/Fonts/Hiragino Sans GB.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "C:/Windows/Fonts/msyh.ttc")
    for path in paths:
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise OSError("缺少中文字体")


def render(card):
    from PIL import Image, ImageDraw
    if "journal" in card:
        from .fishing_cards import render as render_journal
        data=render_journal(dict(card["journal"],player=card.get("nickname","")))
        if data is None:
            raise ValueError("暂时无法生成手绘图版")
        return data
    if card["kind"]=="catch":
        from .catch_card import field_page
        out=BytesIO()
        field_page(card).save(out,"JPEG",quality=88,optimize=True,subsampling=0)
        return out.getvalue()
    bag = card["kind"] == "bag"
    rows = card.get("rows", [])
    if len(rows)>8:
        raise ValueError("历史鱼包过长，保留完整文本")
    lines = []
    if not bag:
        # 只换行，不截去排行、规则或操作说明。
        for line in card["text"].splitlines():
            chunk = ""
            for ch in line:
                if font(25).getlength(chunk+ch)>642:
                    lines.append(chunk)
                    chunk = ""
                chunk += ch
            lines.append(chunk)
        if len(lines)>46:
            raise ValueError("回执过长")
    height = 234+92*len(rows) if bag else 174+39*len(lines)
    img = Image.new("RGB",(720,height),"#102830")
    d = ImageDraw.Draw(img)
    accent = PALETTE.get(card.get("rarity"),"#74d9ce")
    def label(x,y,value,size,color=INK,limit=640):
        value=str(value)
        f=font(size)
        if f.getlength(value)>limit:
            while value and f.getlength(value+"…")>limit:
                value=value[:-1]
            value+="…"
        d.text((x,y),value,font=f,fill=color,anchor="lt")
    d.rectangle((0,0,719,8),fill=accent)
    label(38,30,"二狗   /   渔获手记",22,accent)
    label(38,72,card["title"],42)
    label(460,34,card.get("nickname",""),22,MUTED,218)
    if bag:
        for i,row in enumerate(rows):
            y=143+92*i
            d.line((38,y,680,y),fill="#405a61")
            label(38,y+14,"#"+str(row["id"]),22,MUTED,125)
            label(170,y+12,row["fish"],30,limit=284)
            label(475,y+15,str(row["price"])+" 鱼币",25,accent,206)
            label(170,y+56,mass(row["grams"])+"  ·  "+row["quality"],20,MUTED)
    else:
        for i,line in enumerate(lines):
            label(38,141+39*i,line,25)
    if bag:
        label(38,height-76,"群内发送",20,MUTED)
        label(38,height-48,card["step"],28,accent)
    out=BytesIO()
    img.save(out,"JPEG",quality=88,optimize=True,subsampling=0)
    return out.getvalue()


def preview(db, group, seq):
    import base64
    import json
    import logging
    row=db.execute("""SELECT c.snapshot FROM game_card_snapshots c JOIN outbox o ON o.id=c.task
                      JOIN inbox i ON i.event_id=o.biz AND i.grp=o.grp WHERE i.grp=? AND i.seq=?""",
                   (group,seq)).fetchone()
    if not row:
        return None
    try:
        data=render(json.loads(row[0]))
    except (ImportError,OSError,ValueError,KeyError,TypeError) as exc:
        logging.getLogger(__name__).warning("游戏卡片使用文字回执 (%s)",type(exc).__name__)
        return None
    return "data:image/jpeg;base64,"+base64.b64encode(data).decode("ascii")
