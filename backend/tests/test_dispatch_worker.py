import asyncio
from datetime import timedelta

import pytest

from app.adapters.errors import AdapterTimeoutError
from app.core.config import Settings
from app.core.errors import BusinessError
from app.models.common import ExecutionStatus as S
from app.models.common import utcnow
from app.queue.base import TaskJob
from app.queue.redis_stream import RedisTaskQueue
from app.schemas.management import AccountCreate, AccountUpdate, ConfigUpdate, DefinitionCreate
from app.services.dispatch import DispatchService
from app.services.execution_state import ExecutionStateMachine
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import BaseTask, TaskResult
from app.tasks.engine import TaskEngine
from app.tasks.registry import TaskRegistry, load_builtin_tasks
from app.workers.heartbeat import list_workers
from app.workers.worker import Worker


@pytest.fixture
async def chain(database, management, broker):
    redis, prefix = broker
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:",
                        task_stream_name=prefix, task_dlq_name=prefix + ":dlq",
                        task_lock_prefix=prefix + ":lock:", worker_key_prefix=prefix + ":worker:",
                        task_timeout_seconds=0.03, execution_lease_seconds=0.3, task_lock_ttl=0.3,
                        auto_retry_base_seconds=0, maintenance_interval=0.03,
                        worker_heartbeat_interval=0.03, worker_shutdown_timeout=0.02)
    load_builtin_tasks()
    account = await management.create_account(AccountCreate(account_no="worker-test", platform="WEB"))
    for code in ("MOCK_SUCCESS", "MOCK_FAIL", "MOCK_TIMEOUT", "MOCK_NEED_USER_ACTION"):
        await management.create_definition(DefinitionCreate(task_code=code, task_name=code))
        await management.put_config(account.id, code, ConfigUpdate(enabled=True))
    queue = RedisTaskQueue(redis, prefix, dlq=prefix + ":dlq", reclaim_ms=300)
    service = DispatchService(UnitOfWork(database.sessions), settings, queue)
    worker = Worker(queue, service, TaskEngine(None, timeout_seconds=0.03), redis, settings, "test-worker")
    return account.id, service, worker, queue, settings


@pytest.mark.parametrize("code,status,error", [
    ("MOCK_SUCCESS", S.SUCCESS, None), ("MOCK_FAIL", S.FAILED, "MOCK_FAILURE"),
    ("MOCK_TIMEOUT", S.FAILED, "TASK_TIMEOUT"),
    ("MOCK_NEED_USER_ACTION", S.NEED_USER_ACTION, "MOCK_USER_ACTION"),
])
async def test_worker_results(chain, code, status, error):
    account, service, worker, queue, _ = chain
    submitted = await service.submit(account, code)
    assert submitted.status == S.PENDING
    await service.publish()
    delivery = await queue.dequeue()
    await worker.process(delivery)
    result = await service.get(submitted.execution_id)
    assert result.status == status
    assert result.error_code == error
    assert await queue.size() == 0
    assert result.worker_id == "test-worker"


async def test_worker_continues_after_failure(chain):
    account, service, worker, queue, _ = chain
    bad = await service.submit(account, "MOCK_FAIL")
    good = await service.submit(account, "MOCK_SUCCESS")
    await service.publish()
    await worker.process(await queue.dequeue())
    await worker.process(await queue.dequeue())
    assert (await service.get(bad.execution_id)).status == S.FAILED
    assert (await service.get(good.execution_id)).status == S.SUCCESS


async def test_disabled_after_enqueue(chain, management):
    account, service, worker, queue, _ = chain
    item = await service.submit(account, "MOCK_SUCCESS")
    await management.put_config(account, "MOCK_SUCCESS", ConfigUpdate(enabled=False))
    await service.publish()
    await worker.process(await queue.dequeue())
    assert (await service.get(item.execution_id)).status == S.SKIPPED


async def test_retry_creates_child_and_is_idempotent(chain):
    account, service, worker, queue, _ = chain
    original = await service.submit(account, "MOCK_FAIL")
    await service.publish()
    await worker.process(await queue.dequeue())
    retried = await service.retry_failed(account)
    assert retried["created"] == 1
    child = await service.get(retried["execution_ids"][0])
    assert child.parent_execution_id == original.execution_id
    assert child.trigger_type == "RETRY"
    assert child.retry_count == 1
    assert (await service.get(original.execution_id)).status == S.FAILED
    assert (await service.retry_failed(account))["created"] == 0
    await worker.process(await queue.dequeue())
    assert (await service.get(child.execution_id)).status == S.FAILED


