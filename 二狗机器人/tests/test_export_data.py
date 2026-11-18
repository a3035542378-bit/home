import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import export_data
from deploy.export_data import export
from ergou import bridge, db


class ExportTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = folder / "active.sqlite"
        self.destination = folder / "deployment.sqlite"
        db.initialize(self.source)
        self.active = self.enterContext(db.closing_db(self.source))
        bridge.enroll(self.active, "bot", "room", "X" * 45, listen_only=True)
        self.active.execute("INSERT INTO agent_wechat_links VALUES('default','bot','room','server','cursor')")
        self.active.execute("INSERT INTO directed_groups VALUES('room','bot',1,1)")

    def test_export_preserves_history_excludes_secrets_and_cannot_send(self):
        raw = dict(db.DEFAULT, allowlist=["trusted"], weekly_push=True, city="上海", secret="must_not_migrate")
        self.active.execute("UPDATE groups SET config=?", (db.dump(raw),))
        self.active.execute("INSERT INTO users VALUES('operator','secret-credential','系统管理员','[]')")
        self.active.execute("INSERT INTO tokens VALUES('secret-session','operator',999)")
        self.active.execute("INSERT INTO chat_models VALUES('room',2,'openai','test-model',x'cafe',42)")
        self.active.execute("INSERT INTO smart_controls VALUES('room',1,1,1,'[\"manager\"]')")
        self.active.execute("INSERT INTO member_notice_settings VALUES('room','join',1,2)")
        self.active.execute("INSERT INTO voice_settings VALUES('room',1,2)")
        self.active.execute("INSERT INTO voice_credentials VALUES('room','key',x'cafe')")
        self.active.execute("INSERT INTO schedules VALUES(1,'room','天气','每天',1,1,1,NULL,2)")
        self.active.execute("INSERT INTO games VALUES(1,'room','G01','猜谜','member','RUNNING','{}','{}',1,2,NULL,NULL)")
        self.active.execute("INSERT INTO players VALUES(1,'member',1)")
        self.active.execute("INSERT INTO ledger VALUES(1,'room','member',1,0,'胜利',5,'1','win',1,'完成目标')")
        self.active.execute("""INSERT INTO outbox
            (biz,account,grp,binding,body,state,created,expires,ready) VALUES
            ('old','bot','room',1,'secret-body','PENDING',0,999,0)""")
        self.active.execute("INSERT INTO reply_rule_sets VALUES('room',1,'[]')")
        summary = export(self.source, self.destination, "家庭群")
        self.assertTrue(all(isinstance(value, int) for value in summary.values()))
        with db.closing_db(self.destination) as result:
            self.assertEqual(tuple(result.execute("SELECT paused,binding FROM groups").fetchone()), (1, 1))
            config = json.loads(result.execute("SELECT config FROM groups").fetchone()[0])
            self.assertEqual(config["city"], "上海")
            self.assertEqual(config["allowlist"], [])
            self.assertFalse(config["weekly_push"])
            self.assertNotIn("secret", config)
            self.assertEqual(result.execute("SELECT alias FROM group_profile").fetchone()[0], "家庭群")
            self.assertEqual(result.execute("SELECT state FROM account").fetchone()[0], "SUSPENDED")
            self.assertEqual(tuple(result.execute("SELECT * FROM migration_handoff").fetchone()), ("room", "bot", 1))
            self.assertEqual(result.execute("SELECT SUM(points) FROM ledger").fetchone()[0], 5)
            self.assertEqual(result.execute("SELECT state FROM games").fetchone()[0], "ABORTED")
            self.assertEqual(tuple(result.execute("SELECT * FROM participation").fetchone()), (1, "member", 1))
            self.assertEqual(tuple(result.execute("SELECT body,enabled FROM schedules").fetchone()), ("天气", 0))
            self.assertEqual(result.execute("SELECT enabled FROM member_notice_settings").fetchone()[0], 0)
            self.assertEqual(result.execute("SELECT enabled FROM voice_settings").fetchone()[0], 0)
            self.assertEqual(result.execute("SELECT admins FROM smart_controls").fetchone()[0], "[]")
            self.assertEqual(tuple(result.execute("SELECT model,credential,verified FROM chat_models").fetchone()),
                             ("test-model", None, None))
            for table in ("inbox","outbox","users","tokens","nodes","node_grants","membership","listener_nodes",
                          "agent_wechat_links","directed_groups","voice_credentials","voice_approvals","live_notices"):
                self.assertEqual(result.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
        self.assertFalse(Path(str(self.destination) + "-wal").exists())
        self.assertEqual(self.active.execute("SELECT paused FROM groups").fetchone()[0], 0)

    def test_preexisting_destination_and_ambiguous_alias(self):
        bridge.enroll(self.active, "other", "room2", "Y" * 45, listen_only=True)
        with self.assertRaisesRegex(ValueError, "恰好"):
            export(self.source, self.destination, "不能猜测")
        self.assertFalse(self.destination.exists())
        self.destination.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            export(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"original")

    def test_snapshot_excludes_concurrent_commit_between_tables(self):
        original = export_data._portable_config

        def concurrent_change(raw):
            self.active.execute("INSERT INTO reward_offers VALUES('room','并发新增',10)")
            return original(raw)

        with patch.object(export_data, "_portable_config", concurrent_change):
            counts = export(self.source, self.destination)
        self.assertEqual(self.active.execute("SELECT COUNT(*) FROM reward_offers").fetchone()[0], 1)
        self.assertEqual(counts["reward_offers"], 0)

    def test_handoff_requires_enabled_attached_group_and_current_grant(self):
        self.active.execute("INSERT INTO group_profile VALUES('room','已有群昵称',1,0)")
        for statement in [
            "UPDATE groups SET paused=1", "UPDATE groups SET config='{\"enabled\":false}'",
            "UPDATE group_profile SET detached=1", "UPDATE directed_groups SET binding=2", "DELETE FROM node_grants",
        ]:
            with self.subTest(change=statement):
                self.active.execute(statement)
                summary = export(self.source, self.destination, "新昵称")
                self.assertEqual(summary["migration_handoff"], 0)
                with db.closing_db(self.destination) as result:
                    self.assertEqual(result.execute("SELECT alias FROM group_profile").fetchone()[0], "已有群昵称")
                self.destination.unlink()
                self.active.execute("UPDATE groups SET paused=0,config=?", (db.dump(db.DEFAULT),))
                self.active.execute("UPDATE group_profile SET detached=0")
                self.active.execute("UPDATE directed_groups SET binding=1")
                self.active.execute("INSERT OR IGNORE INTO node_grants VALUES('bot','room')")
