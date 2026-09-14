from datetime import datetime
from typing import Protocol

from app.core.errors import BusinessError
from app.models.common import TriggerType
from app.services.management import require_account
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import AccountContext, TaskContext, TaskResult


class TaskStore(Protocol):
    async def begin(
        self, account_id: int, task_code: str, execution_id: str,
        trigger_type: TriggerType, start_time: datetime,
    ) -> TaskContext: ...

    async def finish(
        self, account_id: int, task_code: str, execution_id: str, result: TaskResult,
    ) -> None: ...


class TaskRuntimeService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def begin(self, account_id, task_code, execution_id, trigger_type, start_time):
        async with self.uow.transaction() as repos:
            account = await require_account(repos, account_id)
            if account.status != "ACTIVE":
                raise BusinessError("ACCOUNT_DISABLED", "账号已停用")
            definition = await repos.tasks.definition(task_code)
            if definition is None:
                raise BusinessError("TASK_NOT_FOUND", "任务定义不存在", 404)
            config = await repos.tasks.config(account_id, task_code)
            if definition.status != "ACTIVE" or config is None or not config.enabled:
                raise BusinessError("TASK_DISABLED", "任务未启用")
            if not await repos.runtime.claim(
                account_id, task_code, execution_id, trigger_type, start_time,
            ):
                raise BusinessError("DUPLICATE_EXECUTION", "任务正在执行，拒绝重复执行", 409)
            return TaskContext(
                account=AccountContext(account.id, account.account_no, account.platform, account.nickname, account.node_id),
                execution_id=execution_id, config=dict(config.config_json),
            )

    async def finish(self, account_id, task_code, execution_id, result):
        async with self.uow.transaction() as repos:
            if not await repos.runtime.complete(account_id, task_code, execution_id, result):
                raise BusinessError("EXECUTION_OWNERSHIP_LOST", "执行记录所有权已改变", 409)
