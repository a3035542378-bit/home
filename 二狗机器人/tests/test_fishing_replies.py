import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ergou import agent_wechat as aw, db, engine, jobs
from tests.test_agent_wechat import Fixture


class FishingReplies(unittest.TestCase):
    def test_live_sender_and_balance(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "test.sqlite"
        db.initialize(path)
        conn = self.enterContext(db.closing_db(path))
        api = Fixture()
        secret = "x" * 40
        aw.link(conn, api, "测试群", secret)
        listener = aw.Listener(conn, api, secret)
        listener.verify()
        conn.execute("INSERT INTO directed_groups SELECT id, account, binding, ? FROM groups WHERE id=?",
                     (time.time()-1, api.room))

        def say(n, member, command, mentions=None):
            api.details.update(body=command, serverId=str(n), senderId=member, mentions=mentions or {},
                               createdAt=datetime.now(timezone.utc).isoformat())
            listener.consume(dict(cursor=str(n), kind="message.committed", data=dict(
                threadId=api.room, messageId=api.details["id"], origin="live", direction="incoming")))
            engine.step(conn)
            task = jobs.claim(conn, api.account, directed_group=api.room)
            self.assertIsInstance(task, dict)
            jobs.finish(conn, api.account, task["id"], task["attempt"], "ACKNOWLEDGED", "fixture")
            return task

        cast = say(13, "player-a", "二狗抛竿")
        self.assertEqual(cast["mention_sender"], "player-a")
        self.assertEqual("二狗查看鱼包", cast["body"].splitlines()[1])
        conn.execute("UPDATE fishing_pond SET price=6 WHERE grp=? AND member='player-a'", (api.room,))
        conn.execute("""INSERT INTO fishing_pond(grp,member,fish,grams,price,storage)
                        VALUES(?,'player-a','鲫鱼',208,8,'bag')""", (api.room,))
        sale = say(14, "player-a", "二狗卖出鱼包")
        self.assertEqual(sale["mention_sender"], "player-a")
        self.assertIn("卖出 2 条鱼\n到账 14 枚鱼币\n当前余额　44 鱼币", sale["body"])
        profile = say(15, "player-b", "二狗查看个人钓鱼信息")
        self.assertEqual(profile["mention_sender"], "player-b")
        self.assertIn("30 鱼币", profile["body"])
        self.assertIn("累计 0 竿", profile["body"])
        self.assertIsNone(conn.execute("SELECT 1 FROM fishing_wallets WHERE grp=? AND member='player-b'",
                                       (api.room,)).fetchone())
        raid = say(16, "player-b", "二狗偷鱼\u2005@甲", {"state":"known","userIds":["player-a"]})
        self.assertEqual(raid["mention_sender"], "player-b")
        self.assertIn("空空如也", raid["body"])
        self.assertIsNone(say(17, "player-b", "二狗菜单")["mention_sender"])

    def test_native_mention_and_readback(self):
        client = aw.Client(6174, "fixture", "read")
        task = dict(grp="g@chatroom", biz="one", body="卖出两条鱼", mention_sender="player")
        intent = dict(accountId=client.slot, destination=task["grp"], state="accepted",
                      localMessageId="m", serverId="123")
        message = dict(id="m", accountId=client.slot, threadId=task["grp"], direction="outgoing",
                       type=1, serverId="123", body="@群昵称\u2005"+task["body"],
                       mentions={"state":"known","all":False,"userIds":["player"]})
        with patch.object(aw.Client, "get", side_effect=[intent,message]), patch.object(aw.http.client,"HTTPConnection") as http:
            conn = http.return_value
            conn.getresponse.return_value.status = 202
            self.assertEqual(aw.send_direct(client,"send",task)[0], "ACKNOWLEDGED")
            self.assertEqual(json.loads(conn.request.call_args.kwargs["body"]),
                             {"threadId":task["grp"],"text":task["body"],"mentions":{"userIds":["player"]}})
        for mismatch in ({"body":"@群昵称\u2005不同正文"}, {"mentions":{"state":"known","userIds":["other"]}}):
            with self.subTest(mismatch=mismatch), patch.object(aw.Client,"get",side_effect=[intent,message|mismatch]):
                self.assertEqual(aw.inspect_text_send(client,"send",task,timeout=0)[0], "UNKNOWN")
