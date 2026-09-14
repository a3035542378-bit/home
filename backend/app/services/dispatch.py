import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import BusinessError
from app.models.common import ExecutionStatus as S
from app.models.common import TriggerType, utcnow
from app.schemas.management import ExecutionRead
from app.services.execution_state import ExecutionStateMachine
from app.services.management import require_account
from app.tasks.base import AccountContext, TaskContext, TaskResult
from app.tasks.registry import registry

logger = logging.getLogger("app.dispatch")
RETRYABLE = {"SITE_NAVIGATION_FAILED", "ADAPTER_TIMEOUT", "ADAPTER_CONNECTION_ERROR", "ONEBOT_TIMEOUT", "ONEBOT_CONNECTION_ERROR"}


class DispatchService:
    def __init__(self, uow, settings, queue=None, clock=utcnow, task_registry=registry):
        self.uow, self.settings, self.queue = uow, settings, queue
        self.clock, self.registry = clock, task_registry

    def today(self):
        return self.clock().astimezone(ZoneInfo(self.settings.business_timezone)).date()

    def bounds(self, day):
        zone = ZoneInfo(self.settings.business_timezone)
        return (datetime.combine(day, time.min, zone),
                datetime.combine(day + timedelta(days=1), time.min, zone))

    async def submit(self, account_id, code, trigger=TriggerType.MANUAL, *, parent_id=None,
                     day=None, schedule_key=None, delay=0):
        self.registry.get(code)
        day = day or self.today()
        async with self.uow.transaction() as repos:
            account = await require_account(repos, account_id)
            if schedule_key:
                existing = await repos.dispatch.schedule_execution(schedule_key)
                if existing:
                    return ExecutionRead.model_validate(existing)
            definition = await repos.tasks.definition(code)
            config = await repos.tasks.config(account_id, code)
            if account.status != "ACTIVE":
                raise BusinessError("ACCOUNT_DISABLED", "账号已停用", 409)
            if definition is None or definition.status != "ACTIVE":
                raise BusinessError("TASK_NOT_FOUND", "任务定义不可用", 404)
            if config is None or not config.enabled:
                raise BusinessError("TASK_DISABLED", "任务未启用", 409)
            parent = None
            if parent_id:
                parent = await repos.executions.get(parent_id)
                if parent is None or parent.status != S.FAILED or parent.account_id != account_id or parent.task_code != code:
                    raise BusinessError("INVALID_RETRY", "仅允许补执行失败记录", 409)
                if await repos.dispatch.child(parent_id) or await repos.dispatch.has_success(account_id, code, day, self.bounds(day)):
                    raise BusinessError("RETRY_EXCLUDED", "已有后续执行或当日成功记录", 409)
                latest = await repos.dispatch.latest(account_id, code, day, self.bounds(day))
                if latest is not None and latest.execution_id != parent_id:
                    raise BusinessError("RETRY_EXCLUDED", "仅允许补执行最新失败记录", 409)
            execution = await repos.dispatch.create(
                account_id, code, trigger, day, self.clock(), parent, schedule_key, delay,
            )
            if execution is None:
                raise BusinessError("DUPLICATE_EXECUTION", "该任务已有待执行或运行记录", 409)
            return ExecutionRead.model_validate(execution)

    async def publish(self):
        if self.queue is None:
            return 0
        async with self.uow.transaction() as repos:
            jobs = await repos.dispatch.outbox(self.clock(), self.settings.outbox_republish_seconds)
        count = 0
        for job in jobs:
            try:
                await self.queue.enqueue(job)
                async with self.uow.transaction() as repos:
                    await repos.dispatch.published(job.execution_id, self.clock())
                count += 1
            except Exception:  # noqa: BLE001 - Outbox 保留待投递记录，下次维护补投
                logger.warning("outbox_unavailable", extra={"event": "outbox_unavailable"})
                break
        return count

    async def get(self, execution_id):
        async with self.uow.transaction() as repos:
            record = await repos.executions.get(execution_id)
            return ExecutionRead.model_validate(record) if record else None

    async def start(self, job, worker_id, lease_token):
        async with self.uow.transaction() as repos:
            account = await repos.accounts.get(job.account_id)
            execution = await repos.executions.get(job.execution_id)
            if execution is None or (execution.account_id, execution.task_code,
                                     execution.trigger_type, execution.retry_count) != (
                    job.account_id, job.task_code, job.trigger_type, job.retry_count):
                raise BusinessError("INVALID_JOB_REFERENCE", "消息与执行记录不匹配")
            if execution.status != S.PENDING:
                return None
            config = await repos.tasks.config(job.account_id, job.task_code)
            definition = await repos.tasks.definition(job.task_code)
            if not account or account.status != "ACTIVE" or not config or not config.enabled or not definition or definition.status != "ACTIVE":
                result = TaskResult(success=False, status=S.SKIPPED, message="账号或任务已停用",
                                    error_code="TASK_DISABLED", execution_id=job.execution_id)
                ExecutionStateMachine.validate(S.PENDING, result.status)
                await repos.dispatch.finish(execution, result, self.clock())
                return None
            if config.active_execution_id != job.execution_id:
                raise BusinessError("EXECUTION_OWNERSHIP_LOST", "任务占用与执行记录不匹配")
            ExecutionStateMachine.validate(execution.status, S.RUNNING)
            if not await repos.dispatch.start(job.execution_id, worker_id, lease_token,
                                              self.clock(), self.settings.execution_lease_seconds):
                return None
            return TaskContext(AccountContext(account.id, account.account_no, account.platform,
                                              account.nickname, account.node_id), job.execution_id, dict(config.config_json))

    async def renew(self, execution_id, worker_id, lease_token):
        async with self.uow.transaction() as repos:
            return await repos.dispatch.renew(execution_id, worker_id, lease_token,
                                               self.clock(), self.settings.execution_lease_seconds)

    async def finish(self, execution_id, worker_id, lease_token, result):
        async with self.uow.transaction() as repos:
            execution = await repos.executions.get(execution_id)
            if execution is None or execution.status != S.RUNNING:
                return False
            ExecutionStateMachine.validate(execution.status, result.status)
            return await repos.dispatch.finish(execution, result, self.clock(),
                                                worker_id=worker_id, lease_token=lease_token)

    async def recover(self):
        now = self.clock()
        async with self.uow.transaction() as repos:
            expired = await repos.dispatch.expired(now, now - timedelta(seconds=self.settings.execution_lease_seconds))
            count = 0
            for execution in expired:
                ExecutionStateMachine.validate(execution.status, S.FAILED)
                result = TaskResult(success=False, status=S.FAILED,
                                    message="Worker lease expired before task completed.",
                                    error_code="WORKER_LEASE_EXPIRED", execution_id=execution.execution_id,
                                    start_time=execution.start_time or now, end_time=now)
                count += await repos.dispatch.finish(execution, result, now, recovery=True)
            return count

    async def retry_failed(self, account_id=None, day=None):
        day = day or self.today()
        failures, cursor = [], None
        while True:
            async with self.uow.transaction() as repos:
                rows = await repos.dispatch.failures(day, account_id, before_id=cursor, bounds=self.bounds(day))
                if not rows:
                    break
                cursor = rows[-1].id
                failures.extend(ExecutionRead.model_validate(e) for e in rows)
        created, skipped = [], 0
        for failure in failures:
            try:
                child = await self.submit(failure.account_id, failure.task_code, TriggerType.RETRY,
                                          parent_id=failure.execution_id, day=day)
                created.append(child.execution_id)
            except BusinessError as exc:
                if exc.http_status == 503:
                    raise
                skipped += 1
        await self.publish()
        return {"execution_ids": created, "created": len(created), "skipped": skipped}

    async def auto_retry(self, execution_id):
        record = await self.get(execution_id)
        if not record or record.status != S.FAILED or record.error_code not in RETRYABLE:
            return "final"
        try:
            task = self.registry.get(record.task_code)
        except BusinessError:
            return "unrecoverable"
        if task.retry_policy is not None:
            if not (task.idempotent and task.read_only and record.error_code in task.retry_policy
                    and record.result_json and record.result_json.get("retryable") is True):
                return "final"
        elif not task.retry_safe:
            return "final"
        if record.retry_count >= self.settings.max_auto_retry:
            return "exhausted"
        try:
            await self.submit(record.account_id, record.task_code, TriggerType.RETRY,
                              parent_id=record.execution_id,
                              day=record.business_date or record.created_at.astimezone(ZoneInfo(self.settings.business_timezone)).date(),
                              delay=self.settings.auto_retry_base_seconds * (3 ** record.retry_count))
        except BusinessError as exc:
            if exc.http_status == 503:
                raise
        return "retry"

    async def mark_dlq(self, execution_id):
        async with self.uow.transaction() as repos:
            await repos.dispatch.mark_dlq(execution_id, self.clock())

    async def schedule(self, day=None):
        day = day or self.today()
        cursor, count = 0, 0
        while True:
            async with self.uow.transaction() as repos:
                configs = await repos.dispatch.enabled(cursor)
            if not configs:
                return count
            for config_id, account_id, code in configs:
                cursor = config_id
                try:
                    task = self.registry.get(code)
                    if not task.scheduled or task.diagnostic_only:
                        continue
                    await self.submit(account_id, code, TriggerType.SCHEDULE, day=day,
                                      schedule_key=f"{account_id}:{code}:{day}:daily")
                    count += 1
                except BusinessError as exc:
                    if exc.http_status == 503:
                        raise

    async def maintain(self):
        await self.recover()
        # ACK 之前崩溃也不会丢掉应创建的自动重试；叶节点唯一约束保证幂等。
        async with self.uow.transaction() as repos:
            failures = [e.execution_id for e in await repos.dispatch.failures(retryable_codes=RETRYABLE)]
        for execution_id in failures:
            await self.auto_retry(execution_id)
        await self.publish()
