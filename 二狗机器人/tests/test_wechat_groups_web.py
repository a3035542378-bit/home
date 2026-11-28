import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from ergou import db, wechat_groups


class WebGroupsTests(TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, CREDENTIALS_DIRECTORY=str(root)))
        (root / "ergou-node-secret").write_text("fixture" * 8)
        db.initialize(root / "app.db")
        self.db = self.enterContext(db.closing_db(root / "app.db"))
        self.client = Mock(slot="slot", base="/v1/accounts/slot")
        self.client.identity.return_value = "bot"
        self.client.member.return_value = True
        self.data = dict(group="a@chatroom", account="bot", server="server")
        self.client.get.side_effect = lambda path: (
            {"serverId": "server"} if path == "/v1/status" else
            {"asOfEventCursor": "25"} if "/members?" in path else
            {"id": self.data["group"], "displayName": "同名群"})

    def bind(self):
        return wechat_groups.bind(self.db,self.client,self.data,{"name":"admin"})

    def test_first_second_and_repeat(self):
        self.bind()
        self.bind()
        self.data["group"] = "b@chatroom"
        self.bind()
        self.assertEqual(self.db.execute("select count(*) from directed_groups").fetchone()[0],2)
        self.assertEqual(self.db.execute("select count(*) from binding_streams").fetchone()[0],1)

    def test_stale_login_and_lost_membership(self):
        self.client.identity.return_value = "other"
        with self.assertRaises(ValueError):
            self.bind()
        self.client.identity.return_value = "bot"
        self.client.member.return_value = False
        with self.assertRaises(ValueError):
            self.bind()
        self.assertFalse(self.db.execute("select 1 from binding_streams").fetchone())

    def test_admin_only(self):
        with self.assertRaises(PermissionError):
            wechat_groups.service({"role":"群管"})
