import json
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot.exceptions import OneBotTimeoutError
from app.adapters.onebot.fake import FakeOneBotAdapter
from app.adapters.onebot.retry_scope import retry_scope
from app.core.config import Settings
from app.models.common import utcnow
from app.schemas.management import AccountCreate, ConfigUpdate, DefinitionCreate, NodeCreate
from app.services.account_runtime import AccountRuntimeReader
from app.services.dispatch import DispatchService
from app.services.onebot import OneBotService
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import AccountContext, TaskContext
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks, registry

CODES = ("QQ_ACCOUNT_STATUS", "QQ_FRIEND_SUMMARY", "QQ_GROUP_SUMMARY", "QQ_RUNTIME_STATUS")


async def run(code, fake=None, config=None, services=None, account_no="123456", provider=None):
    load_builtin_tasks()
    context = TaskContext(
        AccountContext(1, account_no, "QQ", "", 1),
        "business-test",
        config or {},
        services=services or {},
    )
    return await TaskEngine(
        None, adapters={"onebot": fake or FakeOneBotAdapter()}, adapter_provider=provider
    ).run(code, context)


@pytest.mark.parametrize("code", CODES)
def test_metadata(code):
    load_builtin_tasks()
    task = registry.get(code)
    assert task.read_only and task.idempotent and not task.diagnostic_only and not task.scheduled
    assert task.category == "QQ_ACCOUNT" and task.risk_level == "SAFE_READONLY"
    assert task.task_version == task.plugin_version == "1.0.0"


async def test_account_success():
    result = await run("QQ_ACCOUNT_STATUS")
    assert result.success
    assert result.data == {
        "account_id": 1,
        "qq": "***3456",
        "nickname": "Mock",
        "online": True,
        "good": True,
        "connection_state": "CONNECTED",
    }
    assert set(result.evidence) == {"node_id", "checked_at", "connection_state"}


@pytest.mark.parametrize(
    "mode,error,retry",
    [
        ("offline", "ONEBOT_OFFLINE", False),
        ("timeout", "ONEBOT_TIMEOUT", False),
        ("retryable_timeout", "ONEBOT_TIMEOUT", True),
        ("auth", "ONEBOT_AUTH_FAILED", False),
        ("invalid", "ONEBOT_INVALID_RESPONSE", False),
    ],
)
async def test_account_errors(mode, error, retry):
    result = await run("QQ_ACCOUNT_STATUS", FakeOneBotAdapter(mode))
    assert result.error_code == error and result.retryable is retry


async def test_mismatch_not_retry():
    result = await run("QQ_ACCOUNT_STATUS", account_no="987654")
    assert result.error_code == "ONEBOT_ACCOUNT_MISMATCH" and not result.retryable


@pytest.mark.parametrize("code", CODES)
async def test_missing_capability(code):
    fake = FakeOneBotAdapter()
    fake.capabilities = dict
    result = await run(code, fake)
    assert result.error_code == "CAPABILITY_UNSUPPORTED" and not fake.calls


@pytest.mark.parametrize("count", [0, 3, 20000])
async def test_friend_counts_only(count, caplog):
    fake = FakeOneBotAdapter(friend_count=count)
    result = await run("QQ_FRIEND_SUMMARY", fake, {"include_category_counts": True})
    assert result.success and result.data == {
        "friend_count": count,
        "remark_count": count // 2,
        "nickname_count": count,
    }
    assert fake.calls == [("get_friend_list", None)]
    assert all(
        x not in result.model_dump_json() + caplog.text
        for x in ("friend-private", "remark-private", "800000")
    )


@pytest.mark.parametrize("count", [0, 3, 20000])
async def test_group_counts_only(count, caplog):
    fake = FakeOneBotAdapter(group_count=count)
    result = await run("QQ_GROUP_SUMMARY", fake, {"include_role_counts": True})
    assert result.success and result.data == {
        "group_count": count,
        "role_counts_supported": False,
        "owned_group_count": None,
        "admin_group_count": None,
    }
    assert fake.calls == [("get_group_list", None)]
    assert all(x not in result.model_dump_json() + caplog.text for x in ("group-private", "900000"))


