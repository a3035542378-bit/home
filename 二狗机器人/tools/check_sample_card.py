"""离线检查待授权的单张样图。只读取 JPEG 文件。"""
import argparse
import hashlib
import io
import json
from pathlib import Path

SAMPLE=Path(__file__).resolve().parents[1]/"examples"/"渔获手记"/"钓获.jpg"


def inspect(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.format!="JPEG":
            raise ValueError("请选择 JPEG 卡片")
        image.load()
        return {"format":image.format,"width":image.width,"height":image.height,
                "bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file",nargs="?",type=Path,default=SAMPLE)
    print(json.dumps(inspect(parser.parse_args().file.read_bytes()),indent=2))