@pytest.mark.parametrize("exclusion", ["disabled", "account_disabled", "success", "running"])
async def test_retry_exclusions(chain, management, exclusion):
    account, service, worker, queue, _ = chain
    original = await service.submit(account, "MOCK_FAIL")
    await service.publish()
    await worker.process(await queue.dequeue())
    if exclusion == "disabled":
        await management.put_config(account, "MOCK_FAIL", ConfigUpdate(enabled=False))
    elif exclusion == "account_disabled":
        await management.update_account(account, AccountUpdate(status="DISABLED"))
    else:
        current = await service.submit(account, "MOCK_FAIL")
        await service.publish()
        delivery = await queue.dequeue()
        job = TaskJob.model_validate_json(delivery.payload)
        await service.start(job, "w", "claim")
        if exclusion == "success":
            await service.finish(current.execution_id, "w", "claim", TaskResult(
                success=True, status=S.SUCCESS, message="模拟成功",
            ))
    assert (await service.retry_failed(account))["created"] == 0
    assert (await service.get(original.execution_id)).status == S.FAILED


async def test_lease_recovery_fences_old_worker(chain):
    account, service, _, queue, _ = chain
    item = await service.submit(account, "MOCK_SUCCESS")
    await service.publish()
    job = TaskJob.model_validate_json((await queue.dequeue()).payload)
    assert await service.start(job, "old-worker", "old-owner")
    assert (await service.get(item.execution_id)).status == S.RUNNING
    assert not await service.renew(item.execution_id, "other", "wrong")
    assert await service.renew(item.execution_id, "old-worker", "old-owner")
    future = utcnow() + timedelta(seconds=10)
    service.clock = lambda: future
    assert await service.recover() == 1
    assert await service.recover() == 0
    result = await service.get(item.execution_id)
    assert result.error_code == "WORKER_LEASE_EXPIRED"
    assert not await service.finish(item.execution_id, "old-worker", "old-owner", TaskResult(
        success=True, status=S.SUCCESS, message="过期结果",
    ))


async def test_duplicate_submission(chain):
    account, service, _, _, _ = chain
    await service.submit(account, "MOCK_SUCCESS")
    with pytest.raises(BusinessError) as caught:
        await service.submit(account, "MOCK_SUCCESS")
    assert caught.value.code == "DUPLICATE_EXECUTION"


def test_state_machine():
    ExecutionStateMachine.validate(S.PENDING, S.RUNNING)
    ExecutionStateMachine.validate(S.RUNNING, S.SUCCESS)
    ExecutionStateMachine.validate(S.RUNNING, S.FAILED)
    for before, after in ((S.SUCCESS, S.RUNNING), (S.FAILED, S.PENDING), (S.PENDING, S.SUCCESS)):
        with pytest.raises(BusinessError):
            ExecutionStateMachine.validate(before, after)


async def test_redis_outage_keeps_outbox(chain, monkeypatch):
    account, service, _, queue, _ = chain
    original = queue.enqueue
    async def unavailable(job):
        raise ConnectionError("redis unavailable")
    monkeypatch.setattr(queue, "enqueue", unavailable)
    item = await service.submit(account, "MOCK_SUCCESS")
    assert await service.publish() == 0
    assert (await service.get(item.execution_id)).status == S.PENDING
    monkeypatch.setattr(queue, "enqueue", original)
    assert await service.publish() == 1


async def test_bounded_auto_retry_and_dlq(chain, management):
    account, service, worker, queue, _ = chain
    tasks = TaskRegistry()
    class TransientTask(BaseTask):
        task_code = "TRANSIENT"
        retry_safe = True
        async def execute(self, context):
            raise AdapterTimeoutError()
    tasks.register(TransientTask)
    service.registry = tasks
    worker.engine.registry = tasks
    await management.create_definition(DefinitionCreate(task_code="TRANSIENT", task_name="暂时错误"))
    await management.put_config(account, "TRANSIENT", ConfigUpdate(enabled=True))
    await service.submit(account, "TRANSIENT")
    for _ in range(3):
        await service.publish()
        await worker.process(await queue.dequeue())
    records = await management.executions()
    assert len(records) == 3
    assert max(r.retry_count for r in records) == 2
    assert await queue.redis.xlen(queue.dlq) == 1
    assert await queue.size() == 0


async def test_worker_heartbeat_and_offline(chain):
    _, _, worker, _, settings = chain
    settings.worker_heartbeat_ttl = 1
    await worker.heartbeat.update(["active"])
    workers = await list_workers(worker.redis, settings.worker_key_prefix)
    assert workers[0]["active_execution"] == ["active"]
    await worker.redis.pexpire(settings.worker_key_prefix + worker.worker_id, 1)
    await asyncio.sleep(0.01)
    assert await list_workers(worker.redis, settings.worker_key_prefix) == []


