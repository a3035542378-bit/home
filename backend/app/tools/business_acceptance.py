"""开发环境独立验收：真实 HTTP/MySQL/Redis/Worker + 显式 FakeOneBot。"""

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import uvicorn

from app.adapters.onebot.fake import FakeOneBotAdapter
from app.api.dispatch import get_dispatch
from app.core.config import Settings
from app.core.database import Database
from app.core.errors import BusinessError
from app.core.logging import configure_logging
from app.core.redis import create_redis
from app.main import create_app
from app.queue.factory import make_queue
from app.services.account_runtime import AccountRuntimeReader
from app.services.dispatch import DispatchService
from app.services.unit_of_work import UnitOfWork
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks, registry
from app.workers.worker import Worker

CODES = ("QQ_ACCOUNT_STATUS", "QQ_FRIEND_SUMMARY", "QQ_GROUP_SUMMARY", "QQ_RUNTIME_STATUS")


class AcceptanceProvider:
    """仅验收工具使用，不被生产 Worker 导入或通过环境开关启用。"""

    def __init__(self, uow, account_no):
        self.uow, self.account_no = uow, account_no

    def services_for_context(self, context):
        return {
            "account_runtime": AccountRuntimeReader(
                self.uow, context.account.id, context.execution_id
            )
        }

    @asynccontextmanager
    async def for_context(self, context, required):
        if context.account.platform != "QQ" or context.account.account_no != self.account_no:
            raise BusinessError("ONEBOT_ACCOUNT_MISMATCH", "验收账号不匹配")
        fake = FakeOneBotAdapter(user_id=int(self.account_no), friend_count=19, group_count=7)
        try:
            yield {"onebot": fake}
        finally:
            await fake.aclose()


class AcceptanceDispatch(DispatchService):
    """验收只发布自己创建账号的 Outbox，不恢复或重试其他账号。"""
    account_id = None

    async def publish(self):
        if self.account_id is None:
            return 0
        async with self.uow.transaction() as repos:
            jobs = await repos.dispatch.outbox(self.clock(), self.settings.outbox_republish_seconds)
        count = 0
        for job in jobs:
            if job.account_id != self.account_id:
                continue
            await self.queue.enqueue(job)
            async with self.uow.transaction() as repos:
                await repos.dispatch.published(job.execution_id, self.clock())
            count += 1
        return count

    async def maintain(self):
        return await self.publish()


async def run():
    base = Settings()
    if base.environment not in {"development", "test"}:
        raise BusinessError("ACCEPTANCE_ENVIRONMENT_REQUIRED", "仅允许开发或测试环境验收")
    configure_logging()
    load_builtin_tasks()
    prefix = "acceptance:" + uuid4().hex
    settings = base.model_copy(
        update={
            "task_stream_name": prefix + ":stream",
            "task_dlq_name": prefix + ":dlq",
            "task_lock_prefix": prefix + ":lock:",
            "worker_key_prefix": prefix + ":worker:",
            "maintenance_interval": 0.2,
            "worker_heartbeat_interval": 0.2,
        }
    )
    database, redis = Database(settings), create_redis(settings)
    queue = make_queue(redis, settings)
    uow = UnitOfWork(database.sessions)
    account_no = str(int(uuid4().hex[:12], 16))
    provider = AcceptanceProvider(uow, account_no)
    service = AcceptanceDispatch(uow, settings, queue)
    worker = Worker(
        queue,
        service,
        TaskEngine(None, adapter_provider=provider),
        redis,
        settings,
        "business-acceptance-" + uuid4().hex[:8],
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    application = create_app(settings)
    application.dependency_overrides[get_dispatch] = lambda: service
    server = uvicorn.Server(uvicorn.Config(application, log_config=None, access_log=False))
    api_task = asyncio.create_task(server.serve(sockets=[sock]))
    worker_task = None
    account_id = None
    results = []
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if api_task.done():
                    raise BusinessError("ACCEPTANCE_API_FAILED", "临时 API 启动失败")
                await asyncio.sleep(0.05)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=10,
            headers={"Authorization": "Bearer " + settings.admin_access_token.get_secret_value()},
        ) as client:

            async def request(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                if not response.is_success:
                    raise BusinessError(
                        "ACCEPTANCE_API_ERROR", f"验收 API 返回 HTTP {response.status_code}"
                    )
                return response

            try:
                existing = set()
                offset = 0
                while True:
                    rows = (await request("GET", f"/api/tasks?offset={offset}&limit=100")).json()
                    existing.update(row["task_code"] for row in rows)
                    if len(rows) < 100:
                        break
                    offset += 100
                for code in CODES:
                    if code not in existing:
                        await request(
                            "POST",
                            "/api/tasks",
                            json={
                                "task_code": code,
                                "task_name": registry.get(code).task_name,
                                "category": "QQ_ACCOUNT",
                                "executor_type": "ONEBOT",
                            },
                        )
                account = (
                    await request(
                        "POST",
                        "/api/accounts",
                        json={
                            "account_no": account_no,
                            "platform": "QQ",
                            "nickname": "FakeOneBot 临时业务验收",
                        },
                    )
                ).json()
                account_id = account["id"]
                service.account_id = account_id
                worker_task = asyncio.create_task(worker.run())
                for code in CODES:
                    await request(
                        "PUT",
                        f"/api/accounts/{account_id}/tasks/{code}",
                        json={"enabled": True, "config_json": {}},
                    )
                    response = await request(
                        "POST", f"/api/tasks/{code}/execute", json={"account_id": account_id}
                    )
                    assert response.status_code == 202
                    execution = response.json()
                    async with asyncio.timeout(30):
                        while execution["status"] in {"PENDING", "RUNNING"}:
                            await asyncio.sleep(0.1)
                            execution = (
                                await request("GET", f"/api/executions/{execution['execution_id']}")
                            ).json()
                    assert execution["status"] == "SUCCESS", execution["error_code"]
                    saved = execution["result_json"]
                    assert not any(
                        value in json.dumps(saved)
                        for value in (
                            "friend-private",
                            "group-private",
                            "remark-private",
                            account_no,
                        )
                    )
                    assert not any(
                        key in json.dumps(saved).lower()
                        for key in ("cookie", "token", "authorization", "storage_state")
                    )
                    results.append(
                        {
                            "task_code": code,
                            "execution_id": execution["execution_id"],
                            "status": execution["status"],
                            "data": saved["data"],
                        }
                    )
                assert (
                    results[1]["data"]["friend_count"] == 19
                    and results[2]["data"]["group_count"] == 7
                )
                return {
                    "overall": "PASS",
                    "backend": "REAL_HTTP_MYSQL_REDIS_WORKER",
                    "onebot": "FAKE",
                    "real_onebot": "REAL_ONEBOT_BUSINESS_NOT_TESTED",
                    "executions": results,
                }
            finally:
                worker.stop.set()
                if worker_task:
                    await asyncio.wait_for(worker_task, 25)
                if account_id:
                    await request(
                        "PATCH", f"/api/accounts/{account_id}/tasks", json={"enabled": False}
                    )
                    await request("DELETE", f"/api/accounts/{account_id}")
    finally:
        server.should_exit = True
        await asyncio.wait_for(api_task, 15)
        sock.close()
        keys = [key async for key in redis.scan_iter(match=prefix + "*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
        await database.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
