import io
import json
import unittest
from unittest.mock import patch
from ergou import fishing_cards
from . import test_robot


class FishingCards(unittest.TestCase):
    setUp = test_robot.Robot.setUp
    tearDown = test_robot.Robot.tearDown
    say = test_robot.Robot.say

    def test_art_mapping_and_empty_storage_cards(self):
        from ergou.fishing_waters import SPECIES
        self.assertTrue(set(fishing_cards.PLATES)<=set(SPECIES))
        self.assertEqual(len(set(fishing_cards.PLATES.values())),len(fishing_cards.PLATES))
        for path in fishing_cards.PLATES.values():
            self.assertTrue((fishing_cards.ART/path).is_file(),path)
        self.db.execute("UPDATE groups SET config=json_set(config,'$.fishing_cards',1) WHERE id='a'")
        for command in ("查看鱼包","鱼塘"):
            self.say("二狗"+command)
            snapshot=json.loads(self.db.execute("SELECT snapshot FROM fishing_reply_cards ORDER BY task DESC LIMIT 1").fetchone()[0])
            self.assertFalse(snapshot["entries"])
            self.assertTrue(snapshot["commands"])

    def test_snapshots_follow_single_settlement_and_group_setting(self):
        self.db.execute("UPDATE groups SET config=json_set(config,'$.fishing_cards',1) WHERE id='a'")
        first=self.say("二狗抛竿",key="cast")["body"]
        self.assertIn("第一尾鱼",first)
        self.say("二狗抛竿",key="cast")
        self.say("二狗抛竿",group="b")
        self.say("二狗抛竿")
        for cmd in ("查看鱼包","图鉴"):
            self.say("二狗"+cmd)
        rows=self.db.execute("SELECT o.grp,c.snapshot FROM fishing_reply_cards c JOIN outbox o ON c.task=o.id ORDER BY o.id").fetchall()
        self.assertEqual([r["grp"] for r in rows],["a"]*3)
        catch,bag,book=[json.loads(r["snapshot"]) for r in rows]
        self.assertEqual(catch["title"],bag["entries"][0][0])
        self.assertIn([catch["title"],catch["subtitle"].split("  /  ")[1]+" · 已发现"],book["entries"])
        self.assertIn("二狗查看鱼包",catch["commands"])
        self.assertEqual(1,self.db.execute("SELECT count FROM fishing_records WHERE grp='a'").fetchone()[0])
        self.clock+=30
        later=self.say("二狗抛竿")["body"]
        self.assertNotIn("第一尾鱼",later)
        self.say("二狗卖出鱼包")
        self.assertEqual(bag,json.loads(self.db.execute("SELECT snapshot FROM fishing_reply_cards ORDER BY task LIMIT 1 OFFSET 1").fetchone()[0]))

    def test_missing_font_falls_back_and_long_values_wrap(self):
        card=fishing_cards.JournalReply("原回执",heading="渔获手记",title="很长的鱼种名称"*9,
             subtitle="稀有鱼种",facts=[("售价",str(10**36)+" 鱼币")],commands=["团团查看鱼包"]).card
        card["player"]="昵称"*40
        with patch.object(fishing_cards,"font",side_effect=OSError):
            self.assertIsNone(fishing_cards.render(card))
        try:
            from PIL import Image
            fishing_cards.font(25)
        except (OSError,ImportError):
            self.skipTest("当前环境没有 Pillow 或中文字体")
        jpeg=fishing_cards.render(card)
        with Image.open(io.BytesIO(jpeg)) as im:
            self.assertEqual(im.width,900)
            self.assertLess(im.height,3150)
