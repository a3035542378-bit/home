import tempfile
import unittest
from pathlib import Path

from ergou import reply_rules
from ergou.db import closing_db, demo, initialize
from ergou.engine import receive, step


def rule(keyword, content, **extra):
    return dict(keyword=keyword, mode="exact", kind="text", threshold=0.8, content=content) | extra


class ReplyRules(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "bot.sqlite"
        initialize(path)
        demo(path, ("one", "two"))
        self.db = self.enterContext(closing_db(path))
        self.operator = dict(role="运营管理员", name="ops", scopes='["one"]')

    def save(self, rules, version=0):
        return reply_rules.configure(self.db, self.operator, "one", dict(version=version, rules=rules))

    def say(self, src, text, group="one"):
        seq = receive(self.db, "sim-account", group, "member", src, {"text": text})
        step(self.db)
        row = self.db.execute("SELECT body FROM outbox JOIN inbox ON outbox.biz=inbox.event_id WHERE seq=?", (seq,)).fetchone()
        return row[0] if row else None

    def test_authorization_cas_and_content_validation(self):
        rules = [rule("早安", "今天也要精神满满")]
        self.save(rules)
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            self.save([], 0)
        for user, group in ((self.operator, "two"), (self.operator | {"role":"群管理员"}, "one"),
                            (self.operator | {"role":"只读人员"}, "one")):
            with self.assertRaises(PermissionError):
                reply_rules.configure(self.db, user, group, dict(rules=[], version=1))
        for invalid in (rule("早安", "file:///C:/a", kind="image"),
                        rule("早安", "http://example.org/diagram.png", kind="image"),
                        rule("早安", "https://user:pass@example.com/a", kind="link"),
                        rule("早安", "hi", mode="similar", threshold=float("nan")),
                        rule("  ", "hi")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.save([invalid], 1)
        self.assertEqual(reply_rules.settings(self.db, self.operator, "one"), {"version": 1, "rules": rules})
        self.assertEqual(self.save([], 1), {"version": 2, "rules": []})

    def test_priority_typo_boundary_and_hit_privacy(self):
        fuzzy = rule("请告诉我群规", "请尊重其他群成员", mode="similar", threshold=0.8)
        contains = rule("群规", "https://example.org/rules", mode="contains", kind="link")
        image = rule("地图", "https://example.org/map.jpg", kind="image")
        self.save([fuzzy, contains, image, rule("FAQ", "常见问题")])
        self.assertIsNone(self.say("1", "请告诉我群规"))
        self.assertEqual(self.say("2", "二狗请告诉卧群规"), fuzzy["content"])
        self.assertEqual(self.say("3", "二狗我想阅读群规呢"), contains["content"])
        self.assertEqual(self.say("4", "二狗地图"), "图片：" + image["content"])
        self.assertEqual(self.say("5", "二狗ｆａｑ"), "常见问题")
        self.assertNotEqual(self.say("6", "二狗地图", group="two"), "图片：" + image["content"])
        self.assertEqual([s[0] for s in self.db.execute("SELECT keyword FROM reply_rule_hits ORDER BY seq")],
                         ["请告诉我群规", "群规", "地图", "FAQ"])
        self.save([contains, fuzzy, image], 1)
        self.assertEqual(self.say("7", "二狗请告诉我群规"), contains["content"])

    def test_simulated_image_snapshot_belongs_to_original_group_and_event(self):
        url = "https://example.org/first.png"
        self.save([rule("图片", url, kind="image")])
        self.say("img1", "二狗图片")
        seq = self.db.execute("SELECT seq FROM inbox WHERE source='img1'").fetchone()[0]
        self.save([rule("图片", "https://example.org/new.jpg", kind="image")], 1)
        self.assertEqual(reply_rules.simulation_media(self.db, "one", seq), {"type":"image","url":url})
        self.assertIsNone(reply_rules.simulation_media(self.db, "two", seq))
        # A real-account rule returns only the authorized text link.
        from ergou import bridge
        secret="x"*40
        bridge.enroll(self.db,"actual","three",secret,listen_only=True)
        bridge.endpoint(self.db,"heartbeat",secret,dict(state="LISTENING",actual_account="actual",groups=["three"],
                adapter_version="fixture",capabilities=dict(receive=True,send=False,stable_ids=True)))
        reply_rules.configure(self.db,self.operator | dict(scopes='["three"]'),"three",
                              dict(version=0,rules=[rule("图片",url,kind="image")]))
        seq = receive(self.db,"actual","three","member","live1",{"text":"二狗图片"})
        step(self.db)
        self.assertIsNone(reply_rules.simulation_media(self.db,"three",seq))
        self.assertIsNone(self.db.execute("SELECT 1 FROM simulation_reply_images WHERE seq=?",(seq,)).fetchone())
