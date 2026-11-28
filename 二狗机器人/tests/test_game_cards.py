import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ergou import db,engine,game_cards


class GameCards(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"cards.sqlite"
        db.initialize(path)
        db.demo(path,("one","two"))
        self.conn=self.enterContext(db.closing_db(path))
        self.conn.execute("UPDATE groups SET config=json_set(config,'$.game_card_mode','mixed') WHERE id='one'")

    def send(self,key="b",cmd="抛竿",now=101,group="one"):
        seq=engine.receive(self.conn,"sim-account",group,"player",key,{"text":"二狗 "+cmd},now=now)
        engine.step(self.conn)
        return seq

    def test_snapshot_replay_and_text_fallback(self):
        seq=self.send()
        self.assertEqual(seq,self.send())
        data=json.loads(self.conn.execute("SELECT snapshot FROM game_card_snapshots").fetchone()[0])
        fish=self.conn.execute("SELECT * FROM fishing_pond").fetchone()
        for field in ("grams","price","fish"):
            self.assertEqual(data[field],fish[field])
        self.assertEqual(data["item"],fish["id"])
        self.assertEqual(data["casts"],1)
        self.assertIsNone(game_cards.preview(self.conn,"two",seq))
        self.assertIsNone(game_cards.preview(self.conn,"one",self.send("cool","钓鱼",102)))
        with patch.object(game_cards,"render",side_effect=OSError("fixture")):
            self.assertIsNone(game_cards.preview(self.conn,"one",seq))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM fishing_pond").fetchone()[0],1)
        self.assertIsNone(game_cards.preview(self.conn,"two",self.send(group="two")))
        self.assertIn("上钩",self.conn.execute("SELECT body FROM outbox LIMIT 1").fetchone()[0])

    def test_reference_templates_follow_group_mode(self):
        self.conn.execute("UPDATE groups SET config=json_set(config,'$.game_card_mode','image') WHERE id='one'")
        self.send()
        for idx,cmd in enumerate(("查看鱼#1","我的鱼竿","鱼塘","图鉴","图鉴榜","钓鱼玩法")):
            seq=self.send("read-"+str(idx),cmd,201+idx*65)
            row=self.conn.execute("""SELECT c.snapshot,o.body FROM game_card_snapshots c JOIN outbox o ON o.id=c.task
                                     JOIN inbox i ON i.event_id=o.biz WHERE i.seq=?""",(seq,)).fetchone()
            self.assertEqual(json.loads(row["snapshot"])["text"],row["body"])
        self.conn.execute("UPDATE groups SET config=json_set(config,'$.game_card_mode','mixed') WHERE id='one'")
        self.assertIsNone(game_cards.preview(self.conn,"one",self.send("gear","我的鱼竿",730)))

    def test_render_mobile_fields(self):
        try:
            from PIL import Image
            game_cards.font(22)
        except (ImportError,OSError):
            self.skipTest("本机缺少卡片预览依赖")
        self.send()
        card=json.loads(self.conn.execute("SELECT snapshot FROM game_card_snapshots").fetchone()[0])
        outputs=set()
        for rarity in game_cards.PALETTE:
            data=game_cards.render(dict(card,rarity=rarity,nickname="群昵称"*30,fish="超长鱼名"*20))
            with Image.open(BytesIO(data)) as im:
                self.assertEqual(im.size,(720,1080))
                self.assertEqual(im.format,"JPEG")
            outputs.add(data)
        self.assertEqual(len(outputs),5)
        self.assertEqual(card["area"],"新手池塘")
        for remaining in (0,1,100):
            legacy=dict(card,fish="长鳍金枪鱼",line=remaining,rod=remaining)
            legacy.pop("area")
            self.assertTrue(game_cards.render(legacy).startswith(b"\xff\xd8"))
        seq=self.send("inventory","背包",155)
        self.assertTrue(game_cards.preview(self.conn,"one",seq).startswith("data:image/jpeg;base64,"))
