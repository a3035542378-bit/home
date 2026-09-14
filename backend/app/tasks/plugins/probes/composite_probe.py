from typing import ClassVar

from app.tasks.plugins.probes.common import (
    BrowserProbeConfig,
    ProbeTask,
    browser_probe,
    onebot_probe,
    success,
)
from app.tasks.registry import register_task


@register_task
class CompositeProbeTask(ProbeTask):
    task_code = "COMPOSITE_PROBE"
    task_name = "OneBot 与浏览器组合诊断"
    config_schema = BrowserProbeConfig
    required_capabilities: ClassVar[dict[str, set[str]]] = {
        "onebot": {"status", "login_info"},
        "browser": {"browser.navigation", "browser.text"},
    }
    timeout_seconds = 45

    async def execute(self, context):
        onebot = await onebot_probe(context)
        browser, evidence = await browser_probe(context)
        return success({"onebot": onebot, "browser": browser}, evidence)
