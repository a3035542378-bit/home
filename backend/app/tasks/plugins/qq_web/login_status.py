from typing import ClassVar

from app.tasks.plugins.qq_web.common import PageConfig, QQWebReadOnlyTask
from app.tasks.registry import register_task


@register_task
class QQWebLoginStatusTask(QQWebReadOnlyTask):
    task_code = "QQ_WEB_LOGIN_STATUS"
    task_name = "QQ Web 登录状态"
    config_schema = PageConfig
    timeout_seconds = 20
    required_capabilities: ClassVar[dict[str, set[str]]] = {"qq_web": {"site.qq.login_status"}}

    async def execute(self, context):
        return await self.read(context, "check_login_status", context.validated_config.page_key)
