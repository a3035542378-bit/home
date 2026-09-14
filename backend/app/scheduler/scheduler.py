import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import configure_logging
from app.core.redis import create_redis
from app.queue.factory import make_queue
from app.services.dispatch import DispatchService
from app.services.unit_of_work import UnitOfWork
from app.tasks.registry import load_builtin_tasks

logger = logging.getLogger("app.scheduler")


class Scheduler:
    def __init__(self, service, settings):
        self.service, self.settings = service, settings
        self.scheduler = AsyncIOScheduler(timezone=settings.business_timezone)

    async def daily(self):
        try:
            await self.service.schedule()
            await self.service.publish()
        except Exception:  # noqa: BLE001 - 下一次调度仍可继续
            logger.warning("schedule_failed", extra={"event": "schedule_failed"})

    async def maintenance(self):
        try:
            await self.service.maintain()
        except Exception:  # noqa: BLE001 - 恢复和 Outbox 故障后重试
            logger.warning("recovery_failed", extra={"event": "recovery_failed"})

    def start(self):
        self.scheduler.add_job(self.maintenance, "interval", seconds=self.settings.maintenance_interval,
                               id="maintenance", max_instances=1, coalesce=True)
        if self.settings.scheduler_enabled:
            self.scheduler.add_job(self.daily, CronTrigger(
                hour=self.settings.schedule_hour, minute=self.settings.schedule_minute,
                timezone=self.settings.business_timezone,
            ), id="daily", max_instances=1, coalesce=True, misfire_grace_time=3600)
        self.scheduler.start()

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)


async def main():
    settings = Settings()
    configure_logging()
    load_builtin_tasks()
    database, redis = Database(settings), create_redis(settings)
    service = DispatchService(UnitOfWork(database.sessions), settings, make_queue(redis, settings))
    scheduler = Scheduler(service, settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await scheduler.maintenance()
        scheduler.start()
        await stop.wait()
    finally:
        scheduler.shutdown()
        await asyncio.sleep(0)
        await redis.aclose()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