@pytest.mark.parametrize("code", ["QQ_FRIEND_SUMMARY", "QQ_GROUP_SUMMARY"])
async def test_summary_timeout(code):
    result = await run(code, FakeOneBotAdapter("retryable_timeout"))
    assert result.error_code == "ONEBOT_TIMEOUT" and result.retryable


@pytest.mark.parametrize(
    "code,config",
    [
        ("QQ_ACCOUNT_STATUS", {"extra": 1}),
        ("QQ_FRIEND_SUMMARY", {"include_category_counts": "true"}),
        ("QQ_GROUP_SUMMARY", {"include_role_counts": 1}),
        ("QQ_RUNTIME_STATUS", {"execution_history_hours": 0}),
        ("QQ_RUNTIME_STATUS", {"execution_history_hours": 169}),
        ("QQ_RUNTIME_STATUS", {"execution_history_hours": True}),
    ],
)
async def test_config_before_adapter(code, config):
    fake = FakeOneBotAdapter()
    result = await run(code, fake, config)
    assert result.error_code == "TASK_CONFIG_INVALID" and not fake.calls


@pytest.mark.parametrize(
    "online,good,state",
    [(True, True, "CONNECTED"), (True, False, "DEGRADED"), (False, False, "OFFLINE")],
)
async def test_runtime_health(online, good, state):
    reader = AsyncMock()
    reader.snapshot.return_value = {
        "account_status": "ACTIVE",
        "node_status": "CONNECTED" if good else "DISCONNECTED",
        "last_execution_status": None,
        "last_success_execution": None,
        "last_failed_execution": None,
        "worker_status": "UNASSIGNED",
    }
    result = await run(
        "QQ_RUNTIME_STATUS",
        FakeOneBotAdapter(online=online, good=good),
        services={"account_runtime": reader},
    )
    assert result.success and result.data["onebot_status"] == state
    assert (
        result.data["node_status"] == ("CONNECTED" if good else "DISCONNECTED")
        and result.data["last_execution_status"] is None
    )
    reader.snapshot.assert_awaited_once_with(24)


async def test_runtime_scoped_history(database, management):
    from app.models import TaskExecution

    now = utcnow()
    node = await management.create_node(NodeCreate(name="runtime", adapter_type="ONEBOT"))
    a = await management.create_account(
        AccountCreate(account_no="1", platform="QQ", node_id=node.id)
    )
    b = await management.create_account(AccountCreate(account_no="2", platform="QQ"))
    await management.create_definition(DefinitionCreate(task_code="HISTORY", task_name="history"))
    async with database.sessions() as session, session.begin():
        for execution_id, account_id, status, hours in [
            ("old", a.id, "SUCCESS", 25),
            ("good", a.id, "SUCCESS", 2),
            ("bad", a.id, "FAILED", 1),
            ("other", b.id, "SUCCESS", 0),
        ]:
            session.add(
                TaskExecution(
                    execution_id=execution_id,
                    account_id=account_id,
                    task_code="HISTORY",
                    trigger_type="MANUAL",
                    status=status,
                    created_at=now - timedelta(hours=hours),
                    end_time=now - timedelta(hours=hours),
                    result_json={"private": "not-for-runtime"},
                )
            )
    reader = AccountRuntimeReader(UnitOfWork(database.sessions), a.id, "current", clock=lambda: now)
    result = await reader.snapshot(24)
    assert result["last_success_execution"]["execution_id"] == "good"
    assert result["last_failed_execution"]["execution_id"] == "bad"
    assert "other" not in str(result) and "not-for-runtime" not in str(result)
    assert (await reader.snapshot(1))["last_success_execution"] is None
    with pytest.raises(TypeError):
        await reader.snapshot(account_id=b.id)


async def test_not_scheduled(database, management):
    load_builtin_tasks()
    account = await management.create_account(AccountCreate(account_no="qq", platform="QQ"))
    for code in CODES:
        await management.create_definition(DefinitionCreate(task_code=code, task_name=code))
        await management.put_config(account.id, code, ConfigUpdate(enabled=True))
    service = DispatchService(
        UnitOfWork(database.sessions),
        Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:"),
    )
    assert await service.schedule() == 0


