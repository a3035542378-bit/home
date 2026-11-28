"""在临时模拟群通过真实指令生成手记样图，不加载生产配置。"""
import argparse
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from ergou import db, engine, fishing_cards


def new_plates(output):
    from PIL import Image, ImageDraw
    from ergou.fishing_waters import SPECIES
    board=Image.new("RGB",(960,1030),fishing_cards.PAPER)
    draw=ImageDraw.Draw(board)
    draw.text((36,22),"渔获手记  /  新收录鱼类插画",font=fishing_cards.font(36,True),fill=fishing_cards.INK)
    for i,name in enumerate(("黄颡鱼","鲫鱼","鲈鱼","桂花鱼","虹鳟","金色锦鲤")):
        x,y=24+(i%2)*466,92+(i//2)*308
        rarity=SPECIES[name][-1]
        draw.rounded_rectangle((x,y,x+447,y+288),radius=12,outline=fishing_cards.SEALS[rarity],width=2)
        with Image.open(fishing_cards.ART/fishing_cards.PLATES[name]) as fish:
            fish.thumbnail((423,204),Image.Resampling.LANCZOS)
            board.paste(fish,(x+(447-fish.width)//2,y+12+(204-fish.height)//2))
        draw.text((x+18,y+226),name,font=fishing_cards.font(33,True),fill=fishing_cards.INK)
        draw.text((x+320,y+232),rarity+"鱼种",font=fishing_cards.font(24),fill=fishing_cards.SEALS[rarity])
    board.save(output/"新增鱼种图版.jpg",quality=90,optimize=True)


def preview(output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/"preview.sqlite"
        db.initialize(path)
        db.demo(path,("pond",))
        with db.closing_db(path) as conn:
            conn.execute("UPDATE groups SET config=json_set(config,'$.fishing_cards',1)")
            sequence=0
            def say(command):
                nonlocal sequence
                sequence+=1
                event=uuid.uuid5(uuid.NAMESPACE_URL,f"ergou-journal-preview/{sequence}")
                with patch.object(engine.uuid,"uuid4",return_value=event):
                    seq=engine.receive(conn,"sim-account","pond","angler",str(sequence),{"text":"二狗"+command},
                                       now=1795824000+sequence*60)
                engine.step(conn)
                card=conn.execute("""SELECT c.snapshot FROM inbox i JOIN outbox o ON o.biz=i.event_id
                     JOIN fishing_reply_cards c ON c.task=o.id WHERE i.seq=?""",(seq,)).fetchone()
                return json.loads(card[0]) if card else None
            def save(name, card):
                data=fishing_cards.render(card)
                if not data:
                    raise RuntimeError("生成失败，请检查 Pillow、中文字体和静态插画")
                (output/(name+".jpg")).write_bytes(data)
            sample_fish={"鲤鱼","白条","泥鳅"}
            collected=set()
            for _ in range(180):
                card=say("抛竿")
                if not card:
                    continue
                species=card["title"]
                if species in sample_fish and species not in collected:
                    collected.add(species)
                    if species=="鲤鱼":
                        save("钓获",card)
                    if len(collected)==len(sample_fish):
                        break
                else:
                    item=conn.execute("SELECT max(id) FROM fishing_pond WHERE storage='bag'").fetchone()[0]
                    say(f"卖鱼#{item}")
            else:
                raise RuntimeError("模拟群未集齐样图鱼种")
            save("鱼包",say("查看鱼包"))
            carp=conn.execute("SELECT id FROM fishing_pond WHERE fish='鲤鱼'").fetchone()[0]
            say(f"放入鱼塘#{carp}")
            save("鱼塘",say("鱼塘"))
            save("单鱼详情",say(f"查看鱼#{carp}"))
            say(f"收入图鉴#{carp}")
            save("图鉴",say("图鉴"))
            for name,command in (("装备","我的鱼竿"),("商店","鱼饵"),("钓手","钓鱼信息"),
                                  ("排行榜","图鉴榜"),("钓鱼帮助","钓鱼帮助")):
                save(name,say(command))
            say("签到")
            say("打工")
            save("个人档案",say("个人档案"))
            save("成就手册",say("成就手册"))
            conn.execute("INSERT INTO simulation_members VALUES('pond','neighbor')")
            save("礼物商店",say("礼物商店"))
            save("赠送小雏菊",say("送礼 小雏菊 @neighbor"))
    new_plates(output)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    preview(parser.parse_args().output)
