import http.client
import json
import secrets
import tempfile
import threading
import unittest
from pathlib import Path

from ergou import admin, admin_accounts, web
from ergou.db import closing_db, demo, initialize


class AdminAccountTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "accounts.sqlite"
        self.path = path
        initialize(path)
        demo(path, ("home", "work"))
        self.db = self.enterContext(closing_db(path))
        self.owner = dict(name="owner", role="系统管理员", scopes="[]")
        self.fields = dict(name="operator", password=secrets.token_urlsafe(20),
                           role="运营管理员", scopes=["home"])

    def test_creation_produces_real_scoped_login_and_sanitized_list(self):
        self.db.execute("INSERT INTO group_profile(grp,alias) VALUES('home','家庭群')")
        result = admin_accounts.create(self.db, self.owner, self.fields)
        self.assertEqual(result["accounts"], [dict(name="operator", role="运营管理员", scopes=["home"])])
        self.assertIn(dict(id="home", name="家庭群"), result["groups"])
        token = admin.login(self.db, "operator", self.fields["password"], "local")
        operator = admin.identity(self.db, token)
        admin.permitted(operator, "home", True)
        with self.assertRaises(PermissionError):
            admin.permitted(operator, "work", True)
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            admin_accounts.create(self.db, self.owner, dict(self.fields, role="系统管理员", scopes=[]))
        log = [tuple(row) for row in self.db.execute("SELECT actor,action,detail FROM audit")]
        self.assertEqual(log, [("owner", "创建后台用户", "operator")])
        self.assertNotIn(self.fields["password"], str(result) + str(log))

    def test_management_is_restricted_to_authenticated_system_administrator(self):
        for actor in [None] + [dict(self.owner, role=role) for role in admin.ROLES[1:]]:
            with self.subTest(actor=actor), self.assertRaises(PermissionError):
                admin_accounts.view(self.db, actor)
            with self.subTest(actor=actor), self.assertRaises(PermissionError):
                admin_accounts.create(self.db, actor, dict(self.fields, role="系统管理员", scopes=[]))
        self.assertEqual(admin_accounts.view(self.db, self.owner)["accounts"], [])

    def test_validates_roles_scopes_and_standard_password_length(self):
        for patch in [
            dict(name="  "), dict(password=secrets.token_hex(3)), dict(role="root"), dict(scopes="home"),
            dict(scopes=[]), dict(scopes=["missing"]), dict(scopes=["work", ["home"]]),
            dict(role="系统管理员"), dict(actor="somebody"),
        ]:
            with self.subTest(fields=patch.keys()), self.assertRaises(ValueError):
                admin_accounts.create(self.db, self.owner, dict(self.fields, **patch))
        self.assertFalse(admin_accounts.view(self.db, self.owner)["accounts"])

    def test_bootstrap_is_local_short_password_exception_and_is_idempotent(self):
        password = secrets.token_hex(3)
        with self.assertRaises(ValueError):
            admin.user(self.db, "admin", password, "系统管理员", [])
        self.assertTrue(admin_accounts.bootstrap(self.db, password))
        stored = self.db.execute("SELECT password FROM users WHERE name='admin'").fetchone()[0]
        self.assertNotEqual(stored, password)
        self.assertFalse(admin_accounts.bootstrap(self.db, secrets.token_urlsafe(20)))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)
        token = admin.login(self.db, "admin", password, "local")
        self.assertEqual(admin.identity(self.db, token)["role"], "系统管理员")

    def test_bootstrap_preserves_conflicting_migrated_account(self):
        admin.user(self.db, "admin", self.fields["password"], "只读人员", ["work"])
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            admin_accounts.bootstrap(self.db, secrets.token_urlsafe(20))
        token = admin.login(self.db, "admin", self.fields["password"], "local")
        self.assertEqual(admin.identity(self.db, token)["role"], "只读人员")

    def test_account_management_through_authenticated_http(self):
        admin_accounts.bootstrap(self.db, self.fields["password"])
        server = web.server(self.path, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)

        def request(path, data=None, cookie=""):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.request("POST" if data is not None else "GET", path,
                             json.dumps(data) if data is not None else None,
                             {"Content-Type": "application/json", "Cookie": cookie})
                response = conn.getresponse()
                return response.status, json.loads(response.read()), response.getheader("Set-Cookie", "").split(";")[0]
            finally:
                conn.close()

        path = "/api/admin-accounts"
        self.assertEqual(request(path)[0], 401)
        status, _, owner = request("/api/login", dict(name="admin", password=self.fields["password"]))
        self.assertEqual(status, 200)
        status, result, _ = request(path, self.fields, owner)
        self.assertEqual(status, 201)
        self.assertTrue(any(item["name"] == "operator" for item in result["accounts"]))
        self.assertEqual(request(path, self.fields, owner)[0], 409)
        status, _, operator = request("/api/login", dict(name="operator", password=self.fields["password"]))
        self.assertEqual(status, 200)
        self.assertEqual(request(path, cookie=operator)[0], 403)
        self.assertEqual(request(path, dict(self.fields, role="系统管理员", scopes=[]), operator)[0], 403)
        self.assertEqual(request("/api/me", cookie=operator)[1]["groups"], ["home"])