async def test_status_provider_allows_offline_without_identity_data(database, management):
    node = await management.create_node(NodeCreate(name="offline", adapter_type="ONEBOT"))
    account = await management.create_account(
        AccountCreate(account_no="123456", platform="QQ", node_id=node.id)
    )
    fake = FakeOneBotAdapter(online=False, good=False)
    provider = OneBotService(
        UnitOfWork(database.sessions),
        Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:"),
        adapter_factory=lambda _: fake,
    )
    load_builtin_tasks()
    context = TaskContext(
        AccountContext(account.id, account.account_no, "QQ", "", node.id),
        "status",
        services={
            "account_runtime": AccountRuntimeReader(
                UnitOfWork(database.sessions), account.id, "status"
            )
        },
    )
    try:
        result = await TaskEngine(None, adapter_provider=provider).run("QQ_RUNTIME_STATUS", context)
        assert result.success and result.data["onebot_status"] == "OFFLINE"
        assert fake.calls == [("get_status", None)]
    finally:
        await provider.aclose()


async def test_retry_scope_one_http_attempt_and_no_write_retry():
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("private-request")

    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        onebot_http_url="http://fake",
        onebot_max_retries=2,
    )
    async with OneBotAdapter(settings, transport=httpx.MockTransport(handler)) as onebot:
        with retry_scope(True):
            with pytest.raises(OneBotTimeoutError) as exc:
                await onebot.get_status()
            assert exc.value.retryable and len(calls) == 1
            with pytest.raises(OneBotTimeoutError) as write:
                await onebot.call("send_private_msg", {"user_id": 1, "message": "fixture"})
            assert not write.value.retryable and len(calls) == 2
    assert "private-request" not in str(exc.value)


@pytest.mark.parametrize(
    "mode,child_count", [("retryable_timeout", 1), ("auth", 0), ("offline", 0)]
)
async def test_worker_retry_new_record(database, management, broker, mode, child_count):
    from app.queue.redis_stream import RedisTaskQueue
    from app.workers.worker import Worker

    load_builtin_tasks()
    redis, prefix = broker
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        task_lock_prefix=prefix + ":lock:",
        auto_retry_base_seconds=0,
    )
    queue = RedisTaskQueue(redis, prefix, dlq=prefix + ":dlq")
    service = DispatchService(UnitOfWork(database.sessions), settings, queue)
    account = await management.create_account(AccountCreate(account_no="123456", platform="QQ"))
    await management.create_definition(
        DefinitionCreate(task_code="QQ_ACCOUNT_STATUS", task_name="status")
    )
    await management.put_config(account.id, "QQ_ACCOUNT_STATUS", ConfigUpdate(enabled=True))
    worker = Worker(
        queue,
        service,
        TaskEngine(None, adapters={"onebot": FakeOneBotAdapter(mode)}),
        redis,
        settings,
    )
    item = await service.submit(account.id, "QQ_ACCOUNT_STATUS")
    await service.publish()
    await worker.process(await queue.dequeue())
    rows = await management.executions()
    assert len(rows) == 1 + child_count
    assert (await service.get(item.execution_id)).status == "FAILED"
    if child_count:
        assert rows[0].parent_execution_id == item.execution_id and rows[0].status == "PENDING"
    assert "friend-private" not in json.dumps([r.result_json for r in rows])


