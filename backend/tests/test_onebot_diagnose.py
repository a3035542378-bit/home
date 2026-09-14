import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from test_onebot import response, settings
from websockets.asyncio.server import serve

from app.adapters.onebot.exceptions import OneBotInvalidResponseError, OneBotUnsupportedActionError
from app.adapters.onebot.fake import FakeOneBotAdapter
from app.adapters.onebot.schemas import LoginInfo, VersionInfo
from app.tools.onebot_diagnose import ReadOnlyOneBotAdapter, diagnose, masked_id, websocket_probe


@pytest.mark.parametrize('action', ['send_private_msg', 'send_group_msg', 'delete_msg', 'set_group_add_request'])
async def test_diagnostic_rejects_writes(action):
    async with ReadOnlyOneBotAdapter(settings()) as adapter:
        with pytest.raises(OneBotUnsupportedActionError):
            await adapter.call(action)
        assert not adapter.metrics


async def test_diagnostic_success_statistics_no_payloads():
    fake = FakeOneBotAdapter()
    probe = AsyncMock(return_value={'connect':'PASS','heartbeat':'PASS','event_parse':'PASS'})
    report = await diagnose(settings(), '123456', adapter_factory=lambda _: fake, ws_probe=probe)
    assert report['overall'] == 'READ_ONLY_CHECKS_PASS'
    assert report['actions']['get_friend_list']['count'] == 0
    assert report['actions']['get_group_info']['status'] == 'NOT_TESTED'
    assert report['qq']['user_id'] == '****3456'
    assert '123456' not in json.dumps(report)
    assert 'mock-credential' not in json.dumps(report)
    assert all(action.startswith('get_') for action, _ in fake.calls)


async def test_identity_mismatch_stops_before_lists_and_ws():
    fake = FakeOneBotAdapter()
    probe = AsyncMock()
    result = await diagnose(settings(), '999', adapter_factory=lambda _: fake, ws_probe=probe)
    assert result['identity'] == 'ONEBOT_IDENTITY_MISMATCH'
    assert all(action not in {'get_friend_list','get_group_list'} for action, _ in fake.calls)
    probe.assert_not_awaited()


async def test_auth_failure_is_not_connection_failure():
    original = settings()
    seen = []
    def factory(config):
        seen.append(config.onebot_access_token.get_secret_value())
        return ReadOnlyOneBotAdapter(config, transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    result = await diagnose(original, '123456', adapter_factory=factory, wrong_token=True,
                            ws_probe=AsyncMock(return_value={'authentication':'AUTH_FAILED'}))
    assert result['overall'] == 'AUTH_REJECTION_PASS'
    assert seen[0] != original.onebot_access_token.get_secret_value()
    assert original.onebot_access_token.get_secret_value() == 'mock-credential'
    assert seen[0] not in json.dumps(result)


async def test_version_redacts_known_secret():
    fake = FakeOneBotAdapter()
    fake.get_version_info = AsyncMock(return_value=VersionInfo(app_name='NapCat', app_version='mock-credential', protocol_version='v11'))
    result = await diagnose(settings(), '123456', adapter_factory=lambda _: fake,
        ws_probe=AsyncMock(return_value={'connect':'PASS','heartbeat':'PASS','event_parse':'PASS'}))
    assert 'mock-credential' not in json.dumps(result)


@pytest.mark.parametrize('user_id', [2**53+1, 2**63-1])
def test_large_id_precision_and_unknown_fields(user_id):
    value = LoginInfo.model_validate({'user_id':user_id,'nickname':'mock','extra_future_field':True})
    assert value.user_id == user_id
    assert int(json.loads(value.model_dump_json())['user_id']) == user_id
    assert masked_id(user_id).startswith('****')


@pytest.mark.parametrize('data', [{'online':None,'good':True}, {'good':True}, {'online':'true','good':True}])
async def test_known_status_fields_remain_strict(data):
    async with ReadOnlyOneBotAdapter(settings(), transport=httpx.MockTransport(lambda _: response(data))) as adapter:
        with pytest.raises(OneBotInvalidResponseError):
            await adapter.get_status()


async def test_ws_probe_identity_and_cleanup():
    async def server(socket):
        await socket.send(json.dumps({'post_type':'meta_event','meta_event_type':'heartbeat',
            'self_id':123456,'status':{'online':True,'good':True}}))
        await socket.wait_closed()
    async with serve(server, '127.0.0.1', 0) as host:
        config = settings(onebot_ws_url=f'ws://127.0.0.1:{host.sockets[0].getsockname()[1]}')
        result = await websocket_probe(config, 123456, 1)
        assert result['heartbeat'] == 'PASS'
        assert result['automatic_reconnect'] == 'NOT_TESTED'
        result = await websocket_probe(config, 999, 1)
        assert result['heartbeat'] == 'IDENTITY_OR_SCHEMA_MISMATCH'
    assert not any(t.get_coro().__qualname__ == 'EventBus.run' for t in asyncio.all_tasks())


async def test_reconnect_not_claimed_without_evidence():
    result = await diagnose(settings(), '123456', adapter_factory=lambda _: FakeOneBotAdapter(),
        ws_probe=AsyncMock(return_value={'connect':'PASS','heartbeat':'PASS','event_parse':'PASS'}),
        observe_reconnect=True)
    assert result['overall'] == 'FAIL'
