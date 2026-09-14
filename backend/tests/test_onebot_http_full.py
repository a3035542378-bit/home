import asyncio
import io
import logging

import httpx
import pytest
from test_onebot import response, settings

from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot.capability import ACTIONS, ActionType
from app.adapters.onebot.exceptions import (
    OneBotApiError,
    OneBotAuthenticationError,
    OneBotConnectionError,
    OneBotError,
    OneBotInvalidResponseError,
    OneBotRateLimitError,
    OneBotUnsupportedActionError,
)
from app.core.logging import SensitiveDataFilter


@pytest.mark.parametrize('action,params,data', [
    ('get_status', {}, {'online': True, 'good': True}),
    ('get_version_info', {}, {'app_name': 'NapCat', 'app_version': 'mock', 'protocol_version': 'v11'}),
    ('get_friend_list', {}, [{'user_id': 1, 'nickname': 'A', 'remark': ''}]),
    ('get_group_list', {}, [{'group_id': 2, 'group_name': 'G'}]),
    ('get_group_info', {'group_id': 2}, {'group_id': 2, 'group_name': 'G'}),
    ('get_stranger_info', {'user_id': 1}, {'user_id': 1, 'nickname': 'A'}),
    ('send_private_msg', {'user_id': 1, 'message': 'mock'}, {'message_id': 3}),
    ('send_group_msg', {'group_id': 2, 'message': 'mock'}, {'message_id': 4}),
    ('delete_msg', {'message_id': 3}, None),
])
async def test_standard_actions(action, params, data):
    import json
    def handler(request):
        assert request.url.path == '/' + action
        assert json.loads(request.content) == params
        return response(data)
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(handler)) as adapter:
        result = await getattr(adapter, action)(**params)
        assert result is not None or action == 'delete_msg'
        assert adapter.metrics['onebot_http_requests_total'] == 1


@pytest.mark.parametrize('status,error', [(401, OneBotAuthenticationError), (403, OneBotAuthenticationError),
    (429, OneBotRateLimitError), (404, OneBotUnsupportedActionError), (502, OneBotApiError)])
async def test_http_categories(status, error):
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(status))) as adapter:
        with pytest.raises(error) as caught:
            await adapter.get_status()
        assert caught.value.action == 'get_status'
        assert caught.value.error_code.startswith('ONEBOT_')
        assert not caught.value.retryable


@pytest.mark.parametrize('action,params', [('send_private_msg', {'user_id':1, 'message':'mock'}),
    ('send_group_msg', {'group_id':2, 'message':'mock'}), ('delete_msg', {'message_id':3})])
@pytest.mark.parametrize('failure', ['connection', 'timeout', 'http'])
async def test_writes_never_retry(action, params, failure):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if failure == 'connection':
            raise httpx.ConnectError('secret')
        if failure == 'timeout':
            raise httpx.ReadTimeout('secret')
        return httpx.Response(503)
    async with OneBotAdapter(settings(onebot_max_retries=2), transport=httpx.MockTransport(handler)) as adapter:
        with pytest.raises(OneBotError):
            await getattr(adapter, action)(**params)
    assert count == 1


async def test_read_5xx_retry_budget():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503) if calls < 3 else response({'online':True, 'good':True})
    async with OneBotAdapter(settings(onebot_max_retries=2), transport=httpx.MockTransport(handler)) as adapter:
        assert (await adapter.get_status()).online
        assert adapter.metrics == {'onebot_http_requests_total':3, 'onebot_http_errors_total':2}
    assert calls == 3


@pytest.mark.parametrize('data', [None, {}, ['bad'], [{'user_id':True, 'nickname':'bad'}]])
async def test_strict_lists(data):
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(lambda _: response(data))) as adapter:
        with pytest.raises(OneBotInvalidResponseError):
            await adapter.get_friend_list()


async def test_unsupported_call_no_http():
    async with OneBotAdapter(settings()) as adapter:
        with pytest.raises(OneBotUnsupportedActionError):
            await adapter.call('daily_checkin')
        assert not adapter.metrics
    assert ACTIONS['get_status'].action_type == ActionType.READ
    assert not ACTIONS['delete_msg'].retryable


@pytest.mark.parametrize('text', ['Bearer abc123', 'access_token=abc123', 'Cookie: abc123',
    'Authorization: Bearer abc123', '{"token": "abc123"}', 'password=abc123', 'session=abc123'])
def test_sensitive_filter(text):
    output = io.StringIO()
    logger = logging.getLogger('onebot-test-isolated')
    handler = logging.StreamHandler(output)
    handler.addFilter(SensitiveDataFilter())
    logger.addHandler(handler)
    logger.warning('%s', text)
    assert 'abc123' not in output.getvalue()
    assert 'REDACTED' in output.getvalue()
    logger.removeHandler(handler)


async def test_response_text_redacted():
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        'status':'ok', 'retcode':0, 'data':{}, 'message':'Bearer abc123', 'wording':'password=x',
    }))) as adapter:
        result = await adapter.call('get_status')
        assert result.message == result.wording == ''


async def test_cancellation_not_retried():
    async def handler(request):
        raise asyncio.CancelledError()
    async with OneBotAdapter(settings(onebot_max_retries=2), transport=httpx.MockTransport(handler)) as adapter:
        with pytest.raises(asyncio.CancelledError):
            await adapter.get_status()
        assert adapter.metrics['onebot_http_requests_total'] == 1


async def test_connection_failure_exhaustion():
    def handler(request):
        raise httpx.ConnectError('Authorization: abc123')
    async with OneBotAdapter(settings(onebot_max_retries=2), transport=httpx.MockTransport(handler)) as adapter:
        with pytest.raises(OneBotConnectionError) as error:
            await adapter.get_status()
        assert adapter.metrics['onebot_http_requests_total'] == 3
        assert 'abc123' not in str(error.value)
        assert error.value.__cause__ is None


async def test_business_failure_never_retried():
    async with OneBotAdapter(settings(onebot_max_retries=2), transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'status':'failed','retcode':100,'data':None,'wording':'secret'}),
    )) as adapter:
        with pytest.raises(OneBotApiError):
            await adapter.get_friend_list()
        assert adapter.metrics['onebot_http_requests_total'] == 1


async def test_delete_response_validation():
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(lambda _: response('invalid'))) as adapter:
        with pytest.raises(OneBotInvalidResponseError):
            await adapter.delete_msg(1)
