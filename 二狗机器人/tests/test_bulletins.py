import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ergou import admin, bulletins, jobs
from ergou.db import BJ, closing_db, demo, initialize


class Bulletins(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "bot.sqlite"
        initialize(path)
        demo(path)
        self.db = self.enterContext(closing_db(path))
        self.now = int(time.time())
        self.user = dict(role="运营管理员", name="ops", scopes='["demo-group"]')

    def schedule(self, kind, body="", **more):
        data = dict(kind=kind, body=body, period="一次", time=datetime.fromtimestamp(self.now, BJ).isoformat())
        return admin.schedule(self.db, self.user, "demo-group", data|more)

    def test_timed_content_prepared_once_and_static_compatible(self):
        dynamic = self.schedule("weather_news", "上海")
        self.schedule("text", "周末活动提醒")
        def lookup(kind, city, request):
            self.assertFalse(self.db.in_transaction)
            self.assertEqual((kind, city), ("天气", "上海"))
            return "上海 20 °C"
        with patch.object(bulletins.queries,"lookup",side_effect=lookup) as service, patch.object(bulletins,"news",return_value="重点新闻"):
            jobs.tick(self.db, self.now)
            jobs.tick(self.db, self.now)
            service.assert_not_called()
            self.assertTrue(bulletins.work(self.db))
            self.assertFalse(bulletins.work(self.db))
        self.assertEqual({r[0] for r in self.db.execute("SELECT body FROM outbox")}, {"上海 20 °C\n\n重点新闻","周末活动提醒"})
        self.assertEqual(self.db.execute("SELECT result FROM runs WHERE schedule=?", (dynamic,)).fetchone()[0], "QUEUED")

    def test_reconfigure_in_flight_and_handle_failure(self):
        first = self.schedule("news")
        self.schedule("weather", "广州")
        jobs.tick(self.db, self.now)
        def edit():
            self.assertFalse(self.db.in_transaction)
            self.schedule("text", "改期活动", id=first, version=1)
            return "旧内容"
        with patch.object(bulletins, "news", side_effect=edit), patch.object(bulletins.queries,"lookup",side_effect=bulletins.queries.ProviderError("服务超时")):
            self.assertTrue(bulletins.work(self.db))
            self.assertTrue(bulletins.work(self.db))
        results=[r[0] for r in self.db.execute("SELECT result FROM runs ORDER BY schedule")]
        self.assertEqual(results,["SKIPPED","FAILED 服务超时"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],0)

    def test_listener_skips_before_network_and_validates_content(self):
        from ergou import bridge
        bridge.enroll(self.db, "wx", "真实群", "x"*40, listen_only=True)
        u=self.user|dict(scopes='["真实群"]')
        admin.schedule(self.db,u,"真实群",dict(kind="news",period="一次",time=datetime.fromtimestamp(self.now,BJ).isoformat()))
        jobs.tick(self.db, self.now)
        self.assertFalse(bulletins.work(self.db))
        self.assertEqual(self.db.execute("SELECT result FROM runs").fetchone()[0],"SKIPPED")
        with self.assertRaises(ValueError):
            self.schedule("weather","http://example.com")
        sample=b"<rss><channel><item><title>First</title><link>https://www.news.gov.hk/first</link></item><item><title>Bad</title><link>https://elsewhere.example/</link></item></channel></rss>"
        self.assertIn("First", bulletins.headlines(sample))
        self.assertNotIn("Bad", bulletins.headlines(sample))
        with self.assertRaisesRegex(ValueError,"数据异常"):
            bulletins.headlines(b"<!DOCTYPE rss><rss/>")
