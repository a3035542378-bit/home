"""Boundary and distribution checks against the same baseline as replay.py."""
import json
import math
import tempfile
import uuid
from pathlib import Path
from random import Random
from unittest.mock import patch

from ergou import db, pond_growth as growth
from replay import EPOCH, World, digest


def promotion():
    results=[]
    for level in (1,5):
        for fed in (0,1,3):
            rng=Random(716000+10*level+fed)
            n=300000
            hits=0
            for _ in range(n):
                state=dict(original_grams=1200,rounds=2,first_fed=0,food=int(fed>0),
                           fed_segment=max(0,fed-1),appearance=0,promoted=0)
                _,grade=growth.advance("鲤鱼",state,1210,1,level,rng)
                hits+=grade==2
            expected=(.001+.002*fed/3)*(1+(level-1)/4)
            assert abs(hits-n*expected)<5*math.sqrt(n*expected*(1-expected))
            results.append((level,fed,n,hits,round(100*expected,4)))
    class Winning:
        def randint(self,a,b): return a
        def random(self): return 0.
    for initial,expected in ((0,1),(2,3),(3,4),(4,4),(5,5)):
        state=dict(original_grams=1200,rounds=0,first_fed=0,food=0,fed_segment=0,appearance=0,promoted=0)
        grams,grade=1200,initial
        for _ in range(10):
            grams,grade=growth.advance("鲤鱼",state,grams,grade,5,Winning())
        assert grade==expected and state["promoted"]==int(initial<4)
    return results


def boundaries(folder):
    import re
    path=folder/"boundary.db"
    w=World(path,31,"natural",folder/"checks.jsonl")
    key=("lake","brief")
    seq=0
    def say(cmd,t,owner=key):
        nonlocal seq
        seq+=1
        return w.send(owner,cmd,EPOCH+t,f"rule/{seq}")
    def state(item):
        return tuple(w.con.execute("""SELECT g.rounds,p.grams,p.price,p.grade,g.food,g.appearance,g.next_at
            FROM fishing_pond p JOIN pond_growth g ON p.id=g.item WHERE p.id=?""",(item,)).fetchone())
    def catch(t):
        for _ in range(60):
            reply=say("抛竿",t)
            t+=21
            match=re.search(r"收入鱼包 #(\d+)",reply)
            if match:
                return int(match[1]),t
        raise AssertionError("未落袋")
    with patch("time.time",new=lambda:w.now),patch("uuid.uuid4",new=lambda:uuid.UUID(digest(w.token)[:32])):
        try:
            item,t=catch(10)
            cmd=lambda verb:verb+"#"+str(item)
            before=state(item)
            assert "已将" in say(cmd("放入鱼塘"),t)
            assert "没有" in say(cmd("卖鱼"),t+1,("bay","brief"))
            assert "没有" in say(cmd("投喂"),t+2,("lake","split"))
            assert "已投喂" in say(cmd("投喂"),t+3)
            coins=w.con.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()[0]
            assert "还有 3 轮" in say(cmd("投喂"),t+4)
            assert w.con.execute("SELECT coins FROM fishing_wallets WHERE grp=? AND member=?",key).fetchone()[0]==coins
            say("鱼塘",t+179)
            assert state(item)[0:2]==before[0:2]
            say("鱼塘",t+180)
            first=state(item)
            assert first[0]==1 and first[1]>before[1]
            say("鱼塘",t+180)
            assert state(item)==first
            w.con.close()
            db.initialize(path)
            w.con=db.connect(path)
            w.con.create_function("date",2,w.sqlite_date)
            say("鱼塘",t+180)
            assert state(item)==first
            assert "已定型" in say("鱼塘",t+86400)
            final=state(item)
            assert final[0]==10 and final[-1] is None
            say("鱼塘",t+90000)
            assert state(item)==final
            assert w.con.execute("SELECT best_grams FROM fishing_records WHERE grp=? AND member=?",key).fetchone()[0]==before[1]
            assert w.con.execute("SELECT best_grams FROM fishing_species WHERE grp=? AND member=?",key).fetchone()[0]==before[1]
            assert "已定型" in say(cmd("投喂"),t+90001)
            assert f"到账 {final[2]} 枚" in say(cmd("卖鱼"),t+90002)
            second,t=catch(t+90030)
            assert "已将" in say(f"放入鱼塘#{second}",t)
            say("鱼塘",t+361)
            mid=state(second)
            assert mid[0]==2 and mid[-1] is not None
            assert f"到账 {mid[2]} 枚" in say(f"卖鱼#{second}",t+362)
            assert "没有" in say(f"卖鱼#{second}",t+363)
            return dict(initial_grams=before[1],round1_grams=first[1],final_grams=final[1],
                        offline_rounds=final[0]-first[0],record=before[1],early_rounds=mid[0],early_sale=mid[2])
        finally:
            w.con.close()


if __name__=="__main__":
    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(dict(boundary=boundaries(Path(tmp)),promotion=promotion()),ensure_ascii=False))
