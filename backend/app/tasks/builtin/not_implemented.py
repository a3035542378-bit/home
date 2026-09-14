from app.models.common import ExecutionStatus
from app.tasks.base import BaseTask, TaskContext, TaskResult
from app.tasks.registry import register_task


@register_task
class NotImplementedTask(BaseTask):
    task_code = "NOT_IMPLEMENTED"
    task_name = "尚未实现"

    async def execute(self, context: TaskContext) -> TaskResult:
        return TaskResult(success=False, status=ExecutionStatus.SKIPPED,
                          message="任务尚未实现", error_code="NOT_IMPLEMENTED")
