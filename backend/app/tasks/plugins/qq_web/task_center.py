from typing import ClassVar

from app.tasks.plugins.qq_web.common import EmptyConfig, QQWebReadOnlyTask
from app.tasks.registry import register_task


@register_task
class QQTaskCenterSummaryTask(QQWebReadOnlyTask):
    task_code = "QQ_TASK_CENTER_SUMMARY"
    task_name = "QQ 任务中心摘要"
    config_schema = EmptyConfig
    timeout_seconds = 30
    required_capabilities: ClassVar[dict[str, set[str]]] = {"qq_web": {"site.qq.task_center.read"}}

    async def execute(self, context):
        return await self.read(context, "get_task_center_summary")
