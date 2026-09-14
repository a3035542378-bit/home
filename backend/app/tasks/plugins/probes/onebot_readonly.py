from typing import ClassVar

from app.tasks.plugins.probes.common import OneBotProbeConfig, ProbeTask, onebot_probe, success
from app.tasks.registry import register_task


@register_task
class OneBotReadOnlyProbeTask(ProbeTask):
    task_code = "ONEBOT_READONLY_PROBE"
    task_name = "OneBot 只读诊断"
    config_schema = OneBotProbeConfig
    required_capabilities: ClassVar[dict[str, set[str]]] = {"onebot": {"status", "login_info"}}
    timeout_seconds = 10

    async def execute(self, context):
        return success(await onebot_probe(context))
