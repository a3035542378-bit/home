import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ergou import bridge, weflow
from ergou.db import closing_db, initialize
from ergou.engine import step


class WeFlow(unittest.TestCase):
    group = "fixture@chatroom"
    account = "fixture-owner"
    secret = "node-test-" * 4
    now = 1780000000

    def setUp(self):
        self.calls = []
        self.owner = self.account
        self.roster = [self.account, "member"]
        self.other_owner_page = False
        self.wrong_cursor = False
        self.names = [self.group]
        self.rows = [self.msg(20, "二狗 开始 成语接龙"), self.msg(21, "你好")]
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path, query = urlsplit(self.path).path, parse_qs(urlsplit(self.path).query)
                fixture.calls.append((path, query))
                if self.headers.get("Authorization") != "Bearer fixture-token":
                    self.send_error(403)
                    return
                if path == "/api/v1/sessions":
                    result = {"success": True, "sessions": [
                        {"displayName": "测试群", "username": name} for name in fixture.names]}
                elif path == "/api/v1/group-members":
                    result = {"success": True, "chatroomId": query["chatroomId"][0],
                              "members": [{"wxid": user} for user in fixture.roster]}
                elif path == "/api/v1/sessions/fixture%40chatroom/messages":
                    offset = int(query["offset"][0])
                    chunk = fixture.rows[offset:offset + 1]
                    result = {"meta": {"groupId": fixture.group, "type": "group",
                                       "ownerId": "other" if offset and fixture.other_owner_page else fixture.owner},
                              "messages": chunk,
                              "sync": {"hasMore": offset + len(chunk) < len(fixture.rows),
                                       "nextOffset": offset if fixture.wrong_cursor else offset + len(chunk)}}
                else:
                    self.send_error(404)
                    return
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.source = weflow.Source(self.server.server_port, "fixture-token")
        folder = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(folder) / "test.sqlite"
        initialize(path)
        self.db = self.enterContext(closing_db(path))
        bridge.enroll(self.db, self.account, self.group, self.secret, listen_only=True)
        self.listener = weflow.Listener(self.db, self.source, self.account, self.group, self.secret, self.now)

    def msg(self, mid, content, **updates):
        return {"platformMessageId": str(mid), "type": 0, "timestamp": self.now,
                "sender": "member", "content": content} | updates

    def test_group_pages_replay_and_filters(self):
        self.rows += [self.msg(22, "自身", sender=self.account), self.msg(23, "图片", type=1),
                      self.msg(0, "无来源编号"), self.msg(25, "旧消息", timestamp=self.now-1),
                      self.msg(26, "无成员标识", sender="unknown_sender_0")]
        self.listener.poll(self.now)
        self.listener.poll(self.now + 3)
        rows = self.db.execute("SELECT source,member,grp FROM inbox ORDER BY seq")
        self.assertEqual([("20","member",self.group)], list(map(tuple, rows)))
        while step(self.db):
            pass
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM games").fetchone()[0])
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
        self.assertEqual({"/api/v1/group-members", "/api/v1/sessions/fixture%40chatroom/messages"},
                         {path for path, _ in self.calls})

    def test_group_resolution_and_auth(self):
        self.assertEqual(self.group, self.source.find_group("测试群"))
        self.names.append("other@chatroom")
        with self.assertRaisesRegex(weflow.SourceError, "唯一"):
            self.source.find_group("测试群")
        with self.assertRaisesRegex(weflow.SourceError, "403"):
            weflow.Source(self.server.server_port, "wrong").find_group("测试群")

    def test_failed_pages_and_session_change(self):
        self.wrong_cursor = True
        with self.assertRaisesRegex(weflow.SourceError, "分页"):
            self.listener.poll(self.now)
        self.wrong_cursor = False
        self.other_owner_page = True
        with self.assertRaisesRegex(weflow.SourceError, "账号"):
            self.listener.poll(self.now)
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0])
        self.other_owner_page = False
        self.listener.poll(self.now)
        self.roster.remove(self.account)
        self.listener.members_until = 0
        class Stop(Exception):
            pass
        def check_state(_):
            state = self.db.execute("SELECT state FROM account").fetchone()[0]
            self.assertEqual("NEED_USER_ACTION", state)
            self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM membership").fetchone()[0])
            raise Stop
        with patch("ergou.weflow.time.sleep", side_effect=check_state), self.assertRaises(Stop):
            self.listener.run()
        self.assertEqual("STOPPED", self.db.execute("SELECT state FROM account").fetchone()[0])
