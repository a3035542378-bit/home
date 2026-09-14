import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from test_browser_unit import config
from test_qq_web_tasks import CODES

from app.adapters.browser import BrowserAdapter
from app.adapters.sites.qq.selectors import FixtureProfile
from app.adapters.sites.qq.web import QQWebSiteAdapter
from app.api.dispatch import get_dispatch
from app.api.management import get_management
from app.main import create_app
from app.queue.redis_stream import RedisTaskQueue
from app.schemas.management import AccountCreate, ConfigUpdate, DefinitionCreate
from app.services.dispatch import DispatchService
from app.services.runtime_adapters import ScopedBrowserAdapter
from app.services.unit_of_work import UnitOfWork
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks
from app.tools.browser_site import browser_site
from app.tools.qq_web_fixture import fixture_state
from app.workers.worker import Worker

pytestmark = pytest.mark.browser_integration


@pytest.mark.parametrize("code", CODES)
async def test_real_api_stream_worker_web(database, management, broker, tmp_path, code):
    load_builtin_tasks()
    redis, prefix = broker
    settings = config(
        tmp_path,
        task_lock_prefix=prefix + ":lock:",
        worker_key_prefix=prefix + ":worker:",
        admin_access_token="testing",
        maintenance_interval=0.1,
        worker_heartbeat_interval=0.1,
    )
    browser = BrowserAdapter(settings)
    await browser.start()

    class Provider:
        def health(self):
            return browser.health()

        @asynccontextmanager
        async def for_context(self, context, required):
            scoped = ScopedBrowserAdapter(browser, context)
            try:
                yield {"qq_web": QQWebSiteAdapter(scoped, fixture_profile=FixtureProfile(origin))}
            finally:
                await scoped.aclose()

    queue = RedisTaskQueue(redis, prefix, dlq=prefix + ":dlq")
    service = DispatchService(UnitOfWork(database.sessions), settings, queue)
    worker = Worker(
        queue,
        service,
        TaskEngine(None, adapter_provider=Provider()),
        redis,
        settings,
        "probe-worker",
    )
    app = create_app()
    app.state.settings = settings
    app.dependency_overrides[get_dispatch] = lambda: service
    app.dependency_overrides[get_management] = lambda: management
    loop = None
    try:
        async with browser_site() as origin:
            account = await management.create_account(
                AccountCreate(account_no="123456", platform="QQ")
            )
            await browser.manager.storage.save(account.id, fixture_state(account.id))
            await management.create_definition(DefinitionCreate(task_code=code, task_name=code))
            await management.put_config(
                account.id,
                code,
                ConfigUpdate(
                    enabled=True,
                    config_json={},
                ),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://test",
                headers={"Authorization": "Bearer testing"},
            ) as client:
                response = await client.post(
                    f"/api/tasks/{code}/execute", json={"account_id": account.id}
                )
                assert response.status_code == 202
                execution_id = response.json()["execution_id"]
                loop = asyncio.create_task(worker.run())
                async with asyncio.timeout(15):
                    while True:
                        result = (await client.get(f"/api/executions/{execution_id}")).json()
                        if result["status"] not in {"PENDING", "RUNNING"}:
                            break
                        await asyncio.sleep(0.05)
                assert result["status"] == "SUCCESS", result["error_code"]
                saved = result["result_json"]
                assert saved["evidence"]["final_url"] == origin
                assert saved["evidence"]["page_title"] == "QQ Web Fixture"
                if code == "QQ_TASK_CENTER_SUMMARY":
                    assert saved["data"]["total"] == 3
                    assert saved["data"]["items"][2]["status"] == "CLAIMABLE"
                assert saved["task_version"] == saved["plugin_version"] == "1.0.0"
                assert result["worker_id"] == "probe-worker"
                assert all(
                    word not in str(saved).lower()
                    for word in ("cookie", "token", "storage_state", "fixture-private")
                )
                assert not browser.manager.sessions
    finally:
        worker.stop.set()
        if loop:
            await asyncio.wait_for(loop, 5)
        await browser.stop()
