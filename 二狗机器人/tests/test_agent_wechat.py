from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from ergou import agent_wechat as aw
from ergou.db import closing_db, initialize
from ergou.engine import step


class Fixture(aw.Client):
    def __init__(self):
        super().__init__(6174, "test-slot", "test-token")
        self.room = "test@chatroom"
        self.reads = []
        self.details = dict(threadId=self.room, accountId=self.slot, id="upstream-row", serverId="9712345678901234567",
                            senderId="member", direction="incoming", type=1, body="二狗 开始 成语接龙")
        self.account = "account"
        self.member_state = "present"

    def get(self, path):
        self.reads.append(path)
        route = urlsplit(path).path
        if route == "/v1/status":
            return {"serverId": "daemon-id"}
        if route == self.base:
            return dict(id=self.slot, authenticated=True, connection="online", ownUsername=self.account)
        if route.endswith("/groups"):
            return dict(items=[dict(id=self.room,name="测试群")], coverage={"partial": False}, asOfEventCursor="12")
        if route.endswith("/groups/test%40chatroom"):
            return dict(id=self.room, isInGroup=None)
        if route.endswith("/groups/test%40chatroom/members"):
            return dict(items=[], nextCursor=None, asOfEventCursor="12")
        if "/members/" in route:
            return dict(groupId=self.room, username=self.account, state=self.member_state, member={"id":self.account})
        if route.endswith("/messages/upstream-row"):
            return self.details
        raise AssertionError(path)


class AgentWechat(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(root) / "robot.sqlite"
        initialize(self.path)
        self.db = self.enterContext(closing_db(self.path))
        self.api = Fixture()
        self.secret = "a" * 40
        aw.link(self.db, self.api, "测试群", self.secret)
        self.listener = aw.Listener(self.db, self.api, self.secret)
        self.listener.verify()

    def event(self, cursor, **overrides):
        return dict(cursor=str(cursor), kind="message.committed",
                    data=dict(threadId=self.api.room, messageId="upstream-row", origin="live",
                              direction="incoming") | overrides)

    def test_resume_and_filter_before_read(self):
        self.api.reads.clear()
        self.listener.consume(self.event(13, threadId="private"))
        self.listener.consume(self.event(14, origin="history"))
        self.listener.consume(self.event(15, direction="outgoing"))
        self.assertEqual([], self.api.reads)
        self.listener.consume(self.event(16))
        self.assertEqual(1, len(self.api.reads))
        self.assertTrue(step(self.db))
        self.db.execute("UPDATE agent_wechat_links SET cursor='15'")  # lost checkpoint after inbox commit
        again = aw.Listener(self.db, self.api, self.secret)
        again.consume(self.event(16))
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM games").fetchone()[0])
        self.assertEqual(("9712345678901234567","DONE"), tuple(self.db.execute("SELECT source,state FROM inbox").fetchone()))
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
        aw.link(self.db, self.api, "测试群", self.secret, after="0")
        self.assertEqual("16", self.db.execute("SELECT cursor FROM agent_wechat_links").fetchone()[0])

    def test_mismatched_detail_and_membership(self):
        self.api.details["threadId"] = "different@chatroom"
        with self.assertRaises(ValueError):
            self.listener.consume(self.event(13))
        self.assertEqual("12", self.listener.cursor)
        self.api.member_state = "unconfirmed"
        with self.assertRaises(ValueError):
            self.listener.verify()
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0])

    def test_expiry_signals_from_upstream(self):
        client = aw.Client(6174, self.api.slot, "fixture-token")
        error = b'{"error":{"code":"event_cursor_expired","retryable":false}}'
        with patch("ergou.agent_wechat.http.client.HTTPConnection") as factory:
            conn = factory.return_value
            conn.getresponse.return_value.status = 410
            conn.getresponse.return_value.read.return_value = error
            with self.assertRaises(aw.CursorExpired):
                list(client.events("12"))
            conn.close.assert_called_once()
        response = Mock()
        response.getheader.return_value = "text/event-stream"
        response.readline.side_effect = [b"event: error\n", b"data: " + error + b"\n", b"\n"]
        with patch.object(client, "connect", return_value=(Mock(), response)), self.assertRaises(aw.CursorExpired):
            list(client.events("12"))

    def test_recover_from_oldest_retained_event(self):
        def page(after):
            if after < 39:
                raise aw.CursorExpired("expired")
            return [{"cursor": str(after + 1)}] if after < 50 else []
        with (patch.object(self.api, "resolve", return_value=(self.api.room, "50")),
              patch.object(self.api, "next_events", side_effect=page)):
            self.api.member_state = "unconfirmed"
            with self.assertRaises(ValueError):
                self.listener.recover_expired()
            self.assertEqual("12", self.listener.cursor)
            self.api.member_state = "present"
            self.listener.recover_expired()
        self.assertEqual("39", self.db.execute("SELECT cursor FROM agent_wechat_links").fetchone()[0])
        info = self.db.execute("SELECT detail FROM audit WHERE action='事件采集缺口'").fetchall()
        self.assertEqual(1, len(info))
        self.assertIn("13 至 39", info[0][0])
        self.listener.consume(self.event(40))
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0])

    def test_duplicate_process_cannot_overwrite_heartbeat(self):
        code = """import os, sys
from ergou.agent_wechat import listener_lock
from ergou.db import closing_db
with closing_db(sys.argv[1]) as db, listener_lock(db, sys.argv[2]):
    print('ready', flush=True)
    sys.stdin.readline()
    os._exit(73)
"""
        with subprocess.Popen([sys.executable, "-c", code, str(self.path), self.api.slot],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
            try:
                self.assertEqual("ready", child.stdout.readline().strip())
                with self.assertRaisesRegex(RuntimeError, "已有监听进程"):
                    self.listener.run()
                self.assertEqual("LISTENING", self.db.execute("SELECT state FROM account").fetchone()[0])
                self.assertEqual("12", self.db.execute("SELECT cursor FROM agent_wechat_links").fetchone()[0])
            finally:
                child.stdin.write("\n")
                child.stdin.flush()
                child.wait(timeout=10)
        self.assertEqual(73, child.returncode)
        with aw.listener_lock(self.db, self.api.slot):
            self.listener.verify()
