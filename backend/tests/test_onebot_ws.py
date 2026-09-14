import asyncio
import json
from contextlib import suppress

import pytest
from test_onebot import settings
from websockets.asyncio.server import serve

from app.adapters.onebot.events import EventBus, MetaEvent, UnknownEvent, parse_event
from app.adapters.onebot.websocket_client import OneBotWebSocketClient


@pytest.mark.parametrize('payload,kind', [
    ({'post_type':'meta_event', 'meta_event_type':'heartbeat', 'self_id':1}, 'MetaEvent'),
    ({'post_type':'message', 'message_type':'private', 'message_id':1}, 'MessageEvent'),
    ({'post_type':'notice', 'notice_type':'friend_add'}, 'NoticeEvent'),
    ({'post_type':'request', 'request_type':'friend'}, 'RequestEvent'),
    ({'post_type':'custom', 'body':'private'}, 'UnknownEvent'),
    ({'post_type':'message', 'message_id':True}, 'UnknownEvent'),
    ([], 'UnknownEvent'), ({'post_type':[]}, 'UnknownEvent'),
])
def test_event_parsing(payload, kind):
    event = parse_event(json.dumps(payload))
    assert type(event).__name__ == kind
    assert 'raw_event' not in event.model_dump()
    assert 'private' not in repr(event) or kind == 'MessageEvent'


def test_invalid_json():
    assert isinstance(parse_event('not-json'), UnknownEvent)


async def test_bus_isolation():
    bus = EventBus(handler_timeout=.05)
    seen = []
    async def broken(event):
        raise RuntimeError('secret')
    async def good(event):
        seen.append(event)
    bus.subscribe(broken)
    bus.subscribe(good)
    task = asyncio.create_task(bus.run())
    try:
        await bus.publish(UnknownEvent())
        await asyncio.wait_for(bus.queue.join(), 1)
        assert len(seen) == 1
        assert bus.metrics['handler_errors'] == 1
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def wait_until(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


async def test_real_ws_auth_receive_shutdown():
    async def server(socket):
        assert socket.request.headers['Authorization'] == 'Bearer mock-credential'
        await socket.send('bad-json')
        await socket.send(json.dumps({'post_type':'meta_event', 'meta_event_type':'heartbeat', 'self_id':123}))
        await socket.wait_closed()
    async with serve(server, '127.0.0.1', 0) as host:
        port = host.sockets[0].getsockname()[1]
        bus = EventBus()
        client = OneBotWebSocketClient(settings(onebot_ws_url=f'ws://127.0.0.1:{port}'), bus)
        task = asyncio.create_task(client.run())
        await wait_until(lambda: bus.queue.qsize() == 2)
        assert client.connected
        assert isinstance(await bus.queue.get(), UnknownEvent)
        assert isinstance(await bus.queue.get(), MetaEvent)
        await client.stop()
        await asyncio.wait_for(task, 1)
        assert not client.connected


async def test_reconnect_backoff_capped():
    calls = 0
    async def server(socket):
        nonlocal calls
        calls += 1
        await socket.close()
    async with serve(server, '127.0.0.1', 0) as host:
        config = settings(onebot_ws_url=f'ws://127.0.0.1:{host.sockets[0].getsockname()[1]}',
                          onebot_ws_reconnect_min_seconds=.02, onebot_ws_reconnect_max_seconds=.08)
        client = OneBotWebSocketClient(config, EventBus())
        task = asyncio.create_task(client.run())
        await wait_until(lambda: calls >= 4)
        assert client.backoff == .08
        assert client.metrics['onebot_ws_reconnect_total'] >= 3
        await client.stop()
        await asyncio.wait_for(task, 1)


async def test_heartbeat_timeout_even_with_messages():
    async def server(socket):
        with suppress(Exception):
            while True:
                await socket.send(json.dumps({'post_type':'notice','notice_type':'test'}))
                await asyncio.sleep(.01)
    async with serve(server, '127.0.0.1', 0) as host:
        client = OneBotWebSocketClient(settings(
            onebot_ws_url=f'ws://127.0.0.1:{host.sockets[0].getsockname()[1]}',
            onebot_ws_heartbeat_timeout=.08, onebot_ws_reconnect_min_seconds=.02,
        ), EventBus())
        task = asyncio.create_task(client.run())
        await wait_until(lambda: client.metrics['onebot_ws_reconnect_total'] >= 1)
        await client.stop()
        await asyncio.wait_for(task, 1)


async def test_ws_auth_failed():
    async def server(socket):
        await socket.wait_closed()
    def reject(connection, request):
        return connection.respond(401, 'unauthorized')
    async with serve(server, '127.0.0.1', 0, process_request=reject) as host:
        client = OneBotWebSocketClient(settings(onebot_ws_url=f'ws://127.0.0.1:{host.sockets[0].getsockname()[1]}'), EventBus())
        task = asyncio.create_task(client.run())
        await wait_until(lambda: client.state == 'AUTH_FAILED')
        await client.stop()
        await asyncio.wait_for(task, 1)


async def test_unconfigured_listener_stop():
    client = OneBotWebSocketClient(settings(onebot_ws_url=None), EventBus())
    task = asyncio.create_task(client.run())
    await wait_until(lambda: client.state == 'DISCONNECTED')
    await client.stop()
    await asyncio.wait_for(task, 1)
