from typing import ClassVar

from app.tasks.plugins.qq_web.common import PageConfig, QQWebReadOnlyTask
from app.tasks.registry import register_task


@register_task
class QQWebPageStatusTask(QQWebReadOnlyTask):
    task_code = "QQ_WEB_PAGE_STATUS"
    task_name = "QQ Web 页面状态"
    config_schema = PageConfig
    timeout_seconds = 20
    required_capabilities: ClassVar[dict[str, set[str]]] = {"qq_web": {"site.qq.page_status"}}

    async def execute(self, context):
        return await self.read(context, "get_page_status", context.validated_config.page_key)
