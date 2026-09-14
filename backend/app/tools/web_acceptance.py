"""开发环境独立验收：真实 HTTP/MySQL/Redis/Worker/Chromium + 显式本地 Fixture。"""

import asyncio
import json
import socket
from contextlib import AsyncExitStack, asynccontextmanager
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
import uvicorn
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.adapters.browser import BrowserAdapter
from app.adapters.sites.qq.selectors import FixtureProfile
from app.adapters.sites.qq.web import QQWebSiteAdapter
from app.api.dispatch import get_dispatch
from app.core.config import Settings
from app.core.database import Database
from app.core.errors import BusinessError
from app.core.logging import configure_logging
from app.core.redis import create_redis
from app.main import create_app
from app.queue.factory import make_queue
from app.services.runtime_adapters import ScopedBrowserAdapter
from app.services.unit_of_work import UnitOfWork
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks, registry
from app.tools.browser_site import browser_site
from app.tools.business_acceptance import AcceptanceDispatch
from app.tools.qq_web_fixture import fixture_state
from app.workers.worker import Worker

CODES = ("QQ_WEB_LOGIN_STATUS", "QQ_WEB_PAGE_STATUS", "QQ_TASK_CENTER_SUMMARY", "QQ_ACTIVITY_SUMMARY")


class AcceptanceProvider:
    """Fixture 只由验收入口构造，不提供 API 或环境变量开关。"""

    def __init__(self, settings, account_no, origin):
        self.browser = BrowserAdapter(settings)
        self.account_no, self.origin = account_no, origin

    def health(self):
        return self.browser.health()

    @asynccontextmanager
    async def for_context(self, context, required):
        if context.account.platform != "QQ" or context.account.account_no != self.account_no:
            raise BusinessError("FIXTURE_ACCOUNT_MISMATCH", "验收账号不匹配")
        await self.browser.manager.storage.save(context.account.id, fixture_state(context.account.id))
        scoped = ScopedBrowserAdapter(self.browser, context)
        try:
            yield {"qq_web": QQWebSiteAdapter(scoped, fixture_profile=FixtureProfile(self.origin))}
        finally:
            await scoped.aclose()


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
    resources = AsyncExitStack()
    temporary = resources.enter_context(TemporaryDirectory(prefix="qq-web-acceptance-"))
    origin = await resources.enter_async_context(browser_site())
    settings = settings.model_copy(update={
        "browser_state_dir": temporary + "/state", "browser_screenshot_dir": temporary + "/shots",
        "browser_storage_key": SecretStr(Fernet.generate_key().decode()),
    })
    database, redis = Database(settings), create_redis(settings)
    queue = make_queue(redis, settings)
    uow = UnitOfWork(database.sessions)
    account_no = str(int(uuid4().hex[:12], 16))
    provider = AcceptanceProvider(settings, account_no, origin)
    service = AcceptanceDispatch(uow, settings, queue)
    worker = Worker(
        queue,
        service,
        TaskEngine(None, adapter_provider=provider),
        redis,
        settings,
        "web-acceptance-" + uuid4().hex[:8],
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
                                "category": "QQ_WEB",
                                "executor_type": "BROWSER",
                            },
                        )
                account = (
                    await request(
                        "POST",
                        "/api/accounts",
                        json={
                            "account_no": account_no,
                            "platform": "QQ",
                            "nickname": "Chromium Fixture 临时只读验收",
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
                assert results[2]["data"]["total"] == 3
                assert results[2]["data"]["completed"] == results[2]["data"]["pending"] == 1
                assert results[3]["data"]["activity_count"] == 2
                assert not provider.browser.manager.sessions
                return {
                    "overall": "REAL_BROWSER_FIXTURE_PASS",
                    "backend": "REAL_HTTP_MYSQL_REDIS_WORKER",
                    "browser": "REAL_CHROMIUM",
                    "site": "LOCAL_FIXTURE",
                    "real_qq_web": "REAL_QQ_WEB_NOT_TESTED",
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
        await provider.browser.stop()
        await resources.aclose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
