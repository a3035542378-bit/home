"""从临时模拟群的实际结算生成卡片样品。"""
import argparse
import json
from pathlib import Path
import statistics
import tempfile
import time

from ergou import db, engine, game_cards


def generate(output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/"sample.sqlite"
        db.initialize(path)
        db.demo(path,("one",))
        with db.closing_db(path) as conn:
            conn.execute("UPDATE groups SET config=json_set(config,'$.game_card_mode','image')")
            for source,cmd,stamp in (("b","抛竿",101),("d","钓鱼",165),("c3","抛竿",225),("bag","鱼包",290),
                                     ("detail","查看鱼#1",355),("gear","我的鱼竿",420),
                                     ("pond","鱼塘",485),("book","图鉴",550),
                                     ("ranking","图鉴榜",615),("guide","钓鱼玩法",680)):
                seq=engine.receive(conn,"sim-account","one","player",source,{"text":"二狗 "+cmd},now=stamp)
                engine.step(conn)
                if source in ("d","c3"):
                    continue
                row=conn.execute("""SELECT c.snapshot FROM game_card_snapshots c JOIN outbox o ON o.id=c.task
                                    JOIN inbox i ON i.event_id=o.biz WHERE i.seq=?""",(seq,)).fetchone()
                card=json.loads(row[0])
                times=[]
                for _ in range(5):
                    start=time.perf_counter()
                    data=game_cards.render(card)
                    times.append((time.perf_counter()-start)*1000)
                target=output/(("catch" if source=="b" else source)+".jpg")
                target.write_bytes(data)
                print(target,len(data),"bytes",round(statistics.median(times),1),"ms")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    generate(parser.parse_args().output)
