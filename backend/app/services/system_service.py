import asyncio
import logging
from typing import Protocol

from app.schemas.system import HealthResponse

logger = logging.getLogger("app.health")


class Probe(Protocol):
    async def ping(self) -> object: ...


class SystemService:
    def __init__(self, database: Probe, redis: Probe, timeout: float, onebot=None, worker_status=None):
        self.probes = {"database": database, "redis": redis}
        self.timeout = timeout
        self.onebot = onebot
        self.worker_status = worker_status

    async def health(self) -> HealthResponse:
        async def check(name, probe):
            try:
                async with asyncio.timeout(self.timeout):
                    await probe.ping()
                return name, "ok"
            except Exception:  # noqa: BLE001 - probe boundary; never expose driver exceptions
                logger.warning("dependency_unavailable", extra={
                    "event": "dependency_unavailable", "dependency": name,
                })
                return name, "unavailable"

        results = dict(await asyncio.gather(*(
            check(name, probe) for name, probe in self.probes.items()
        )))
        onebot = {}
        if self.onebot:
            try:
                async with asyncio.timeout(self.timeout):
                    onebot = await self.onebot.summary()
            except Exception:  # noqa: BLE001 - 可选节点故障不能影响核心健康
                logger.warning("onebot_summary_unavailable", extra={"event": "onebot_summary_unavailable"})
                onebot = {"state": "UNKNOWN"}
        browser = "DEGRADED"
        if self.worker_status:
            try:
                async with asyncio.timeout(self.timeout):
                    workers = await self.worker_status.list()
                    states = [w.get("browser", "DOWN") for w in workers if w.get("status") == "ONLINE"]
                    browser = "UP" if states and all(s == "UP" for s in states) else "DOWN" if states and all(s == "DOWN" for s in states) else "DEGRADED"
            except Exception:  # noqa: BLE001 - 浏览器健康是可选依赖
                logger.warning("browser_health_unavailable", extra={"event": "browser_health_unavailable"})
        return HealthResponse(
            status="ok" if all(v == "ok" for v in results.values()) else "degraded",
            dependencies=results, onebot=onebot, browser=browser,
        )
