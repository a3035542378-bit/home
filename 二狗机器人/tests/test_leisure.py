import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ergou import db, engine, leisure, queries


class Leisure(unittest.TestCase):
    def setUp(self):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))/"robot.sqlite"
        db.initialize(path)
        db.demo(path,("private-room",))
        self.db=self.enterContext(db.closing_db(path))
        self.n=0

    def say(self,text):
        self.n+=1
        seq=engine.receive(self.db,"sim-account","private-room","private-member",str(self.n),{"text":text})
        self.assertTrue(engine.step(self.db))
        return seq

    def reply(self,seq):
        row=self.db.execute("SELECT o.body FROM inbox i LEFT JOIN outbox o ON o.biz=i.event_id WHERE i.seq=?",(seq,)).fetchone()
        return row[0]

    def test_music_and_recipes_without_network(self):
        with patch.object(leisure.bulletins,"public_get",side_effect=AssertionError("Unexpected network request")):
            song="A+B & 小调"
            result=self.reply(self.say("二狗帮我点一首"+song))
            link=urlsplit(result.splitlines()[-1])
            self.assertEqual((link.scheme,link.hostname,parse_qs(link.query)),("https","music.apple.com",{"term":[song]}))
            self.assertIn("做法",self.reply(self.say("二狗菜谱：西红柿炒蛋")))
            self.assertIn("青椒炒蛋",self.reply(self.say("二狗查菜谱 鸡蛋")))
            self.assertIn("本地菜谱还没有",self.reply(self.say("二狗菜谱 不存在的菜")))

    def test_explicit_song_request_in_api_mode(self):
        with patch("ergou.models.api_first",return_value=True),patch("ergou.models.submit") as model:
            seq=self.say("二狗 点歌 周杰伦 晴天")
            self.assertIn("music.apple.com",self.reply(seq))
            model.assert_not_called()
            self.say("二狗 点歌是什么意思")
            model.assert_not_called()

    def test_live_music_creates_one_share_for_the_original_event(self):
        args=("sim-account","private-room","private-member","card-1",{"text":"二狗点歌 周杰伦 晴天"})
        for _ in range(2):
            engine.receive(self.db,*args,adapter_version="agent-wechat-events/2.7.1")
            engine.step(self.db)
        rows=self.db.execute("SELECT title,url,body FROM music_search_cards JOIN outbox ON task=id").fetchall()
        self.assertEqual(len(rows),1)
        title,url,body=rows[0]
        self.assertEqual(title,"周杰伦 晴天")
        self.assertEqual(url,body.splitlines()[-1])
        self.assertEqual(parse_qs(urlsplit(url).query),{"term":[title]})

    def test_wikipedia_receipt_and_metadata(self):
        seq=self.say("二狗查百科 小熊猫")
        self.assertIsNone(self.reply(seq))
        def get(url,limit,timeout,*,user_agent):
            self.assertFalse(self.db.in_transaction)
            parsed=urlsplit(url)
            self.assertEqual((parsed.hostname,parsed.path),("zh.wikipedia.org","/w/api.php"))
            self.assertEqual(parse_qs(parsed.query)["titles"],["小熊猫"])
            self.assertNotIn("private-",url+user_agent)
            return json.dumps({"query":{"pages":[{"pageid":42,"title":"小熊猫","extract":"一段简介。"}]}}).encode()
        with patch.object(leisure.bulletins,"public_get",side_effect=get):
            self.assertTrue(queries.work(self.db))
            self.assertFalse(queries.work(self.db))
        self.assertIn("一段简介。",self.reply(seq))
        self.assertIn("https://zh.wikipedia.org/?curid=42",self.reply(seq))
        self.assertEqual(tuple(self.db.execute("SELECT state,argument FROM queries").fetchone()),("DONE",None))
        self.assertIsNone(self.reply(self.say("大家在查百科 小熊猫")))

    def test_no_match_failure_and_bad_response(self):
        missing=b'{"query":{"pages":[{"missing":true,"title":"not found"}]}}'
        found=b'{"query":{"pages":[{"pageid":2,"title":"related"}]}}'
        with patch.object(leisure.bulletins,"public_get",side_effect=[missing,found]) as get:
            self.assertIn("相关条目",leisure.encyclopedia("主题",time.monotonic()+4))
            self.assertEqual(parse_qs(urlsplit(get.call_args.args[0]).query)["gsrsearch"],["主题"])
        with patch.object(leisure.bulletins,"public_get",return_value=b'{"batchcomplete":true}'):
            response=leisure.encyclopedia("带 & 空格",time.monotonic()+4)
            self.assertIn("暂未找到",response)
            self.assertEqual(parse_qs(urlsplit(response.splitlines()[-1]).query)["search"],["带 & 空格"])
        with patch.object(leisure.bulletins,"public_get",return_value=b'{"unexpected":123}'):
            with self.assertRaisesRegex(queries.ProviderError,"数据格式"):
                leisure.encyclopedia("熊猫",time.monotonic()+4)
        seq=self.say("二狗百科 熊猫")
        with patch.object(leisure.bulletins,"public_get",side_effect=queries.ProviderError("外部请求超时")):
            queries.work(self.db)
        self.assertIn("超时",self.reply(seq))
        self.assertEqual(tuple(self.db.execute("SELECT state,argument FROM queries").fetchone()),("FAILED",None))
