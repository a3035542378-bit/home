import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.adapters.errors import AdapterConnectionError, AdapterResponseError, AdapterTimeoutError
from app.core.errors import BusinessError
from app.models.common import ExecutionStatus
from app.schemas.management import AccountCreate, AccountUpdate, ConfigUpdate, DefinitionCreate
from app.services.task_runtime import TaskRuntimeService
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import BaseTask, TaskResult
from app.tasks.engine import TaskEngine
from app.tasks.registry import TaskRegistry, load_builtin_tasks, registry


class SuccessTask(BaseTask):
    task_code = "TEST"

    async def execute(self, context):
        return TaskResult(success=True, status=ExecutionStatus.SUCCESS, message="完成")


@pytest.fixture
async def runtime(database, management):
    account = await management.create_account(AccountCreate(account_no="123", platform="QQ"))
    await management.create_definition(DefinitionCreate(task_code="TEST", task_name="测试"))
    await management.put_config(account.id, "TEST", ConfigUpdate(enabled=True))
    return account.id, TaskRuntimeService(UnitOfWork(database.sessions))


def engine(store, task=SuccessTask, **kwargs):
    tasks = TaskRegistry()
    tasks.register(task)
    return TaskEngine(store, tasks, **kwargs)


def test_registry():
    tasks = TaskRegistry()
    assert tasks.register(SuccessTask) is SuccessTask
    assert tasks.get("TEST") is SuccessTask
    with pytest.raises(BusinessError):
        tasks.register(SuccessTask)
    with pytest.raises(BusinessError):
        tasks.register(object)
    with pytest.raises(BusinessError):
        tasks.register(BaseTask)
    with pytest.raises(BusinessError):
        tasks.get("MISSING")


def test_discovery():
    load_builtin_tasks()
    load_builtin_tasks()
    assert issubclass(registry.get("NOT_IMPLEMENTED"), BaseTask)


async def test_success_and_result_persisted(runtime, management):
    account_id, store = runtime
    result = await engine(store).execute(account_id, "TEST")
    assert result.success
    saved = await management.execution(result.execution_id)
    assert saved.status == "SUCCESS"
    assert saved.result_json["execution_id"] == result.execution_id
    assert result.start_time <= result.end_time
    assert (await engine(store).execute(account_id, "TEST")).success


@pytest.mark.parametrize("condition,code", [
    ("account_missing", "ACCOUNT_NOT_FOUND"), ("plugin_missing", "TASK_NOT_FOUND"),
    ("disabled", "TASK_DISABLED"), ("account_disabled", "ACCOUNT_DISABLED"),
])
async def test_preconditions(runtime, management, condition, code):
    account_id, store = runtime
    task_code = "TEST"
    if condition == "disabled":
        await management.put_config(account_id, "TEST", ConfigUpdate(enabled=False))
    elif condition == "account_disabled":
        await management.update_account(account_id, AccountUpdate(status="DISABLED"))
    elif condition == "account_missing":
        account_id = 999
    elif condition == "plugin_missing":
        task_code = "MISSING"
    result = await engine(store).execute(account_id, task_code)
    assert result.error_code == code
    assert not result.success
    assert result.execution_id is None
    assert await management.executions() == []


@pytest.mark.parametrize("error,code", [
    (RuntimeError, "TASK_EXCEPTION"), (AdapterConnectionError, "ADAPTER_CONNECTION_ERROR"),
    (AdapterTimeoutError, "ADAPTER_TIMEOUT"), (AdapterResponseError, "ADAPTER_INVALID_RESPONSE"),
])
async def test_exceptions(runtime, management, error, code):
    class BrokenTask(SuccessTask):
        async def execute(self, context):
            raise error()

    account_id, store = runtime
    result = await engine(store, BrokenTask).execute(account_id, "TEST")
    assert result.error_code == code
    assert (await management.execution(result.execution_id)).status == "FAILED"
    assert (await engine(store).execute(account_id, "TEST")).success


@pytest.mark.parametrize("status", [ExecutionStatus.FAILED, ExecutionStatus.SKIPPED, ExecutionStatus.NEED_USER_ACTION])
async def test_plugin_terminal_results(runtime, status):
    class FailedTask(SuccessTask):
        async def execute(self, context):
            return TaskResult(success=False, status=status, message="需要处理", error_code="USER_CHECK")
    account_id, store = runtime
    result = await engine(store, FailedTask).execute(account_id, "TEST")
    assert result.status == status


async def test_timeout(runtime):
    class SlowTask(SuccessTask):
        async def execute(self, context):
            await asyncio.sleep(10)
    account_id, store = runtime
    result = await engine(store, SlowTask, timeout_seconds=0.01).execute(account_id, "TEST")
    assert result.error_code == "TASK_TIMEOUT"
    assert (await engine(store).execute(account_id, "TEST")).success


