from app.models.common import ExecutionStatus
from app.tasks.base import BaseTask, TaskResult
from app.tasks.registry import register_task


@register_task
class MockFailTask(BaseTask):
    task_code = "MOCK_FAIL"
    task_name = "模拟失败（无外部调用）"

    async def execute(self, context):
        return TaskResult(success=False, status=ExecutionStatus.FAILED, message="预期的模拟失败",
                          error_code="MOCK_FAILURE", data={"mock": True})
