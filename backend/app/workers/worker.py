import asyncio
import logging
import os
import signal
import socket
from uuid import uuid4

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import BusinessError
from app.core.logging import configure_logging
from app.core.redis import create_redis
from app.models.common import ExecutionStatus as S
from app.queue.base import TaskJob
from app.queue.factory import make_queue
from app.queue.lock import TaskLock
from app.services.dispatch import DispatchService
from app.services.unit_of_work import UnitOfWork
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks
from app.workers.heartbeat import WorkerHeartbeat

logger = logging.getLogger("app.worker")
TERMINAL = {S.SUCCESS, S.FAILED, S.SKIPPED, S.NEED_USER_ACTION}


class Worker:
    def __init__(self, queue, service, engine, redis, settings, worker_id=None):
        self.queue, self.service, self.engine = queue, service, engine
        self.redis, self.settings = redis, settings
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
        self.queue.consumer = self.worker_id
        self.heartbeat = WorkerHeartbeat(redis, self.worker_id, settings, browser_health=
            getattr(engine.adapter_provider, "health", None))
        self.active = set()
        self.stop = asyncio.Event()
        self.tasks = set()

    def log(self, status, job=None):
        fields = {"event": "worker_event", "status": status, "worker_id": self.worker_id}
        if job:
            fields.update(job_id=job.job_id, execution_id=job.execution_id, account_id=job.account_id,
                          task_code=job.task_code, retry_count=job.retry_count)
        logger.info("worker_event", extra=fields)

    async def settle(self, delivery, job):
        state = await self.service.get(job.execution_id)
        if state is None:
            await self.queue.dead_letter(delivery, "EXECUTION_NOT_FOUND", self.worker_id)
        elif state.status in TERMINAL:
            decision = await self.service.auto_retry(job.execution_id)
            if decision in {"exhausted", "unrecoverable"}:
                code = "RETRY_EXHAUSTED" if decision == "exhausted" else "PLUGIN_UNAVAILABLE"
                await self.queue.dead_letter(delivery, code, self.worker_id)
                await self.service.mark_dlq(job.execution_id)
            else:
                await self.queue.ack(delivery)

    async def process(self, delivery):
        try:
            job = TaskJob.model_validate_json(delivery.payload)
        except ValueError:
            self.log("INVALID_JOB")
            await self.queue.dead_letter(delivery, "INVALID_JOB", self.worker_id)
            return
        lock = TaskLock(self.redis, f"{self.settings.task_lock_prefix}{job.account_id}:{job.task_code}",
                        self.settings.task_lock_ttl)
        renewal = None
        execution_task = None
        acquired = False
        try:
            state = await self.service.get(job.execution_id)
            if state is not None and (state.account_id, state.task_code, state.trigger_type,
                                      state.retry_count) != (job.account_id, job.task_code,
                                                           job.trigger_type, job.retry_count):
                await self.queue.dead_letter(delivery, "INVALID_JOB_REFERENCE", self.worker_id)
                return
            if state is None or state.status in TERMINAL:
                await self.settle(delivery, job)
                return
            acquired = await lock.acquire()
            if not acquired:
                return
            context = await self.service.start(job, self.worker_id, lock.token)
            if context is None:
                await self.settle(delivery, job)
                return
            self.active.add(job.execution_id)
            self.log("RUNNING", job)
            execution_task = asyncio.create_task(self.engine.run(job.task_code, context))
            renewal = asyncio.create_task(self.renew(job, lock))
            done, _ = await asyncio.wait({execution_task, renewal}, return_when=asyncio.FIRST_COMPLETED)
            if renewal in done:
                self.log("LEASE_LOST", job)
                execution_task.cancel()
                await asyncio.gather(execution_task, return_exceptions=True)
                return
            result = execution_task.result()
            # 保存结果前再次验证锁，DB 租约 token 还会进行第二层 fencing。
            if not await lock.renew():
                self.log("LOCK_LOST", job)
                return
            if await self.service.finish(job.execution_id, self.worker_id, lock.token, result):
                self.log(result.status, job)
                await self.settle(delivery, job)
        except BusinessError as exc:
            self.log(exc.code, job)
            if exc.code == "INVALID_JOB_REFERENCE":
                await self.queue.dead_letter(delivery, exc.code, self.worker_id)
        except asyncio.CancelledError:
            self.log("STOPPED_WITH_LEASE", job)
            raise
        except Exception:  # noqa: BLE001 - 保留 PEL 与租约，由后续恢复处理
            self.log("WORKER_TASK_ERROR", job)
        finally:
            for pending in (renewal, execution_task):
                if pending is not None and not pending.done():
                    pending.cancel()
            await asyncio.gather(*(p for p in (renewal, execution_task) if p), return_exceptions=True)
            self.active.discard(job.execution_id)
            if acquired:
                try:
                    await lock.release()
                except Exception:  # noqa: BLE001 - TTL 最终释放，不能删除其他持有者
                    self.log("LOCK_RELEASE_ERROR", job)

    async def renew(self, job, lock):
        interval = min(self.settings.execution_lease_seconds, self.settings.task_lock_ttl) / 3
        try:
            while True:
                await asyncio.sleep(interval)
                if not await lock.renew() or not await self.service.renew(job.execution_id, self.worker_id, lock.token):
                    return
        except Exception:  # noqa: BLE001 - 续租失败立即停止接受本次执行结果
            self.log("RENEW_ERROR", job)

    async def background(self):
        while not self.stop.is_set():
            try:
                await self.heartbeat.update(self.active)
                await self.service.maintain()
            except Exception:  # noqa: BLE001 - 外部依赖恢复后继续
                self.log("MAINTENANCE_ERROR")
            try:
                await asyncio.wait_for(self.stop.wait(), min(
                    self.settings.worker_heartbeat_interval, self.settings.maintenance_interval,
                ))
            except TimeoutError:
                continue

    async def run(self):
        background = asyncio.create_task(self.background())
        self.log("STARTED")
        try:
            while not self.stop.is_set():
                self.tasks = {t for t in self.tasks if not t.done()}
                if len(self.tasks) >= self.settings.worker_concurrency:
                    await asyncio.wait(self.tasks, timeout=0.2, return_when=asyncio.FIRST_COMPLETED)
                    continue
                try:
                    delivery = await self.queue.dequeue()
                    if delivery is not None and not self.stop.is_set():
                        self.tasks.add(asyncio.create_task(self.safe_process(delivery)))
                except Exception:  # noqa: BLE001 - Redis 恢复后继续消费
                    self.log("QUEUE_UNAVAILABLE")
                    await asyncio.sleep(0.2)
        finally:
            if self.tasks:
                _, pending = await asyncio.wait(self.tasks, timeout=self.settings.worker_shutdown_timeout)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*self.tasks, return_exceptions=True)
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)
            try:
                await self.heartbeat.update([], "OFFLINE")
            except Exception:  # noqa: BLE001 - 心跳 TTL 会将 Worker 标记离线
                self.log("HEARTBEAT_UNAVAILABLE")


    async def safe_process(self, delivery):
        try:
            await self.process(delivery)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 包含畸形消息 DLQ 写入失败，保留 Pending
            self.log("DELIVERY_ERROR")


from app.services.runtime_adapters import RuntimeAdapters


async def main():
    settings = Settings()
    configure_logging()
    load_builtin_tasks()
    database, redis = Database(settings), create_redis(settings)
    queue = make_queue(redis, settings)
    service = DispatchService(UnitOfWork(database.sessions), settings, queue)
    adapters = RuntimeAdapters(UnitOfWork(database.sessions), settings)
    worker = Worker(queue, service, TaskEngine(None, timeout_seconds=settings.task_timeout_seconds, adapter_provider=adapters), redis, settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop.set)
    try:
        await adapters.start()
        await worker.run()
    finally:
        try:
            await adapters.aclose()
        finally:
            try:
                await redis.aclose()
            finally:
                await database.close()


if __name__ == "__main__":
    asyncio.run(main())
