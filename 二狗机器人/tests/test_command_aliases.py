import tempfile
import unittest
from pathlib import Path

from ergou import db, engine
from ergou.intents import command_alias


class CommandAliasTests(unittest.TestCase):
    def test_mobile_spellings(self):
        cases = {
            "收入图鉴#17": "放入图鉴#17",
            "请帮我把１７号鱼收录图鉴": "放入图鉴#17",
            "存入图鉴　＃　１７": "放入图鉴#17",
            "#17放进鱼塘": "放入鱼塘#17",
            "卖17号鱼": "卖鱼#17", "卖＃１７": "卖鱼#17",
            "去高级场": "切换水域", "换个地图": "切换水域",
            "切换钓场到荷花湿地": "切换水域 荷花湿地", "去荷花湿地": "切换水域 荷花湿地",
            "我想看看我的鱼包里有啥": "查看鱼包", "钓鱼的玩法": "钓鱼玩法",
            "出售17号鱼": "卖鱼#17",
            "出售17号鱼？": "卖鱼",
            "看看我的背包第２页": "查看鱼包 2",
            "查看本群财富榜": "资产榜",
            "鱼包扩容": "升级鱼包",
            "甩杆高级饵": "抛竿 高级鱼饵",
            "查询群规则": "群规",
            "报名抽签": "抽签 报名",
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(command_alias(phrase), expected)
        for chat in ("别卖17号鱼", "卖#17和#18", "不要收入图鉴#17", "解释一下卖鱼#17", "收入图鉴#17和#18",
                     "收入图鉴#0", "收入图鉴#17.5", "我叫它收入图鉴#17", "收入图鉴#１７abc"):
            with self.subTest(chat=chat):
                self.assertEqual(command_alias(chat), chat)

    def test_exhibit_through_group_message_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.sqlite"
            db.initialize(path)
            db.demo(path, ("one", "two"))
            with db.closing_db(path) as conn:
                def say(text, seq, group):
                    event = engine.receive(conn, "sim-account", group, "player", str(seq),
                                           {"text": text}, now=100 + seq)
                    engine.step(conn)
                    row = conn.execute("SELECT body FROM outbox JOIN inbox ON biz=event_id WHERE seq=?",
                                       (event,)).fetchone()
                    return row[0] if row else None

                conn.execute("INSERT INTO chat_models VALUES('two',1,'glm','fixture',?,100)", (b"fixture",))
                conn.execute("INSERT INTO smart_controls(grp,enabled,generation) VALUES('two',1,1)")
                for index, group in enumerate(("one", "two")):
                    number = 17 + index
                    seq = 10 * index
                    conn.execute("INSERT INTO fishing_wallets(grp,member) VALUES(?,'player')", (group,))
                    conn.execute("""INSERT INTO fishing_pond(id,grp,member,fish,grams,price,storage)
                                    VALUES(?,?,'player','鲫鱼',125,3,'bag')""", (number,group))
                    self.assertIn(f"二狗批量点亮图鉴#{number}", say("二狗收入图鉴", seq+1, group))
                    self.assertIn(f"二狗卖鱼#{number}", say(f"二狗卖鱼#{number}？", seq+4, group))
                    self.assertIsNone(say(f"收入图鉴#{number}", seq+2, group))
                    result = say(f"二狗收入图鉴#{number}", seq+3, group)
                    self.assertIn("已点亮", result)
                    self.assertEqual(result, say(f"二狗收入图鉴#{number}", seq+3, group))
                    self.assertEqual(conn.execute("SELECT item_id FROM fishing_exhibits WHERE grp=?",
                                                  (group,)).fetchone()[0], number)
                    self.assertIsNone(conn.execute("SELECT 1 FROM fishing_pond WHERE id=?", (number,)).fetchone())
                self.assertIsNone(conn.execute("SELECT 1 FROM chat_requests").fetchone())
                prompt = "不要收入图鉴#17"
                self.assertIn("没看懂这个指令",say("二狗" + prompt, 20, "two"))
                self.assertIsNone(conn.execute("SELECT 1 FROM chat_requests").fetchone())
