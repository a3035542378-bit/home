from app.models.common import ExecutionStatus
from app.tasks.base import BaseTask, TaskResult
from app.tasks.registry import register_task


@register_task
class MockNeedUserActionTask(BaseTask):
    task_code = "MOCK_NEED_USER_ACTION"
    task_name = "模拟人工处理（无外部调用）"

    async def execute(self, context):
        return TaskResult(success=False, status=ExecutionStatus.NEED_USER_ACTION,
                          message="模拟需要本人处理", error_code="MOCK_USER_ACTION",
                          data={"mock": True})
