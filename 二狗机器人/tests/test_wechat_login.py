import json
import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ergou import admin, web, wechat_login
from ergou.db import closing_db, initialize


class FakePlugin(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def call(self):
        s = self.server
        # 关闭短连接前读完请求体，否则分开发送的 POST 正文可能使响应被 TCP 重置。
        if self.command == "POST":
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.headers.get("Authorization") != "Bearer fixture-login":
            self.send_error(403)
            return
        prefix = "/v1/accounts/ergou-listener"
        if self.path == prefix:
            data = {"id": s.slot, "authenticated": s.online, "connection": "online" if s.online else "offline",
                    "ownUsername": "fixture-user"}
        elif self.path == prefix + "/login-attempts" and self.command == "POST":
            key = self.headers["Idempotency-Key"]
            s.keys.append(key)
            if key not in s.operations:
                s.operations[key] = "attempt-" + str(len(s.operations) + 1)
            s.attempt = s.operations[key]
            s.state = "awaiting_scan"
            data = self.operation()
            if s.drop:
                s.drop = False
                self.close_connection = True
                return
        elif self.path == prefix + "/login-attempts/" + s.attempt:
            data = self.operation()
        elif self.path == prefix + "/login-attempts/" + s.attempt + "/cancel" and self.command == "POST":
            s.state = "cancelled"
            data = self.operation()
        elif self.path == prefix + "/login-attempts/" + s.attempt + "/qr?generation=1":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(wechat_login.PNG + b"test pixels")
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def operation(self):
        return {"accountId": self.server.slot, "id": self.server.attempt, "kind": "login",
                "state": self.server.state, "result": {"qrAvailable": True, "qrGeneration": 1,
                                                       "sensitiveFixtureField": "do-not-proxy"}}

    do_GET = do_POST = call


class WechatLoginTests(unittest.TestCase):
    def serve(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)

    def setUp(self):
        self.profile = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.profile / "ergou-login-token").write_text("fixture-login", encoding="utf-8")
        self.plugin = ThreadingHTTPServer(("127.0.0.1", 0), FakePlugin)
        self.plugin.state, self.plugin.attempt, self.plugin.slot = "", "", "ergou-listener"
        self.plugin.operations, self.plugin.keys = {}, []
        self.plugin.online = self.plugin.drop = False
        self.serve(self.plugin)
        self.enterContext(patch.dict(os.environ, {"ERGOU_WECHAT_PRIVATE_DIR": str(self.profile),
            "ERGOU_WECHAT_SLOT": self.plugin.slot, "ERGOU_WECHAT_PORT": str(self.plugin.server_port)}))
        self.user = {"role": "系统管理员"}

    def test_lost_start_and_repeated_start_resume_same_operation(self):
        self.plugin.drop = True
        with self.assertRaisesRegex(ValueError, "无法连接"):
            wechat_login.action(self.user, {"action": "start"})
        self.assertEqual(wechat_login.status(self.user)["state"], "retry_start")
        recovered = wechat_login.action(self.user, {"action": "start"})
        repeated = wechat_login.action(self.user, {"action": "start"})
        self.assertEqual(recovered, repeated)
        self.assertEqual(len(self.plugin.keys), 2)
        self.assertEqual(len(set(self.plugin.keys)), 1)
        self.assertNotIn("do-not-proxy", repr(recovered))
        record = wechat_login.LoginPlugin().load()
        self.assertEqual(set(record), {"key", "created", "attempt"})
        with self.assertRaisesRegex(ValueError, "失效"):
            wechat_login.qr(self.user, "old-attempt", "1")
        with self.assertRaisesRegex(ValueError, "失效"):
            wechat_login.qr(self.user, recovered["attempt"], "2")
        self.assertTrue(wechat_login.qr(self.user, recovered["attempt"], "1").startswith(wechat_login.PNG))
        self.plugin.state = "awaiting_approval"
        self.assertEqual(wechat_login.status(self.user)["generation"], 0)
        with self.assertRaisesRegex(ValueError, "失效"):
            wechat_login.qr(self.user, recovered["attempt"], "1")

    def test_cancel_expire_retry_and_online_never_replaces_login(self):
        first = wechat_login.action(self.user, {"action": "start"})
        with self.assertRaisesRegex(ValueError, "变更"):
            wechat_login.action(self.user, {"action": "cancel", "attempt": "stale"})
        self.assertEqual(wechat_login.action(self.user, {"action": "cancel", "attempt": first["attempt"]})["state"], "cancelled")
        next_op = wechat_login.action(self.user, {"action": "start"})
        self.assertNotEqual(first["attempt"], next_op["attempt"])
        self.plugin.state = "expired"
        self.assertEqual(wechat_login.status(self.user)["state"], "expired")
        self.assertEqual(wechat_login.status(self.user)["generation"], 0)
        self.plugin.online = True
        self.assertEqual(wechat_login.status(self.user), {"state": "online", "account": "fixture-user"})
        wechat_login.action(self.user, {"action": "start"})
        self.assertEqual(len(self.plugin.operations), 2)

    def test_account_identity_and_permission_fail_closed(self):
        self.plugin.slot = "wrong-slot"
        with self.assertRaisesRegex(ValueError, "身份"):
            wechat_login.action(self.user, {"action": "start"})
        for call in (lambda: wechat_login.status({"role":"运营管理员"}),
                     lambda: wechat_login.action(None, {"action":"start"}),
                     lambda: wechat_login.qr({"role":"群管理员"}, "attempt-1", "1")):
            with self.assertRaises(PermissionError):
                call()
        self.assertFalse(self.plugin.keys)

    def test_native_start_and_confirmation_transitions(self):
        native = wechat_login.LoginPlugin()
        op = {"kind": "login", "id": "login-1", "accountId": native.slot, "result": {}}
        for state in ("starting", "resuming", "authenticating"):
            self.assertEqual(wechat_login._operation(native, dict(op, state=state))["state"], state)
        op["result"] = {"lanChallenge": "waiting_for_phone", "other": "private"}
        self.assertIn("局域网", wechat_login._operation(native, dict(op, state="awaiting_approval"))["hint"])
        self.assertNotIn("private", repr(wechat_login._operation(native, dict(op, state="awaiting_approval"))))

    def test_http_qr_requires_session_and_is_never_cached(self):
        dbfile = self.profile / "web.sqlite"
        initialize(dbfile)
        with closing_db(dbfile) as db:
            admin.user(db, "qr-admin", "fixture-password", "系统管理员", [])
            admin.user(db, "qr-reader", "fixture-password", "只读人员", [])
            tokens = {name: admin.login(db, name, "fixture-password", "fixture") for name in ("qr-admin", "qr-reader")}
        server = web.server(dbfile, 0)
        self.serve(server)

        def request(suffix="", data=None, name=None):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=4)
            headers = {"Content-Type": "application/json"}
            if name:
                headers["Cookie"] = "session=" + tokens[name]
            try:
                conn.request("GET" if data is None else "POST", "/api/wechat-login" + suffix,
                             None if data is None else json.dumps(data), headers)
                response = conn.getresponse()
                return response.status, response.headers, response.read()
            finally:
                conn.close()

        self.assertEqual(request(data={"action":"start"})[0], 401)
        self.assertEqual(request(data={"action":"start"}, name="qr-reader")[0], 403)
        status, _, body = request(data={"action":"start"}, name="qr-admin")
        self.assertEqual(status, 200)
        img = "/qr?attempt=" + json.loads(body)["attempt"] + "&generation=1"
        self.assertEqual(request(img)[0], 401)
        self.assertEqual(request(img, name="qr-reader")[0], 403)
        status, headers, body = request(img, name="qr-admin")
        self.assertEqual((status, headers.get_content_type(), headers["Cache-Control"]), (200, "image/png", "no-store"))
        self.assertTrue(body.startswith(wechat_login.PNG))
