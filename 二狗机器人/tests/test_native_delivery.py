import json
import unittest
from unittest.mock import patch

from ergou import agent_wechat as aw


class NativeDelivery(unittest.TestCase):
    def setUp(self):
        self.client=aw.Client(6174,"slot","read-fixture")
        self.task={"biz":"job/one","grp":"test@chatroom","body":"约定的文字"}
        self.intent={"accountId":"slot","destination":self.task["grp"],"state":"accepted",
                     "serverId":"9007199254740997","localMessageId":"message/id"}
        self.message={"id":"message/id","accountId":"slot","threadId":self.task["grp"],"type":1,
                      "direction":"outgoing","serverId":self.intent["serverId"],"body":self.task["body"]}
        self.get=self.enterContext(patch.object(aw.Client,"get",autospec=True,side_effect=self.fixture))

    def fixture(self,client,path):
        if "/sends/" in path:
            self.assertEqual(client.token,"send-fixture")
            self.assertEqual(path,"/v1/accounts/slot/sends/by-idempotency-key?key=ergou-job%2Fone")
            return self.intent
        self.assertIs(client,self.client)
        self.assertEqual(path,"/v1/accounts/slot/messages/message%2Fid")
        return self.message

    def inspect(self):
        return aw.inspect_text_send(self.client,"send-fixture",self.task,timeout=0)

    def test_outgoing_message_identity_and_body(self):
        self.assertEqual(self.inspect(),("ACKNOWLEDGED","微信已受理，已回读核对本群发件记录"))
        for field,value in (("id","other"),("accountId","other"),("threadId","other"),("direction","incoming"),
                            ("serverId","17"),("body","不同文本"),("type",34),("type",True)):
            with self.subTest(field=field), patch.dict(self.message,{field:value}):
                self.assertEqual(self.inspect()[0],"UNKNOWN")
        with patch.dict(self.intent,{"destination":"unrelated"}):
            self.get.reset_mock()
            self.assertEqual(self.inspect()[0],"UNKNOWN")
            self.assertEqual(self.get.call_count,1)

    def test_music_search_card_payload_and_readback(self):
        card=dict(kind="share",title="周杰伦 晴天",url="https://music.apple.com/cn/search?term=test",
                  description="在 Apple Music 查看搜索结果")
        self.task["share"]=card
        self.message.update(type=49,appMessageType=5,link=dict(title=card["title"],url=card["url"]))
        with patch.object(aw.http.client,"HTTPConnection") as factory:
            conn=factory.return_value
            conn.getresponse.return_value.status=202
            self.assertEqual(aw.send_direct(self.client,"send-fixture",self.task)[0],"ACKNOWLEDGED")
            self.assertEqual(json.loads(conn.request.call_args.kwargs["body"]),dict(threadId=self.task["grp"],**card))
        self.message["link"]["url"]="https://other.example/"
        self.assertEqual(self.inspect()[0],"UNKNOWN")

    def test_missing_projection_and_unavailable_readback(self):
        for fields in ({"localMessageId":None},{"serverId":"0"},{"serverId":str(2**64)}):
            with self.subTest(fields=fields),patch.dict(self.intent,fields):
                self.assertEqual(self.inspect(),("ACKNOWLEDGED","微信已受理，发件记录暂未核验"))
        self.get.side_effect=[self.intent,ConnectionError("upstream unavailable")]
        self.assertIn("暂未核验",self.inspect()[1])
        self.get.side_effect=ConnectionError()
        self.assertEqual(self.inspect()[0],"UNKNOWN")

    def test_native_music_sends_one_card_and_checks_artist_and_subtype(self):
        card=dict(kind="music", title="有何不可", author="许嵩", url="https://c.y.qq.com/song",
                  musicUrl="https://stream.qq.com/preview.mp3", thumbnailUrl="https://y.qq.com/art.jpg")
        self.task.update(share=card, mention_sender="requester")
        self.message.update(type=49, appMessageType=3, link=dict(title=card["title"],url=card["url"],description=card["author"]))
        with patch.object(aw.http.client,"HTTPConnection") as factory:
            conn=factory.return_value
            conn.getresponse.side_effect=ConnectionResetError()
            self.assertEqual(aw.send_direct(self.client,"send-fixture",self.task)[0],"ACKNOWLEDGED")
            conn.request.assert_called_once()
            payload=json.loads(conn.request.call_args.kwargs["body"])
            self.assertEqual(payload,dict(threadId=self.task["grp"],**card))
        self.message["link"]["description"]="其他歌手"
        self.assertEqual(self.inspect()[0],"UNKNOWN")
        self.message.update(appMessageType=5)
        self.assertEqual(self.inspect()[0],"UNKNOWN")

    def test_lost_post_receipt_reads_original_key_without_resending(self):
        with patch.object(aw.http.client,"HTTPConnection") as factory:
            connection=factory.return_value
            connection.getresponse.side_effect=ConnectionResetError()
            result=aw.send_direct(self.client,"send-fixture",self.task)
        self.assertEqual(result[0],"ACKNOWLEDGED")
        connection.request.assert_called_once()
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Idempotency-Key"],"ergou-job/one")
        self.assertEqual(self.get.call_count,2)

    def test_delayed_projection_retries_reads(self):
        self.get.side_effect=[dict(self.intent,localMessageId=None),self.intent,self.message]
        with patch.object(aw.time,"sleep"):
            state,detail=aw.inspect_text_send(self.client,"send-fixture",self.task)
        self.assertEqual(state,"ACKNOWLEDGED")
        self.assertIn("已回读",detail)

