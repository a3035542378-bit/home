import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ergou import agent_wechat, leisure, models, native_voice, queries, voice_policy
from ergou.db import closing_db, initialize
from ergou.engine import receive
from tests.test_agent_wechat import Fixture
from tests.voice_credentials import verify_credential


class VoiceAsyncTests(unittest.TestCase):
    def setUp(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "async.sqlite"
        initialize(path)
        self.db = self.enterContext(closing_db(path))
        self.api = Fixture()
        self.group = self.api.room
        self.user = dict(role="运营管理员", name="ops", scopes=json.dumps([self.group]))
        self.enterContext(patch.dict(os.environ, {"ERGOU_BAIDU_SPEECH_KEY":"sample-key"}))
        agent_wechat.link(self.db, self.api, "测试群", "t"*40)
        agent_wechat.Listener(self.db,self.api,"t"*40).verify()
        voice_policy.configure(self.db, self.user, self.group, dict(action="switch", enabled=True, version=0))
        voice_policy.approve(self.db, voice_policy.preview(self.db, self.group))
        verify_credential(self.db,self.user,self.group)
        self.db.execute("INSERT INTO chat_models VALUES(?,1,'glm','test',?,?)",(self.group,b"sealed",time.time()))
        self.sent = self.enterContext(patch("ergou.engine.queue"))
        self.complete = self.enterContext(patch("ergou.models.complete", return_value="模型回答"))
        self.key = self.enterContext(patch("ergou.models.protect", return_value=b"test"))
        self.count = 0

    def disable(self):
        version = voice_policy.settings(self.db, self.user, self.group)["version"]
        voice_policy.configure(self.db, self.user, self.group, dict(action="switch", enabled=False, version=version))

    def event(self, *, awake=True, voice=True):
        self.count += 1
        source = str(self.count)
        seq = receive(self.db, self.api.account, self.group, "member", source, dict(text="二狗测试"),
                      message_type="voice" if voice else "text",
                      adapter_version=native_voice.VERSION if voice else "agent-wechat-events/2.7.1")
        event = self.db.execute("SELECT * FROM inbox WHERE seq=?",(seq,)).fetchone()
        if voice and awake:
            self.db.execute("""INSERT INTO native_voice_events(grp,account,binding,generation,slot,server_id,
                message_id,source,member,source_time,state,seq) SELECT grp,account,binding,generation,slot,
                server_id,?,?,?,?,'AWAKE',? FROM active_native_voice WHERE grp=?""",
                ("upstream-"+source,source,event["member"],event["arrived"],seq,self.group))
        elif not voice:
            self.db.execute("INSERT INTO directed_events VALUES(?,?)",(event["event_id"],event["arrived"]))
        return event

    def test_unproven_event_does_not_create_external_work(self):
        event = self.event(awake=False)
        models.submit(self.db,event,"聊天")
        queries.submit(self.db,event,"天气","北京")
        self.assertFalse(models.ChatWorker().work(self.db))
        self.assertFalse(queries.work(self.db, Mock(side_effect=AssertionError)))
        self.complete.assert_not_called()

    def test_voice_revoked_before_model_transmission(self):
        event = self.event()
        models.submit(self.db,event,"话题")
        def revoke(*args):
            self.disable()
            return b"test"
        self.key.side_effect = revoke
        self.assertTrue(models.ChatWorker().work(self.db))
        self.assertEqual(tuple(self.db.execute("SELECT state,prompt FROM chat_requests").fetchone()),("CANCELLED",None))
        self.complete.assert_not_called()
        self.sent.assert_not_called()

    def test_model_response_after_revocation_is_discarded(self):
        event = self.event()
        models.submit(self.db,event,"话题")
        def revoke(*args):
            self.disable()
            return "应丢弃的回复"
        self.complete.side_effect = revoke
        worker = models.ChatWorker()
        self.assertTrue(worker.work(self.db))
        self.assertEqual(tuple(self.db.execute("SELECT state,prompt FROM chat_requests").fetchone()),("CANCELLED",None))
        self.sent.assert_not_called()
        self.assertFalse(worker.sessions)

    def test_voice_history_shared_with_text_until_group_revokes_voice(self):
        worker = models.ChatWorker()
        models.submit(self.db,self.event(),"语音上下文")
        self.assertTrue(worker.work(self.db))
        models.submit(self.db,self.event(voice=False),"继续")
        self.assertTrue(worker.work(self.db))
        self.assertEqual([p["content"] for p in self.complete.call_args.args[-1][1:]], ["语音上下文","模型回答","继续"])
        self.disable()
        models.submit(self.db,self.event(voice=False),"新问题")
        self.assertTrue(worker.work(self.db))
        self.assertEqual([p["content"] for p in self.complete.call_args.args[-1][1:]], ["新问题"])

    def test_text_only_chat_survives_voice_switch_during_request(self):
        worker = models.ChatWorker()
        models.submit(self.db,self.event(voice=False),"纯文字开头")
        worker.work(self.db)
        following = self.event(voice=False)
        models.submit(self.db,following,"继续说")
        def revoke(*args):
            self.disable()
            return "文字仍可回答"
        self.complete.side_effect = revoke
        self.assertTrue(worker.work(self.db))
        self.assertEqual([p["content"] for p in self.complete.call_args.args[-1][1:]],["纯文字开头","模型回答","继续说"])
        self.assertEqual(self.sent.call_args.args[3],"文字仍可回答")
        self.assertTrue(models.reply_authorized(self.db,following["event_id"]))
        self.assertTrue(models.reply_authorized(self.db,"并非模型任务"))
        self.assertFalse(self.db.execute("SELECT 1 FROM chat_voice_context").fetchone())

    def test_text_drops_revoked_voice_before_call_but_keeps_independent_text(self):
        worker = models.ChatWorker()
        models.submit(self.db,self.event(voice=False),"独立文字")
        worker.work(self.db)
        voice = self.event()
        models.submit(self.db,voice,"语音私密片段")
        worker.work(self.db)
        reply_to_text = self.event(voice=False)
        models.submit(self.db,reply_to_text,"延续语音内容")
        worker.work(self.db)
        self.assertTrue(models.reply_authorized(self.db,reply_to_text["event_id"]))
        fresh_text = self.event(voice=False)
        models.submit(self.db,fresh_text,"新的文字提问")
        def disable_before_dispatch(*args):
            self.disable()
            return b"test"
        self.key.side_effect = disable_before_dispatch
        worker.work(self.db)
        self.assertEqual([p["content"] for p in self.complete.call_args.args[-1][1:]],
                         ["独立文字","模型回答","新的文字提问"])
        self.assertTrue(models.reply_authorized(self.db,fresh_text["event_id"]))
        self.assertFalse(models.reply_authorized(self.db,reply_to_text["event_id"]))
        self.assertFalse(models.reply_authorized(self.db,voice["event_id"]))

    def test_text_with_voice_history_in_flight_is_cancelled(self):
        worker = models.ChatWorker()
        models.submit(self.db,self.event(),"私密语音")
        worker.work(self.db)
        text_event = self.event(voice=False)
        models.submit(self.db,text_event,"刚才说什么")
        def revoke(*args):
            self.disable()
            return "含语音的答案"
        self.complete.side_effect = revoke
        self.sent.reset_mock()
        worker.work(self.db)
        self.assertEqual(self.complete.call_args.args[-1][1]["content"],"私密语音")
        self.sent.assert_not_called()
        self.assertFalse(models.reply_authorized(self.db,text_event["event_id"]))

    def test_query_revoked_while_queued(self):
        queries.submit(self.db,self.event(),"天气","北京")
        self.disable()
        request = Mock(side_effect=AssertionError)
        self.assertFalse(queries.work(self.db,request))
        self.assertEqual(tuple(self.db.execute("SELECT state,argument,result FROM queries").fetchone()),("CANCELLED",None,None))
        request.assert_not_called()
        self.sent.assert_not_called()

    def test_weather_revoked_between_geocoding_and_forecast(self):
        queries.submit(self.db,self.event(),"天气","北京")
        def geocode(url, params, deadline):
            self.assertEqual(url,queries.GEO)
            self.disable()
            return dict(results=[dict(name="北京", latitude=39, longitude=116)])
        self.assertTrue(queries.work(self.db,geocode))
        self.assertEqual(self.db.execute("SELECT state FROM queries").fetchone()[0],"CANCELLED")
        self.assertFalse(self.db.execute("SELECT 1 FROM weather_cache").fetchone())
        self.sent.assert_not_called()

    def test_encyclopedia_revoked_after_exact_title_miss(self):
        queries.submit(self.db,self.event(),"百科","熊猫")
        def missing(*args, **kwargs):
            self.disable()
            return b'{"batchcomplete":true}'
        with patch.object(leisure.bulletins,"public_get",side_effect=missing) as request:
            self.assertTrue(queries.work(self.db))
        request.assert_called_once()
        self.assertEqual(self.db.execute("SELECT state FROM queries").fetchone()[0],"CANCELLED")
        self.sent.assert_not_called()

    def test_query_revoked_during_final_response(self):
        queries.submit(self.db,self.event(),"天气","北京")
        def request(url, params, deadline):
            if url == queries.GEO:
                return dict(results=[dict(name="北京", latitude=39, longitude=116)])
            self.disable()
            return dict(current=dict(temperature_2m=10, time="2026-11-18T12:00"))
        self.assertTrue(queries.work(self.db,request))
        self.assertEqual(self.db.execute("SELECT state FROM queries").fetchone()[0],"CANCELLED")
        self.assertFalse(self.db.execute("SELECT 1 FROM weather_cache").fetchone())
        self.sent.assert_not_called()
