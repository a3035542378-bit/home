from sqlalchemy import update

from app.models import TaskConfig, TaskExecution
from app.models.common import ExecutionStatus


class RuntimeRepository:
    def __init__(self, session):
        self.session = session

    async def claim(self, account_id, code, execution_id, trigger_type, start_time) -> bool:
        changed = await self.session.execute(update(TaskConfig).where(
            TaskConfig.account_id == account_id, TaskConfig.task_code == code,
            TaskConfig.enabled.is_(True), TaskConfig.active_execution_id.is_(None),
        ).values(active_execution_id=execution_id))
        if changed.rowcount != 1:
            return False
        self.session.add(TaskExecution(
            execution_id=execution_id, account_id=account_id, task_code=code,
            trigger_type=trigger_type, status=ExecutionStatus.RUNNING, start_time=start_time,
        ))
        await self.session.flush()
        return True

    async def complete(self, account_id, code, execution_id, result) -> bool:
        changed = await self.session.execute(update(TaskConfig).where(
            TaskConfig.account_id == account_id, TaskConfig.task_code == code,
            TaskConfig.active_execution_id == execution_id,
        ).values(active_execution_id=None))
        if changed.rowcount != 1:
            return False
        changed = await self.session.execute(update(TaskExecution).where(
            TaskExecution.execution_id == execution_id,
            TaskExecution.status == ExecutionStatus.RUNNING,
        ).values(
            status=result.status, end_time=result.end_time, result_json=result.model_dump(mode="json"),
            error_code=result.error_code,
            error_message=result.message if not result.success else None,
        ))
        return changed.rowcount == 1
