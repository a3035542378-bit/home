import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import threading
import unittest

from ergou import bridge, jobs, web
from ergou.db import closing_db, initialize
from ergou.engine import step


class WechatyListener(unittest.TestCase):
    @unittest.skipUnless(os.getenv("ERGOU_SDK_HOST"), "optional Wechaty SDK installation")
    def test_upstream_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sdk.sqlite"
            initialize(path)
            secret = secrets.token_urlsafe(32)
            with closing_db(path) as db, web.server(path, 0) as httpd:
                bridge.enroll(db, "sdk-account", "sdk-room", secret, listen_only=True)
                thread = threading.Thread(target=httpd.serve_forever)
                thread.start()
                try:
                    script = Path(__file__).resolve().with_name("wechaty-sdk.mjs")
                    result = subprocess.run([shutil.which("node"), str(script), str(httpd.server_port)],
                                            env=os.environ | {"ERGOU_NODE_SECRET": secret}, cwd=folder,
                                            capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(0, result.returncode, result.stderr)
                finally:
                    httpd.shutdown()
                    thread.join()
                source = next(line[7:] for line in result.stdout.splitlines() if line.startswith("SOURCE="))
                self.assertTrue(source)
                self.assertEqual(("sdk-room", "sdk-member", source),
                                 tuple(db.execute("SELECT grp,member,source FROM inbox").fetchone()))
                self.assertTrue(step(db))
                self.assertEqual(1, db.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                self.assertEqual(0, db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the Wechaty plugin")
    def test_callback_through_http_and_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.sqlite"
            initialize(path)
            secret = secrets.token_urlsafe(32)
            account, group = "fixture-account", "fixture-room"
            with closing_db(path) as db:
                bridge.enroll(db, account, group, secret, listen_only=True)
                httpd = web.server(path, 0)
                thread = threading.Thread(target=httpd.serve_forever)
                thread.start()
                try:
                    subprocess.run([shutil.which("node"), str(Path(__file__).with_name("wechaty-callback.mjs")),
                                    str(httpd.server_port), group, account], check=True, timeout=20,
                                   env=os.environ | {"ERGOU_NODE_SECRET": secret})
                finally:
                    httpd.shutdown()
                    thread.join()
                    httpd.server_close()
                self.assertEqual("LISTENING", db.execute("SELECT state FROM account").fetchone()[0])
                rows = db.execute("SELECT grp,member,source FROM inbox ORDER BY seq")
                self.assertEqual([(group, "member-200", "message-100"), (group, "member-200", "message-101")],
                                 list(map(tuple, rows)))
                while step(db):
                    pass
                self.assertEqual(1, db.execute("SELECT COUNT(*) FROM games").fetchone()[0])
                self.assertEqual(0, db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
                for op in ("claim", "result"):
                    with self.assertRaises(PermissionError):
                        bridge.endpoint(db, op, secret, {})
                with self.assertRaises(ValueError):
                    bridge.enroll(db, account, group, secret)
                now = db.execute("SELECT last_seen FROM nodes").fetchone()[0]
                jobs.tick(db, now + 31)
                self.assertEqual("RECONNECTING", db.execute("SELECT state FROM account").fetchone()[0])
