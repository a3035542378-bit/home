from dataclasses import replace
from datetime import timedelta
from typing import ClassVar
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from test_onebot import settings

from app.adapters.onebot.events import parse_event
from app.adapters.onebot.fake import FakeOneBotAdapter
from app.core.errors import BusinessError
from app.main import create_app
from app.models.common import ExecutionStatus, utcnow
from app.schemas.management import AccountCreate, NodeCreate
from app.schemas.onebot import NodeConnection
from app.services.onebot import OneBotService
from app.services.system_service import SystemService
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import AccountContext, BaseTask, TaskContext, TaskResult
from app.tasks.engine import TaskEngine
from app.tasks.registry import TaskRegistry


@pytest.fixture
async def node_setup(database, management):
    node = await management.create_node(NodeCreate(name='A', adapter_type='ONEBOT',
        onebot_http_url='http://node-a:3000', onebot_ws_url='ws://node-a:3001', secret_ref='node_a'))
    account = await management.create_account(AccountCreate(account_no='123456', platform='QQ', node_id=node.id))
    service = OneBotService(UnitOfWork(database.sessions), settings(onebot_node_tokens='{"node_a":"test-only"}'),
                            adapter_factory=lambda _: FakeOneBotAdapter())
    yield node, account, service
    await service.aclose()


@pytest.mark.parametrize('state,expected', [('CONNECTED','CONNECTED'), ('DISCONNECTED','DEGRADED'),
    ('UNKNOWN','DEGRADED'), ('AUTH_FAILED','AUTH_FAILED')])
async def test_node_states_and_account(node_setup, management, state, expected):
    node, account, service = node_setup
    endpoint = await service.endpoint(node.id)
    await service.ws_state(endpoint, state)
    health = await service.health(node.id)
    assert health.connection_state == expected
    assert health.account_id == account.id
    assert (await management.account(account.id)).online_status == 'ONLINE'
    assert 'test-only' not in health.model_dump_json()


@pytest.mark.parametrize('mode', ['connection', 'timeout', 'api', 'invalid'])
async def test_node_failures_leave_account_enabled(node_setup, management, mode):
    node, account, service = node_setup
    service.adapter_factory = lambda _: FakeOneBotAdapter(mode)
    result = await service.health(node.id)
    assert result.connection_state == 'DISCONNECTED'
    assert result.error_code.startswith('ONEBOT_')
    saved = await management.account(account.id)
    assert saved.status == 'ACTIVE'
    assert saved.online_status == 'UNKNOWN'


async def test_node_identity_mismatch(node_setup, management):
    node, account, service = node_setup
    service.adapter_factory = lambda _: FakeOneBotAdapter(user_id=999)
    result = await service.health(node.id)
    assert result.error_code == 'ONEBOT_IDENTITY_MISMATCH'
    assert (await management.account(account.id)).online_status == 'UNKNOWN'


async def test_two_nodes_separate_credentials_and_clients(node_setup, management):
    node, _, service = node_setup
    other = await management.create_node(NodeCreate(name='B', adapter_type='ONEBOT', onebot_http_url='http://node-b:3000'))
    first, second = await service.endpoint(node.id), await service.endpoint(other.id)
    assert service.connection_settings(first).onebot_access_token.get_secret_value() == 'test-only'
    assert service.connection_settings(second).onebot_access_token.get_secret_value() == ''
    async with service.adapter(first) as a, service.adapter(second) as b, service.adapter(first) as again:
        assert a is again and a is not b
    assert service.connection_settings(second).onebot_http_url.get_secret_value() == 'http://node-b:3000'


async def test_configuration_revision_fences_old_events(node_setup, management):
    node, account, service = node_setup
    old = await service.endpoint(node.id)
    await service.configure(node.id, NodeConnection(onebot_http_url='http://new-node'))
    await service.ws_state(old, 'CONNECTED')
    event = parse_event('{"self_id":123456,"post_type":"meta_event","meta_event_type":"heartbeat","status":{"online":true,"good":true}}')
    await service.event_status(old, event)
    assert (await management.account(account.id)).online_status == 'UNKNOWN'
    async with service.uow.transaction() as repos:
        saved = await repos.nodes.get(node.id)
        assert saved.ws_state == 'UNKNOWN'
        assert saved.config_revision == old.revision + 1


async def test_events_update_only_bound_identity(node_setup, management):
    node, account, service = node_setup
    other = await management.create_account(AccountCreate(account_no='999', platform='QQ', node_id=node.id))
    endpoint = await service.endpoint(node.id)
    await service.event_status(endpoint, parse_event('{"self_id":123456,"post_type":"meta_event","meta_event_type":"heartbeat","status":{"online":true,"good":true}}'))
    assert (await management.account(account.id)).online_status == 'ONLINE'
    assert (await management.account(other.id)).online_status == 'UNKNOWN'
    await service.event_status(endpoint, parse_event('{"self_id":123456,"post_type":"meta_event","meta_event_type":"heartbeat","status":{"online":false,"good":false}}'))
    assert (await management.account(account.id)).online_status == 'OFFLINE'


async def test_stale_ws_is_degraded(node_setup):
    node, _, service = node_setup
    async with service.uow.transaction() as repos:
        saved = await repos.nodes.get(node.id)
        saved.ws_state, saved.ws_seen_at = 'CONNECTED', utcnow() - timedelta(minutes=10)
    assert (await service.health(node.id)).connection_state == 'DEGRADED'


