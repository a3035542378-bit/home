"""单群一次性验收。在提交图片之后只读取原任务回执。"""
import json
from . import game_cards, native_voice_send as media


def send_image(client,token,task,snapshot,authorized):
    if not authorized():
        return "FAILED","图片测试授权已失效"
    try:
        jpeg=game_cards.render(json.loads(snapshot))
    except (OSError,ValueError,ImportError,KeyError,TypeError):
        from .agent_wechat import send_direct
        return send_direct(client,token,task) if authorized() else ("FAILED","授权已失效")
    return media.send_media(client,token,task,authorized,jpeg,"image",timeout=8)
