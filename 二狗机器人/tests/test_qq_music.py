import asyncio
import json
import unittest
from unittest.mock import patch

from ergou import qq_music as qq

MID = "002mZevo3wHvsc"
SEARCH = "https://music.apple.com/cn/search?term=test"
PAGE = b'<meta property="og:image" content="https://y.qq.com/cover.jpg">"file":{"media_mid":"004XjSbo0WlYr1","size_try":900}'
TRACK = {"name": "有何不可", "singer": "许嵩", "mid": MID}


def response(path, mid=MID):
    return {"code": 0, "data": {"sip": ["http://stream.qq.com/"], "midurlinfo": [
        {"songmid": mid, "result": 0 if path else 104003, "purl": path}]}}


class QQMusicTests(unittest.TestCase):
    def resolve(self, *replies):
        with patch.object(qq, "public_get", side_effect=replies) as fetch:
            card = asyncio.run(qq.resolve("许嵩 有何不可", SEARCH))
        return card, fetch

    def results(self, *tracks):
        return json.dumps({"data": {"song": {"itemlist": tracks}}}).encode()

    def test_trial_cover_and_exact_title_artist(self):
        playback = json.dumps({"full":response(""), "trial":response("trial.mp3")}).encode()
        card, fetch = self.resolve(self.results(TRACK), PAGE, playback)
        self.assertEqual(card, dict(kind="music", title="有何不可", author="许嵩", url=qq.LANDING+"songmid="+MID,
                                    thumbnailUrl="https://y.qq.com/cover.jpg", musicUrl="https://stream.qq.com/trial.mp3"))
        self.assertEqual(fetch.call_count,3)

    def test_full_when_available_and_no_thumbnail_required(self):
        card,_ = self.resolve(self.results(TRACK), b"", json.dumps({"full":response("full.mp3")}).encode())
        self.assertEqual(card["musicUrl"], "https://stream.qq.com/full.mp3")
        self.assertNotIn("thumbnailUrl", card)

    def test_unavailable_or_foreign_media_uses_song_page(self):
        for trial in (response(""),response("https://outside.invalid/file"),response("wrong.mp3","unrelated")):
            with self.subTest(trial=trial):
                card,_ = self.resolve(self.results(TRACK), PAGE, json.dumps({"trial":trial}).encode())
                self.assertEqual((card["kind"],card["url"]),("share",qq.LANDING+"songmid="+MID))
        card,_ = self.resolve(self.results(TRACK), TimeoutError())
        self.assertEqual(card["kind"],"share")

    def test_no_match_and_outage_keep_search(self):
        for result in (self.results(dict(TRACK,singer="翻唱")), b"{}", TimeoutError()):
            card,fetch = self.resolve(result)
            self.assertEqual((card["kind"],card["url"]),("share",SEARCH))
            self.assertEqual(fetch.call_count,1)

    def test_wechat_event_replay_sends_one_card(self):
        import os
        import time
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from ergou import agent_wechat as wx, db, engine
        from tests.test_agent_wechat import Fixture

        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "replay.sqlite"
        db.initialize(path)
        conn = self.enterContext(db.closing_db(path))
        client = Fixture()
        secret = "fixture" * 8
        wx.link(conn, client, "测试群", secret)
        listener = wx.Listener(conn, client, secret)
        listener.verify()
        listener.heartbeat("LISTENING")
        conn.execute("INSERT INTO directed_groups VALUES(?,?,1,?)", (client.room,client.account,time.time()-5))
        client.details.update(body="二狗点歌 许嵩 有何不可", createdAt=datetime.now(timezone.utc).isoformat())
        event = dict(cursor="13",kind="message.committed",data=dict(threadId=client.room,messageId="upstream-row",
                                                                    origin="live",direction="incoming"))
        listener.consume(event)
        engine.step(conn)
        listener.consume(event)
        with patch.dict(os.environ, ERGOU_QQ_MUSIC="1"), patch.object(qq, "public_get", side_effect=[
                self.results(TRACK), PAGE, json.dumps({"trial":response("preview.mp3")}).encode()
        ]), patch.object(wx, "send_direct", return_value=("ACKNOWLEDGED", "fixture")) as send:
            self.assertTrue(wx.replies(conn,client,secret,"fixture",group=client.room,once=True))
            self.assertFalse(wx.replies(conn,client,secret,"fixture",group=client.room,once=True))
        send.assert_called_once()
        task = send.call_args.args[-1]
        self.assertEqual((task["grp"],task["share"]["title"],task["share"]["kind"]),(client.room,"有何不可","music"))
