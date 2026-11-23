"""隔离微信入站、发件任务和原生提及回读。"""
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ergou import agent_wechat as aw, db, engine, jobs
from tests.test_agent_wechat import Fixture


class JianghuMentions(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "room.sqlite"
        db.initialize(path)
        self.conn = self.enterContext(db.closing_db(path))
        self.api = Fixture()
        secret = "fixture" * 8
        aw.link(self.conn, self.api, "测试群", secret)
        self.listener = aw.Listener(self.conn, self.api, secret)
        self.listener.verify()
        self.conn.execute("INSERT INTO directed_groups VALUES(?,?,1,?)",
                          (self.api.room, self.api.account, time.time() - 30))
        self.conn.execute("INSERT INTO jh_group_config VALUES(?,1,1)", (self.api.room,))
        self.conn.execute("UPDATE groups SET config=json_set(config,'$.send_rate',30) WHERE id=?", (self.api.room,))
        self.seq = 12

    def say(self, cmd, targets=()):
        self.seq += 1
        self.api.details.update(body=cmd, serverId=str(self.seq), senderId="player-a",
                                createdAt=datetime.now(timezone.utc).isoformat(),
                                mentions={"state": "known", "userIds": list(targets)})
        self.listener.consume(dict(cursor=str(self.seq), kind="message.committed", data=dict(
            threadId=self.api.room, messageId=self.api.details["id"], origin="live", direction="incoming")))
        engine.step(self.conn)
        task = jobs.claim(self.conn, self.api.account, directed_group=self.api.room)
        self.assertIsInstance(task, dict)
        jobs.finish(self.conn, self.api.account, task["id"], task["attempt"], "ACKNOWLEDGED", "fixture")
        return task

    def test_personal_help_and_duel_addressing(self):
        self.assertEqual(aw.reply_mentions(self.say("二狗江湖帮助")), ["player-a"])
        self.assertEqual(aw.reply_mentions(self.say("二狗闯江湖")), ["player-a"])
        for who, route in (("player-a", "拳"), ("player-b", "剑")):
            self.conn.execute("""INSERT INTO jh_players
                (grp,member,identity,strength,agility,constitution,insight,luck,title,route,first_win_at)
                VALUES(?,?,'平民',20,20,20,20,5,'踏实练家子',?,?)""",
                              (self.api.room, who, route, time.time()))
        story = self.say("二狗江湖故事")
        self.assertIn("渡口相见", story["body"])
        self.assertNotIn("送了你一把铁剑", story["body"])
        self.assertEqual(aw.reply_mentions(story), ["player-a"])
        self.assertEqual(aw.reply_mentions(self.say("二狗切磋 @乙")), ["player-a"])
        original = self.api.get
        def read(path):
            if path.endswith("/members/player-b"):
                return {"groupId": self.api.room, "username": "player-b", "state": "present",
                        "member": {"username": "player-b", "roomDisplayName": "阿乙"}}
            return original(path)
        with patch.object(self.api, "get", side_effect=read):
            invite = self.say("二狗切磋 @阿乙", ["player-b"])
            self.assertIn("阿乙收到了", invite["body"])
            self.assertEqual(aw.reply_mentions(invite), ["player-a", "player-b"])
            self.assertEqual(aw.reply_mentions(self.say("二狗切磋 @阿乙", ["player-b"])), ["player-a"])

        intent = dict(accountId=self.api.slot, destination=self.api.room, state="accepted",
                      localMessageId="m", serverId="123")
        message = dict(id="m", accountId=self.api.slot, threadId=self.api.room, direction="outgoing",
                       type=1, serverId="123", body="@甲\u2005@阿乙\u2005"+invite["body"],
                       mentions={"state": "known", "all": False, "userIds": ["player-b", "player-a"]})
        client = aw.Client(self.api.port, self.api.slot, "fixture")
        with patch.object(aw.Client, "get", side_effect=[intent, message]), patch.object(aw.http.client, "HTTPConnection") as http:
            conn = http.return_value
            conn.getresponse.return_value.status = 202
            self.assertEqual(aw.send_direct(client, "fixture", invite)[0], "ACKNOWLEDGED")
            payload = json.loads(conn.request.call_args.kwargs["body"])
            self.assertEqual(payload["mentions"]["userIds"], ["player-a", "player-b"])
        message["mentions"]["userIds"] = ["player-a"]
        with patch.object(aw.Client, "get", side_effect=[intent, message]):
            self.assertEqual(aw.inspect_text_send(client, "fixture", invite, timeout=0)[0], "UNKNOWN")
