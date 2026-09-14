from typing import ClassVar

from app.tasks.plugins.qq_web.common import EmptyConfig, QQWebReadOnlyTask
from app.tasks.registry import register_task


@register_task
class QQActivitySummaryTask(QQWebReadOnlyTask):
    task_code = "QQ_ACTIVITY_SUMMARY"
    task_name = "QQ 活动摘要"
    config_schema = EmptyConfig
    timeout_seconds = 30
    required_capabilities: ClassVar[dict[str, set[str]]] = {"qq_web": {"site.qq.activity.read"}}

    async def execute(self, context):
        return await self.read(context, "get_activity_summary")
