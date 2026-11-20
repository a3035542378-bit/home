"""微信群纯文本鱼获卡片。按显示宽度在右方补空格。"""
import unicodedata


def width(text):
    return sum(0 if unicodedata.combining(c) or c in ("\ufe0f","\u200d") else
               2 if unicodedata.east_asian_width(c) in ("W","F") else 1 for c in text)


def grid(rows):
    rows = [tuple(map(str,row)) for row in rows]
    if not rows:
        return []
    widths = [max(map(width,col)) for col in zip(*rows,strict=True)]
    return ["  ".join("["+cell+" "*(w-width(cell))+"]" for cell,w in zip(row,widths)) for row in rows]


def mass(grams):
    if grams>=1_000_000:
        kilos,remainder=divmod(grams,1000)
        suffix=f"{remainder:03d}".rstrip("0")
        return f"{kilos//1000}.{kilos%1000:03d}{suffix} 吨"
    return f"{grams/1000:.3f} 公斤" if grams>=1000 else f"{grams} 克"


def single(item,fish,quality,size,grams,price):
    return grid([(f"名称: {fish}",f"品质: {quality}",f"大小: {size or '未记录'}"),
                 (f"编号: {item}",f"重量: {mass(grams)}",f"售价: {price} 鱼币")])