async def test_graceful_shutdown_leaves_lease(chain):
    account, service, worker, _, _ = chain
    worker.engine.timeout = 10
    item = await service.submit(account, "MOCK_TIMEOUT")
    running = asyncio.create_task(worker.run())
    try:
        for _ in range(100):
            if (await service.get(item.execution_id)).status == S.RUNNING:
                break
            await asyncio.sleep(0.01)
        assert (await service.get(item.execution_id)).status == S.RUNNING
    finally:
        worker.stop.set()
        await asyncio.wait_for(running, 2)
    assert (await service.get(item.execution_id)).status == S.RUNNING
    future = utcnow() + timedelta(seconds=10)
    service.clock = lambda: future
    assert await service.recover() == 1


async def test_scheduler_dedup_after_completion(chain):
    _, service, worker, queue, _ = chain
    await service.schedule()
    await service.publish()
    for _ in range(4):
        await worker.process(await queue.dequeue())
    assert await queue.size() == 0

    async with service.uow.transaction() as repos:
        first_ids = {e.execution_id for e in await repos.executions.list(0, 100)}
    await service.schedule()
    await service.publish()
    async with service.uow.transaction() as repos:
        assert {e.execution_id for e in await repos.executions.list(0, 100)} == first_ids
    assert await queue.size() == 0


async def test_long_task_renews_lease(chain):
    account, service, worker, queue, _ = chain
    tasks = TaskRegistry()
    class SlowSuccess(BaseTask):
        task_code = "MOCK_SUCCESS"
        async def execute(self, context):
            await asyncio.sleep(0.5)
            return TaskResult(success=True, status=S.SUCCESS, message="模拟长任务")
    tasks.register(SlowSuccess)
    worker.engine = TaskEngine(None, tasks, timeout_seconds=2)
    item = await service.submit(account, "MOCK_SUCCESS")
    await service.publish()
    await worker.process(await queue.dequeue())
    result = await service.get(item.execution_id)
    assert result.status == S.SUCCESS
    assert result.heartbeat_at > result.start_time


async def test_worker_exception_isolated(chain):
    account, service, worker, queue, _ = chain
    item = await service.submit(account, "MOCK_SUCCESS")
    original = worker.engine.run
    async def broken(*args):
        raise RuntimeError("untrusted-exception")
    worker.engine.run = broken
    await service.publish()
    await worker.process(await queue.dequeue())
    assert (await service.get(item.execution_id)).status == S.RUNNING
    worker.engine.run = original
    other = await service.submit(account, "MOCK_FAIL")
    await service.publish()
    await worker.process(await queue.dequeue())
    assert (await service.get(other.execution_id)).status == S.FAILED


async def test_retry_backoff_uses_clock_without_sleep(chain, management):
    account, service, worker, queue, settings = chain
    tasks = TaskRegistry()
    class NetworkTask(BaseTask):
        task_code = "NETWORK"
        retry_safe = True
        async def execute(self, context):
            raise AdapterTimeoutError()
    tasks.register(NetworkTask)
    service.registry = worker.engine.registry = tasks
    settings.auto_retry_base_seconds = 5
    await management.create_definition(DefinitionCreate(task_code="NETWORK", task_name="mock"))
    await management.put_config(account, "NETWORK", ConfigUpdate(enabled=True))
    await service.submit(account, "NETWORK")
    await service.publish()
    await worker.process(await queue.dequeue())
    assert await service.publish() == 0
    future = utcnow() + timedelta(seconds=6)
    service.clock = lambda: future
    assert await service.publish() == 1


async def test_duplicate_message_runs_once(chain, management):
    account, service, worker, queue, _ = chain
    item = await service.submit(account, "MOCK_SUCCESS")
    await service.publish()
    delivery = await queue.dequeue()
    await queue.retry(TaskJob.model_validate_json(delivery.payload))
    await worker.process(delivery)
    await worker.process(await queue.dequeue())
    assert len(await management.executions()) == 1
    assert (await service.get(item.execution_id)).status == S.SUCCESS


async def test_two_schedulers_concurrent(chain, management):
    _, service, _, _, _ = chain
    await asyncio.gather(service.schedule(), service.schedule())
    assert len(await management.executions()) == 4


async def test_shutdown_during_dequeue_does_not_start_job(chain):
    account, service, worker, queue, _ = chain
    item = await service.submit(account, "MOCK_SUCCESS")
    await service.publish()
    original = queue.dequeue
    async def stop_then_deliver():
        delivery = await original()
        worker.stop.set()
        return delivery
    queue.dequeue = stop_then_deliver
    await worker.run()
    assert (await service.get(item.execution_id)).status == S.PENDING


async def test_retry_legacy_execution_without_business_date(chain):
    from app.services.task_runtime import TaskRuntimeService
    account, service, _, _, _ = chain
    legacy = await TaskEngine(TaskRuntimeService(service.uow)).execute(account, "MOCK_FAIL")
    assert (await service.get(legacy.execution_id)).business_date is None
    result = await service.retry_failed(account)
    assert result["created"] == 1
    child = await service.get(result["execution_ids"][0])
    assert child.parent_execution_id == legacy.execution_id
