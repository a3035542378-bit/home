import asyncio
import json
from contextlib import suppress

import pytest
from test_onebot import settings
from test_onebot_ws import wait_until
from websockets.asyncio.server import serve

from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot.events import EventBus
from app.adapters.onebot.exceptions import OneBotArgumentError
from app.adapters.onebot.listener import OneBotListener
from app.adapters.onebot.websocket_client import OneBotWebSocketClient
from app.schemas.management import AccountCreate, NodeCreate
from app.services.onebot import OneBotService
from app.services.unit_of_work import UnitOfWork


@pytest.mark.parametrize('action,params', [
    ('get_group_info', {'group_id':True}), ('get_stranger_info', {'user_id':-1}),
    ('send_private_msg', {'user_id':1}),
    ('send_group_msg', {'group_id':1,'message':[{'data':{}}]}),
    ('delete_msg', {'message_id':'1'}), ('get_status', {'access_token':'never-send'}),
])
async def test_input_schema_prevents_network(action, params):
    async with OneBotAdapter(settings()) as adapter:
        with pytest.raises(OneBotArgumentError):
            await adapter.call(action, params)
        assert not adapter.metrics


async def test_http_ws_listener_simultaneous_recovery(database, management):
    requests = []
    connections = 0
    async def http_handler(reader, writer):
        try:
            headers = (await reader.readuntil(b'\r\n\r\n')).decode()
            path = headers.split(' ')[1]
            length = next(int(line.split(':',1)[1]) for line in headers.splitlines() if line.lower().startswith('content-length:'))
            await reader.readexactly(length)
            requests.append(path)
            assert 'Bearer mock-credential' in headers
            values = {
                '/get_status': {'online':True,'good':True},
                '/get_login_info': {'user_id':123456,'nickname':'Mock'},
                '/get_version_info': {'app_name':'MockNapCat','app_version':'1','protocol_version':'v11'},
                '/get_friend_list': [], '/get_group_list': [],
            }
            body = json.dumps({'status':'ok','retcode':0,'data':values[path]}).encode()
            writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def ws_handler(socket):
        nonlocal connections
        connections += 1
        assert socket.request.headers['Authorization'] == 'Bearer mock-credential'
        if connections == 1:
            await socket.close()
            return
        with suppress(Exception):
            while True:
                await socket.send(json.dumps({'post_type':'meta_event','meta_event_type':'heartbeat',
                    'self_id':123456, 'status':{'online':True,'good':True}}))
                await asyncio.sleep(.025)

    http_server = await asyncio.start_server(http_handler, '127.0.0.1', 0)
    async with http_server, serve(ws_handler, '127.0.0.1', 0) as ws_server:
        config = settings(onebot_poll_interval=.05, onebot_ws_reconnect_min_seconds=.02,
                          onebot_ws_heartbeat_timeout=.2)
        node = await management.create_node(NodeCreate(name='Integration', adapter_type='ONEBOT',
            onebot_http_url=f'http://127.0.0.1:{http_server.sockets[0].getsockname()[1]}',
            onebot_ws_url=f'ws://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}', secret_ref='default'))
        account = await management.create_account(AccountCreate(account_no='123456', platform='QQ', node_id=node.id))
        service = OneBotService(UnitOfWork(database.sessions), config)
        listener = OneBotListener(service, config)
        task = asyncio.create_task(listener.run())
        try:
            await wait_until(lambda: connections >= 2 and '/get_version_info' in requests)
            async with asyncio.timeout(3):
                while (await service.health(node.id)).connection_state != 'CONNECTED':
                    await asyncio.sleep(.02)
            assert (await management.account(account.id)).online_status == 'ONLINE'
            endpoint = await service.endpoint(node.id)
            async with service.adapter(endpoint) as adapter:
                assert await adapter.get_friend_list() == []
                assert await adapter.get_group_list() == []
            assert all(path.startswith('/get_') for path in requests)
        finally:
            listener.stop.set()
            await asyncio.wait_for(task, 3)
            await service.aclose()
        assert all(t.done() for _, t in listener.nodes.values())
        assert not any(t.get_coro().__qualname__ == "EventBus.run" for t in asyncio.all_tasks())


async def test_bad_node_does_not_stop_other_node(database, management):
    await management.create_node(NodeCreate(name='MissingSecret', adapter_type='ONEBOT', secret_ref='missing'))
    good = await management.create_node(NodeCreate(name='Unconfigured', adapter_type='ONEBOT'))
    service = OneBotService(UnitOfWork(database.sessions), settings(onebot_poll_interval=.02))
    listener = OneBotListener(service, service.settings)
    task = asyncio.create_task(listener.run())
    try:
        await wait_until(lambda: good.id in listener.nodes)
        await asyncio.sleep(.1)
        assert not task.done()
        assert not listener.nodes[good.id][1].done()
    finally:
        listener.stop.set()
        await asyncio.wait_for(task, 2)
        await service.aclose()


async def test_healthy_connection_resets_backoff():
    count = 0
    async def server(socket):
        nonlocal count
        count += 1
        if count < 3:
            await socket.close()
            return
        with suppress(Exception):
            for _ in range(10):
                await socket.send(json.dumps({'post_type':'meta_event','meta_event_type':'heartbeat'}))
                await asyncio.sleep(.01)
            await socket.close()
    async with serve(server, '127.0.0.1', 0) as host:
        client = OneBotWebSocketClient(settings(onebot_ws_url=f'ws://127.0.0.1:{host.sockets[0].getsockname()[1]}',
            onebot_ws_reconnect_min_seconds=.05, onebot_ws_reconnect_max_seconds=.2,
            onebot_ws_heartbeat_timeout=.06), EventBus())
        task = asyncio.create_task(client.run())
        try:
            await wait_until(lambda: client.metrics['onebot_ws_reconnect_total'] >= 3)
            assert client.backoff == .05
        finally:
            await client.stop()
            await asyncio.wait_for(task, 2)
