from typing import ClassVar

from app.tasks.plugins.qq.common import QQReadOnlyTask, RuntimeConfig, adapter, result
from app.tasks.registry import register_task


@register_task
class QQRuntimeStatusTask(QQReadOnlyTask):
    task_code = "QQ_RUNTIME_STATUS"
    task_name = "QQ 运行状态"
    config_schema = RuntimeConfig
    timeout_seconds = 10
    onebot_status_only = True
    required_capabilities: ClassVar[dict[str, set[str]]] = {"onebot": {"status"}}

    async def execute(self, context):
        onebot = adapter(context)
        context.set_stage("RUNTIME_SNAPSHOT")
        data = await context.get_service("account_runtime").snapshot(
            context.validated_config.execution_history_hours
        )
        context.set_stage("ONEBOT")
        status = await onebot.get_status()
        state = (
            "CONNECTED"
            if status.online and status.good
            else "DEGRADED"
            if status.online
            else "OFFLINE"
        )
        data["onebot_status"] = state
        return result(context, data, state)
