import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ergou import agent_wechat, bridge, monitor
from ergou.db import closing_db, demo, initialize
from tests.test_agent_wechat import Fixture
from tests.voice_credentials import verify_credential


class MonitorHealth(unittest.TestCase):
    def setUp(self):
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        database = base / "monitor.sqlite"
        initialize(database)
        demo(database, ("simulation",))
        self.db = self.enterContext(closing_db(database))
        self.owner = dict(name="owner", role="系统管理员", scopes="[]")
        self.api = Fixture()
        self.secret = "fixture-only-secret" * 3
        agent_wechat.link(self.db, self.api, "测试群", self.secret)
        agent_wechat.Listener(self.db, self.api, self.secret).verify()
        self.now = self.db.execute("SELECT last_seen FROM nodes WHERE account=?", (self.api.account,)).fetchone()[0]

    def grant_replies(self):
        self.db.execute("INSERT INTO directed_groups SELECT id,account,binding,? FROM groups WHERE id=?",
                        (self.now, self.api.room))

    def health(self):
        return monitor.group_health(self.db, self.api.room, self.now)

    def test_overview_counts_current_authorized_binding_and_visible_groups(self):
        self.assertEqual("listen_only", self.health()["mode"])
        self.assertEqual({"configured": 2, "serviceable": 1}, monitor.overview(self.db, self.owner))
        self.grant_replies()
        self.assertEqual("directed", self.health()["mode"])
        self.assertTrue(self.health()["directed"])
        self.assertEqual(self.now, self.health()["last_seen"])
        self.assertEqual({"configured": 2, "serviceable": 2}, monitor.overview(self.db, self.owner))
        scoped = dict(role="只读人员", scopes='["simulation"]')
        self.assertEqual({"configured": 1, "serviceable": 1}, monitor.overview(self.db, scoped))
        simulated = monitor.group_health(self.db, "simulation", self.now)
        self.assertEqual(("simulation", None, True), (simulated["mode"], simulated["last_seen"], simulated["serviceable"]))
        self.db.execute("UPDATE groups SET binding=binding+1 WHERE id=?", (self.api.room,))
        self.assertFalse(self.health()["directed"])
        self.assertFalse(self.health()["serviceable"])

    def test_missing_link_grant_or_join_does_not_count_as_a_working_group(self):
        self.grant_replies()
        for sql, mode in (("DELETE FROM membership WHERE grp=?", "not_joined"),
                          ("DELETE FROM agent_wechat_links WHERE grp=?", "listen_only"),
                          ("DELETE FROM node_grants WHERE grp=?", "ungranted"),
                          ("UPDATE groups SET paused=1 WHERE id=?", "paused"),
                          ("UPDATE groups SET config=json_set(config,'$.enabled',0) WHERE id=?", "disabled"),
                          ("INSERT INTO group_profile(grp,detached) VALUES(?,1)", "detached")):
            with self.subTest(mode=mode):
                self.db.execute("SAVEPOINT test_case")
                self.db.execute(sql, (self.api.room,))
                health = self.health()
                self.assertEqual(mode, health["mode"])
                self.assertFalse(health["serviceable"])
                self.db.execute("ROLLBACK TO test_case")
                self.db.execute("RELEASE test_case")

    def test_heartbeat_expires_at_thirty_seconds_and_offline_alert_recovers(self):
        self.grant_replies()
        self.assertTrue(monitor.group_health(self.db, self.api.room, self.now+29.99)["serviceable"])
        self.assertEqual("stale", monitor.group_health(self.db, self.api.room, self.now+30)["mode"])
        monitor.sample_alerts(self.db, self.now+30)
        self.db.execute("UPDATE nodes SET last_seen=? WHERE account=?", (self.now+31, self.api.account))
        monitor.sample_alerts(self.db, self.now+31)
        alert = self.db.execute("SELECT kind,opened,recovered FROM group_alert WHERE grp=?", (self.api.room,)).fetchone()
        self.assertEqual(("账号离线", self.now+30, self.now+31), tuple(alert))

    def test_regular_online_adapter_does_not_need_an_agent_wechat_slot(self):
        secret = "normal-adapter-token" * 2
        bridge.enroll(self.db, "regular", "another", secret)
        bridge.endpoint(self.db, "heartbeat", secret, dict(state="ONLINE", actual_account="regular",
                        groups=["another"], adapter_version="fixture", capabilities=dict(receive=True, send=True, stable_ids=True)))
        health = monitor.group_health(self.db, "another")
        self.assertEqual(("online", False, True), (health["mode"], health["directed"], health["serviceable"]))

    def test_member_notices_do_not_imply_text_permission(self):
        self.db.execute("INSERT INTO member_notice_settings VALUES(?,'join',1,1)", (self.api.room,))
        self.db.execute("INSERT INTO member_notice_approvals VALUES(?,'join',1,?,1,?,'daemon-id',?)",
                        (self.api.room, self.api.account, self.api.slot, self.now))
        health = self.health()
        self.assertEqual(("limited", False, True), (health["mode"], health["directed"], health["serviceable"]))
        self.assertIn("成员通知", health["detail"])
        self.db.execute("UPDATE member_notice_settings SET enabled=0")
        self.assertFalse(self.health()["serviceable"])

    def test_voice_alone_requires_a_current_verified_credential(self):
        self.db.execute("INSERT INTO voice_settings VALUES(?,1,1)", (self.api.room,))
        self.db.execute("INSERT INTO voice_approvals VALUES(?,1,?,1,?,'daemon-id',?)",
                        (self.api.room, self.api.account, self.api.slot, self.now))
        with patch.dict(os.environ, ERGOU_BAIDU_SPEECH_KEY="fixture-key", ERGOU_BAIDU_SPEECH_TOKEN=""):
            self.assertFalse(self.health()["serviceable"])
            verify_credential(self.db, self.owner, self.api.room)
            self.assertEqual("limited", self.health()["mode"])
            self.assertIn("语音唤醒回复", self.health()["detail"])
            os.environ["ERGOU_BAIDU_SPEECH_KEY"] = "different-fixture-key"
            self.assertFalse(self.health()["serviceable"])