@pytest.mark.parametrize('value', ['http://user:secret@node', 'http://node?access_token=x', 'ftp://node', 'http://node#secret'])
def test_node_url_rejects_secrets(value):
    with pytest.raises(ValidationError):
        NodeConnection(onebot_http_url=value)


async def test_missing_secret_and_explicit_default(node_setup):
    node, _, service = node_setup
    endpoint = await service.endpoint(node.id)
    with pytest.raises(BusinessError, match='节点凭据引用未配置'):
        service.connection_settings(replace(endpoint, secret_ref='missing'))
    config = service.connection_settings(replace(endpoint, http_url=None, secret_ref=None))
    assert config.onebot_http_url is None
    config = service.connection_settings(replace(endpoint, http_url=None, secret_ref='default'))
    assert config.onebot_http_url == service.settings.onebot_http_url


class CapabilityTask(BaseTask):
    task_code = 'CAPABILITY_TEST'
    required_capabilities: ClassVar[dict[str, set[str]]] = {'onebot': {'login_info'}}
    async def execute(self, context):
        result = await context.get_adapter('onebot').get_login_info()
        return TaskResult(success=True, status=ExecutionStatus.SUCCESS, message='完成', data={'user_id':result.user_id})


def task_engine(**kwargs):
    registry = TaskRegistry()
    registry.register(CapabilityTask)
    return TaskEngine(None, registry, **kwargs)


@pytest.mark.parametrize('mode,code', [('success',None), ('connection','ONEBOT_CONNECTION_ERROR'),
    ('timeout','ONEBOT_TIMEOUT'), ('api','ONEBOT_API_ERROR'), ('invalid','ONEBOT_INVALID_RESPONSE')])
async def test_engine_fake_adapter(mode, code):
    context = TaskContext(AccountContext(1,'123456','QQ',''), 'execution')
    engine = task_engine(adapters={'onebot':FakeOneBotAdapter(mode)})
    result = await engine.run(CapabilityTask.task_code, context)
    assert result.error_code == code


async def test_engine_missing_and_unsupported_capability():
    context = TaskContext(AccountContext(1,'123456','QQ',''), 'execution')
    assert (await task_engine().run(CapabilityTask.task_code, context)).error_code == 'ADAPTER_NOT_CONFIGURED'
    fake = FakeOneBotAdapter()
    fake.capabilities = lambda: {'login_info':False}
    result = await task_engine(adapters={'onebot':fake}).run(CapabilityTask.task_code, context)
    assert result.error_code == 'CAPABILITY_UNSUPPORTED'
    assert fake.calls == []


async def test_engine_node_provider_identity(node_setup):
    node, account, service = node_setup
    context = TaskContext(AccountContext(account.id, account.account_no, 'QQ', '', node.id), 'execution')
    engine = task_engine(adapter_provider=service)
    assert (await engine.run(CapabilityTask.task_code, context)).success
    wrong = replace(context, account=replace(context.account, account_no='999'))
    assert (await engine.run(CapabilityTask.task_code, wrong)).error_code == 'ONEBOT_IDENTITY_MISMATCH'
    unbound = replace(context, account=replace(context.account, node_id=None))
    assert (await engine.run(CapabilityTask.task_code, unbound)).error_code == 'NODE_NOT_CONFIGURED'


async def test_core_health_not_affected_by_onebot():
    optional = AsyncMock()
    optional.summary.side_effect = RuntimeError('secret')
    result = await SystemService(AsyncMock(), AsyncMock(), 1, optional).health()
    assert result.status == 'ok'
    assert result.onebot == {'state':'UNKNOWN'}


async def test_node_api_auth_validation(node_setup):
    node, _, service = node_setup
    app = create_app()
    app.state.settings = settings(admin_access_token='test-only')
    app.state.onebot = service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get(f'/api/nodes/{node.id}/health')).status_code == 401
        client.headers['Authorization'] = 'Bearer test-only'
        result = await client.get(f'/api/nodes/{node.id}/health')
        assert result.status_code == 200
        assert 'test-only' not in result.text and 'onebot_http_url' not in result.text
        result = await client.put(f'/api/nodes/{node.id}/connection', json={'onebot_http_url':'http://node?token=private'})
        assert result.status_code == 422 and 'private' not in result.text
        assert (await client.put(f'/api/nodes/{node.id}/connection', json={'onebot_http_url':'http://node-new'})).status_code == 204
        assert (await client.get('/api/nodes/9999/health')).status_code == 404


async def test_account_rebinding_resets_online_status(node_setup, management):
    from app.schemas.management import AccountUpdate
    node, account, service = node_setup
    await service.health(node.id)
    assert (await management.account(account.id)).online_status == 'ONLINE'
    await management.update_account(account.id, AccountUpdate(node_id=None))
    assert (await management.account(account.id)).online_status == 'UNKNOWN'


async def test_error_counters_visible_in_health(node_setup):
    from app.adapters.onebot import OneBotAdapter
    node, _, service = node_setup
    service.adapter_factory = lambda config: OneBotAdapter(config, transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    result = await service.health(node.id)
    assert result.metrics['onebot_http_errors_total'] == 1
    assert result.metrics['onebot_http_requests_total'] == 1
