from app.models.common import ExecutionStatus
from app.tasks.base import BaseTask, TaskResult
from app.tasks.registry import register_task


@register_task
class MockSuccessTask(BaseTask):
    task_code = "MOCK_SUCCESS"
    task_name = "模拟成功（无外部调用）"
    retry_safe = True

    async def execute(self, context):
        return TaskResult(success=True, status=ExecutionStatus.SUCCESS, message="模拟任务已完成",
                          data={"mock": True})
