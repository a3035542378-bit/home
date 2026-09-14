import asyncio

from app.tasks.base import BaseTask
from app.tasks.registry import register_task


@register_task
class MockTimeoutTask(BaseTask):
    task_code = "MOCK_TIMEOUT"
    task_name = "模拟超时（无外部调用）"

    async def execute(self, context):
        await asyncio.Event().wait()