async def test_actual_adapter_retry_delegation_through_provider(database, management):
    calls = []
    async def timeout(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("do-not-log")
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", onebot_max_retries=2)
    node = await management.create_node(NodeCreate(name="retry-owner", adapter_type="ONEBOT", onebot_http_url="http://fake"))
    account = await management.create_account(AccountCreate(account_no="123456", platform="QQ", node_id=node.id))
    provider = OneBotService(UnitOfWork(database.sessions), settings,
        adapter_factory=lambda config: OneBotAdapter(config, transport=httpx.MockTransport(timeout)))
    load_builtin_tasks()
    context = TaskContext(AccountContext(account.id, account.account_no, "QQ", "", node.id), "delegation")
    try:
        result = await TaskEngine(None, adapter_provider=provider).run("QQ_ACCOUNT_STATUS", context)
        assert result.error_code == "ONEBOT_TIMEOUT" and result.retryable
        assert len(calls) == 1
    finally:
        await provider.aclose()


async def test_runtime_worker_lease_and_empty_history(database, management):
    from app.models import TaskExecution
    now = utcnow()
    a = await management.create_account(AccountCreate(account_no="lease", platform="QQ"))
    await management.create_definition(DefinitionCreate(task_code="LEASE_TEST", task_name="lease"))
    async with database.sessions() as session, session.begin():
        session.add(TaskExecution(execution_id="current", account_id=a.id, task_code="LEASE_TEST", trigger_type="MANUAL",
            status="RUNNING", worker_id="internal-worker", lease_until=now+timedelta(seconds=30)))
    reader = AccountRuntimeReader(UnitOfWork(database.sessions), a.id, "current", clock=lambda: now)
    snapshot = await reader.snapshot()
    assert snapshot["worker_status"] == "LEASE_ACTIVE" and snapshot["node_status"] == "NOT_CONFIGURED"
    assert snapshot["last_success_execution"] is None and snapshot["last_failed_execution"] is None
    assert "internal-worker" not in str(snapshot)
    reader._clock = lambda: now + timedelta(seconds=31)
    assert (await reader.snapshot())["worker_status"] == "LEASE_EXPIRED"


async def test_retry_scope_isolated_between_coroutines():
    import asyncio

    from app.adapters.onebot.retry_scope import worker_owns_retry
    entered, checked = asyncio.Event(), asyncio.Event()
    async def delegated():
        with retry_scope(True):
            entered.set()
            await checked.wait()
            assert worker_owns_retry.get()
        assert not worker_owns_retry.get()
    async def normal():
        await entered.wait()
        assert not worker_owns_retry.get()
        checked.set()
    await asyncio.gather(delegated(), normal())


async def test_acceptance_outbox_scoped_to_own_account(database, management):
    from app.tools.business_acceptance import AcceptanceDispatch
    load_builtin_tasks()
    settings = Settings(_env_file=None, database_url='sqlite+aiosqlite:///:memory:')
    await management.create_definition(DefinitionCreate(task_code='QQ_ACCOUNT_STATUS', task_name='status'))
    accounts = [await management.create_account(AccountCreate(account_no=number, platform='QQ')) for number in ('own', 'other')]
    queue = AsyncMock()
    service = AcceptanceDispatch(UnitOfWork(database.sessions), settings, queue)
    for account in accounts:
        await management.put_config(account.id, 'QQ_ACCOUNT_STATUS', ConfigUpdate(enabled=True))
        await service.submit(account.id, 'QQ_ACCOUNT_STATUS')
    service.account_id = accounts[0].id
    assert await service.maintain() == 1
    assert queue.enqueue.await_args.args[0].account_id == accounts[0].id
    async with UnitOfWork(database.sessions).transaction() as repos:
        pending = await repos.dispatch.outbox(utcnow(), 30)
    assert [job.account_id for job in pending] == [accounts[1].id]


async def test_status_only_adapter_has_no_identity_or_list_methods():
    from app.services.onebot import StatusOnlyAdapter
    adapter = StatusOnlyAdapter(FakeOneBotAdapter())
    assert adapter.capabilities() == {'status': True}
    assert not hasattr(adapter, 'get_friend_list') and not hasattr(adapter, 'get_login_info')
    assert (await adapter.get_status()).online


async def test_runtime_history_equal_timestamp_uses_record_order(database, management):
    from app.models import TaskExecution
    now = utcnow().replace(microsecond=0)
    account = await management.create_account(AccountCreate(account_no='tie', platform='QQ'))
    await management.create_definition(DefinitionCreate(task_code='TIE', task_name='tie'))
    async with database.sessions() as session, session.begin():
        for status in ('SUCCESS', 'FAILED'):
            session.add(TaskExecution(execution_id=status, account_id=account.id, task_code='TIE',
                                     trigger_type='MANUAL', status=status, created_at=now, end_time=now))
            await session.flush()
    reader = AccountRuntimeReader(UnitOfWork(database.sessions), account.id, 'current', clock=lambda: now)
    result = await reader.snapshot()
    assert result['last_execution_status'] == 'FAILED'
    assert '_order' not in str(result)
