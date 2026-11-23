"""ERGOU_PROBE_WX 指向原型二进制时，以独立临时目录验证 HTTP 发送入口。"""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(os.environ.get("ERGOU_PROBE_WX"), "需要隔离原型二进制")
class NativeMusic(unittest.TestCase):
    def test_offline_music_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen(
                [os.environ["ERGOU_PROBE_WX"], "--data-dir", tmp, "--listen", f"127.0.0.1:{port}", "serve"],
                env={"HOME":tmp, "PATH":os.defpath, "XDG_CONFIG_HOME":tmp},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                def request(method, path, body=None):
                    token_file = Path(tmp, "api-token")
                    token = token_file.read_text().strip() if token_file.exists() else ""
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                    try:
                        conn.request(method, path, json.dumps(body) if body else None,
                                     {"Content-Type":"application/json", "Authorization":"Bearer "+token,
                                      "Idempotency-Key":f"probe-{time.monotonic_ns()}"})
                        response = conn.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        conn.close()

                for _ in range(100):
                    self.assertIsNone(process.poll(), "临时服务提前退出")
                    try:
                        if request("GET", "/health")[0] == 200:
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(.1)
                else:
                    self.fail("临时服务启动超时")
                status, account = request("POST", "/v1/accounts", {"alias":"offline-music"})
                self.assertEqual(status, 201)
                path = "/v1/accounts/" + account["id"] + "/sends"
                common = {"threadId":"demo@chatroom", "title":"Outfoxing the Fox",
                          "url":"https://mdn.github.io/webaudio-examples/audio-basics/"}
                music = dict(common, kind="music", author="Kevin MacLeod",
                             musicUrl=common["url"]+"outfoxing.mp3")
                cases = [
                    ("音乐卡", music, 409, "auth_required"),
                    ("网页分享", dict(common, kind="share"), 409, "auth_required"),
                    ("音乐卡缺少音源", {k:v for k,v in music.items() if k!="musicUrl"}, 400, "invalid_request"),
                    ("本地文件音源", dict(music, musicUrl="file:///offline"), 400, "invalid_share_request"),
                ]
                for label, body, status, code in cases:
                    with self.subTest(case=label):
                        actual, reply = request("POST", path, body)
                        self.assertEqual((actual, reply["error"]["code"]), (status, code))
                        print(f"{label} {actual} {code}", flush=True)
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
