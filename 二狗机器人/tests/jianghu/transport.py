"""隔离进程里的生产微信监听器；只替换微信上游、时钟与事件 ID 来源。"""

import traceback
from contextlib import contextmanager
from datetime import datetime
from multiprocessing import get_context
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from ergou import agent_wechat, db, engine
from tests.test_agent_wechat import Fixture

START = int(datetime(2026, 11, 22, 8, tzinfo=db.BJ).timestamp())
GROUP = "test@chatroom"
MEMBER = "member"


def serve(path, pipe, fresh):
    try:
        if fresh:
            db.initialize(path)
        with db.closing_db(path) as conn:
            api = Fixture()
            secret = "receipt-fixture" * 3
            if fresh:
                agent_wechat.link(conn, api, "测试群", secret)
                conn.execute(
                    "INSERT INTO directed_groups(grp,account,binding,since) VALUES(?,?,1,?)",
                    (GROUP, api.account, START - 2),
                )
                conn.execute(
                    "INSERT INTO chat_models VALUES(?,1,'glm','fixture',?,?)",
                    (GROUP, b"fixture", START),
                )
                conn.execute("INSERT INTO jh_group_config VALUES(?,1,1)", (GROUP,))
            listener = agent_wechat.Listener(conn, api, secret)
            pipe.send((True, "ready"))
            while True:
                text, now, mentioned = pipe.recv()
                cursor = str(int(listener.cursor) + 1)
                ident = uuid5(NAMESPACE_URL, "jianghu-blind/" + cursor)
                with (
                    patch("time.time", return_value=now),
                    patch("ergou.engine.uuid.uuid4", return_value=ident),
                ):
                    listener.verify()
                    api.details.update(
                        body=text,
                        serverId=cursor,
                        createdAt=datetime.fromtimestamp(now, db.BJ).isoformat(),
                        mentions={
                            "state": "known",
                            "self": mentioned,
                            "all": False,
                            "userIds": [api.account] if mentioned else [],
                        },
                    )
                    seq = listener.consume(
                        {
                            "cursor": cursor,
                            "kind": "message.committed",
                            "data": {
                                "threadId": GROUP,
                                "messageId": "upstream-row",
                                "origin": "live",
                                "direction": "incoming",
                            },
                        }
                    )
                    row = None
                    if seq:
                        engine.step(conn)
                        row = conn.execute(
                            """SELECT body FROM inbox JOIN outbox ON biz=event_id
                                              WHERE seq=? AND inbox.grp=? AND inbox.member=?""",
                            (seq, GROUP, MEMBER),
                        ).fetchone()
                pipe.send((True, (seq, row[0] if row else "")))
    except EOFError:
        return
    except Exception:  # noqa: BLE001 — 原样回传子进程堆栈，父进程据此报告失败。
        pipe.send((False, traceback.format_exc()))
    finally:
        pipe.close()


class Session:
    def __init__(self, path):
        self.path = path
        self.spawn(True)

    def spawn(self, fresh):
        ctx = get_context("spawn")
        self.pipe, remote = ctx.Pipe()
        self.process = ctx.Process(
            target=serve, args=(self.path, remote, fresh), daemon=True
        )
        self.process.start()
        remote.close()
        try:
            self.receive()
        except BaseException:
            self.stop()
            raise

    def receive(self):
        if not self.pipe.poll(20):
            raise TimeoutError("隔离监听器未在 20 秒内响应")
        ok, value = self.pipe.recv()
        if not ok:
            raise RuntimeError(value)
        return value

    def send(self, text, now=START, *, mentioned=False):
        self.pipe.send((text, now, mentioned))
        return self.receive()

    def stop(self):
        self.process.kill()
        self.process.join(5)
        assert self.process.exitcode is not None
        self.pipe.close()

    def restart(self):
        self.stop()
        self.spawn(False)


@contextmanager
def session(path):
    instance = Session(path)
    try:
        yield instance
    finally:
        instance.stop()