async def test_duplicate_across_engine_instances(runtime, management):
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockingTask(SuccessTask):
        async def execute(self, context):
            entered.set()
            await release.wait()
            return await super().execute(context)

    account_id, store = runtime
    first = asyncio.create_task(engine(store, BlockingTask).execute(account_id, "TEST"))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        second = await engine(store, BlockingTask).execute(account_id, "TEST")
        assert second.error_code == "DUPLICATE_EXECUTION"
        assert len(await management.executions()) == 1
        with pytest.raises(BusinessError):
            await management.delete_account(account_id)
    finally:
        release.set()
        await first


async def test_cancellation_releases_claim(runtime):
    entered = asyncio.Event()

    class BlockingTask(SuccessTask):
        async def execute(self, context):
            entered.set()
            await asyncio.sleep(10)

    account_id, store = runtime
    running = asyncio.create_task(engine(store, BlockingTask).execute(account_id, "TEST"))
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert (await engine(store).execute(account_id, "TEST")).success


async def test_invalid_result(runtime):
    class InvalidTask(SuccessTask):
        async def execute(self, context):
            return {"success": True}
    account_id, store = runtime
    result = await engine(store, InvalidTask).execute(account_id, "TEST")
    assert result.error_code == "INVALID_TASK_RESULT"


async def test_storage_failure_does_not_report_success():
    store = AsyncMock()
    from app.tasks.base import AccountContext, TaskContext
    store.begin.return_value = TaskContext(AccountContext(1, "123", "QQ", ""), "placeholder")
    store.finish.side_effect = RuntimeError("do-not-expose")
    result = await engine(store).execute(1, "TEST")
    assert result.error_code == "PERSISTENCE_ERROR"
    assert "do-not-expose" not in result.model_dump_json()


def test_result_invariants():
    with pytest.raises(ValidationError):
        TaskResult(success=True, status=ExecutionStatus.FAILED, message="")
    with pytest.raises(ValidationError):
        TaskResult(success=False, status=ExecutionStatus.RUNNING, message="")
    with pytest.raises(ValidationError):
        TaskResult(success=True, status=ExecutionStatus.SUCCESS, message="", data={"token": "x"})


async def test_context_adapter_injection(runtime):
    adapter = AsyncMock()

    class AdapterTask(SuccessTask):
        async def execute(self, context):
            await context.adapters["onebot"].health_check()
            assert context.account.account_no == "123"
            return await super().execute(context)

    account_id, store = runtime
    result = await engine(store, AdapterTask, adapters={"onebot": adapter}).execute(account_id, "TEST")
    assert result.success
    adapter.health_check.assert_awaited_once()


async def test_missing_definition_and_config(runtime, management):
    account_id, store = runtime

    class UndefinedTask(SuccessTask):
        task_code = "UNDEFINED"

    result = await engine(store, UndefinedTask).execute(account_id, "UNDEFINED")
    assert result.error_code == "TASK_NOT_FOUND"
    other = await management.create_account(AccountCreate(account_no="456", platform="QQ"))
    result = await engine(store).execute(other.id, "TEST")
    assert result.error_code == "TASK_DISABLED"


def test_invalid_registry_plugins():
    class SyncTask(SuccessTask):
        def execute(self, context):
            return None

    class BadCode(SuccessTask):
        task_code = "bad-code"

    class NonStringCode(SuccessTask):
        task_code = 123

    for plugin in (SyncTask, BadCode, NonStringCode):
        with pytest.raises(BusinessError):
            TaskRegistry().register(plugin)


async def test_default_status_and_not_implemented():
    load_builtin_tasks()
    task = registry.get("NOT_IMPLEMENTED")()
    from app.tasks.base import AccountContext, TaskContext
    context = TaskContext(AccountContext(1, "123", "QQ", ""), "test")
    assert (await task.execute(context)).error_code == "NOT_IMPLEMENTED"
    assert (await task.check_status(context)).status == ExecutionStatus.SKIPPED


async def test_bootstrap_closes_resources(monkeypatch):
    from app.core.config import Settings
    from app.tasks.bootstrap import task_engine
    db, adapter = AsyncMock(), AsyncMock()
    adapter.__aenter__.return_value = adapter
    monkeypatch.setattr("app.tasks.bootstrap.Database", lambda _: db)
    monkeypatch.setattr("app.tasks.bootstrap.RuntimeAdapters", lambda *args: adapter)
    async with task_engine(Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")) as built:
        assert isinstance(built, TaskEngine)
        assert built.adapter_provider is adapter
    db.close.assert_awaited_once()
    adapter.aclose.assert_awaited_once()


async def test_simultaneous_database_claim(runtime):
    account_id, store = runtime
    from app.models.common import TriggerType, utcnow
    results = await asyncio.gather(*(
        store.begin(account_id, "TEST", f"claim-{i}", TriggerType.MANUAL, utcnow())
        for i in range(2)
    ), return_exceptions=True)
    assert sum(isinstance(r, BusinessError) for r in results) == 1
    rejected = next(r for r in results if isinstance(r, BusinessError))
    assert rejected.code == "DUPLICATE_EXECUTION"
