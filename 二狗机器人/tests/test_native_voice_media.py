import hashlib
import io
import json
import struct
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock, patch

from ergou.agent_wechat import Client
from ergou.native_voice_media import fetch_pcm
from ergou.speech import pcm_from_wav


def recording(rate=16000, channels=1):
    output = io.BytesIO()
    sample = struct.pack("<h", 1000) if channels == 1 else struct.pack("<hh", 1000, 3000)
    with wave.open(output, "wb") as stream:
        stream.setparams((channels, 2, rate, 0, "NONE", ""))
        stream.writeframes(sample * rate)
    return output.getvalue()


class VoiceMediaTests(unittest.TestCase):
    def setUp(self):
        self.message_id = "message /1"
        self.raw = recording()
        self.asset = dict(accountId="slot", messageId=self.message_id, id="voice /1", kind="voice",
                          variant="normal", actualVariant="normal", state="available", contentType="audio/wav",
                          byteLength=len(self.raw), sha256=hashlib.sha256(self.raw).hexdigest(),
                          contentUrl="https://ignored.invalid/voice")
        self.job = dict(accountId="slot", id="job /1", assetId=self.asset["id"], kind="download", state="available")
        self.client = Mock(base="/v1/accounts/slot", slot="slot")
        self.conn = Mock()
        self.response = Mock()
        self.response.read.return_value = self.raw
        self.response.getheader.return_value = "audio/wav"
        self.client.connect.return_value = self.conn, self.response

    def test_local_http_transfer_contract(self):
        calls = []
        content = self.raw
        asset = self.asset
        job = self.job
        media_path = "/v1/accounts/slot/messages/message%20%2F1/media"
        content_path = "/v1/accounts/slot/media/voice%20%2F1/content"
        job_path = "/v1/accounts/slot/jobs/job%20%2F1"

        class Replay(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, value, mime="application/json"):
                data = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                calls.append(("GET", self.path, self.headers.get("Authorization")))
                if self.path == media_path:
                    phase = "available" if len(calls) > 1 else "pending"
                    self.reply(200, {"items": [dict(asset, id="silk", variant="encoded"), dict(asset, state=phase)]})
                elif self.path == job_path:
                    self.reply(200, job)
                elif self.path == content_path:
                    self.reply(200, content, "audio/wav")
                else:
                    self.reply(404, {})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(("POST", self.path, self.headers.get("Authorization"), payload))
                self.reply(202, dict(job, state="queued"))

        with HTTPServer(("127.0.0.1", 0), Replay) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            try:
                client = Client(server.server_port, "slot", "test-token")
                self.assertEqual(fetch_pcm(client, self.message_id, Mock()), struct.pack("<h", 1000) * 16000)
            finally:
                server.shutdown()
                thread.join(3)
        self.assertEqual([c[1] for c in calls], [media_path, media_path+"-transfers", job_path, media_path, content_path])
        self.assertTrue(all(c[2] == "Bearer test-token" for c in calls))
        self.assertEqual(calls[1][3], dict(messageId=self.message_id, assetId=self.asset["id"], quality="normal"))

    def test_pending_job_reused_and_cached_data_read(self):
        self.client.get.side_effect = [
            dict(items=[dict(self.asset, state="pending", jobId=self.job["id"])]), self.job, dict(items=[self.asset])]
        with patch("ergou.native_voice_media._start") as start:
            self.assertEqual(len(fetch_pcm(self.client, self.message_id, Mock())), 32000)
            start.assert_not_called()
        self.conn.close.assert_called_once()

    def test_wrong_owner_message_variant_state_size_and_digest_rejected(self):
        for changes in [dict(accountId="other"), dict(messageId="other"), dict(variant="encoded"),
                        dict(actualVariant="encoded"), dict(state="revoked"), dict(contentType="audio/silk"),
                        dict(byteLength=80000000), dict(sha256=None)]:
            with self.subTest(changes=changes):
                self.client.get.return_value = dict(items=[dict(self.asset, **changes)])
                with self.assertRaises(ValueError):
                    fetch_pcm(self.client, self.message_id, Mock())
                self.client.connect.assert_not_called()

    def test_wrong_job_or_asset_after_download_rejected(self):
        for job_update, final_update in [(dict(assetId="wrong"), {}), ({}, dict(id="different"))]:
            self.client.get.side_effect = [dict(items=[dict(self.asset, state="pending", jobId=self.job["id"])]),
                                           dict(self.job, **job_update), dict(items=[dict(self.asset, **final_update)])]
            with self.assertRaises(ValueError):
                fetch_pcm(self.client, self.message_id, Mock())
            self.client.connect.assert_not_called()

    def test_revocation_before_download_and_before_return(self):
        self.client.get.return_value = dict(items=[dict(self.asset, state="pending")])
        with patch("ergou.native_voice_media._start") as start:
            with self.assertRaises(PermissionError):
                fetch_pcm(self.client, self.message_id, Mock(side_effect=[None, PermissionError()]))
            start.assert_not_called()
        self.client.get.return_value = dict(items=[self.asset])
        with self.assertRaises(PermissionError):
            fetch_pcm(self.client, self.message_id, Mock(side_effect=[None, None, PermissionError()]))
        self.conn.close.assert_called_once()

    def test_bad_binary_rejected_and_connection_closed(self):
        self.client.get.return_value = dict(items=[self.asset])
        for mimetype, data in [("audio/mpeg", self.raw), ("audio/wav", self.raw[:-1]),
                               ("audio/wav", b"x"*len(self.raw))]:
            self.conn.reset_mock()
            self.response.getheader.return_value = mimetype
            self.response.read.return_value = data
            with self.assertRaises(ValueError):
                fetch_pcm(self.client, self.message_id, Mock())
            self.conn.close.assert_called_once()

    def test_native_wav_sample_rates_and_channels(self):
        for rate, channels, expected in [(8000, 2, 2000), (24000, 1, 1000), (16000, 1, 1000)]:
            with self.subTest(rate=rate, channels=channels):
                pcm = pcm_from_wav(recording(rate, channels), convert=True)
                self.assertLessEqual(abs(16000-len(pcm)//2), 1)
                self.assertEqual(pcm, struct.pack("<h", expected) * (len(pcm)//2))
        for invalid in [b"#!SILK_V3", self.raw[:-2], recording(96000)]:
            with self.assertRaises(ValueError):
                pcm_from_wav(invalid, convert=True)


if __name__ == "__main__":
    unittest.main()
