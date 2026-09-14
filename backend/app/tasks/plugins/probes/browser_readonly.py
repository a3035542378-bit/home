from typing import ClassVar

from app.tasks.plugins.probes.common import BrowserProbeConfig, ProbeTask, browser_probe, success
from app.tasks.registry import register_task


@register_task
class BrowserReadOnlyProbeTask(ProbeTask):
    task_code = "BROWSER_READONLY_PROBE"
    task_name = "浏览器只读诊断"
    config_schema = BrowserProbeConfig
    required_capabilities: ClassVar[dict[str, set[str]]] = {
        "browser": {"browser.navigation", "browser.text"}
    }
    timeout_seconds = 30

    async def execute(self, context):
        data, evidence = await browser_probe(context)
        return success(data, evidence)
