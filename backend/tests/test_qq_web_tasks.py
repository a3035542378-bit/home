from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from test_browser_unit import config

from app.adapters.browser.exceptions import BrowserNavigationTimeout, BrowserPageCrashError
from app.adapters.sites.qq.exceptions import SiteNavigationFailed, SiteParseFailed
from app.adapters.sites.qq.fake import FakeQQSiteAdapter
from app.adapters.sites.qq.schemas import LoginState
from app.adapters.sites.qq.selectors import FixtureProfile
from app.adapters.sites.qq.web import QQWebSiteAdapter
from app.tasks.base import AccountContext, TaskContext
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks, registry

CODES = ("QQ_WEB_LOGIN_STATUS", "QQ_WEB_PAGE_STATUS", "QQ_TASK_CENTER_SUMMARY", "QQ_ACTIVITY_SUMMARY")


async def run(code, site=None, values=None):
    load_builtin_tasks()
    context = TaskContext(AccountContext(1, "123456", "QQ", "", None), "web-test", values or {})
    return await TaskEngine(None, adapters={"qq_web": site or FakeQQSiteAdapter()}).run(code, context)


@pytest.mark.parametrize("code", CODES)
async def test_success_metadata_and_data_minimization(code):
    result = await run(code)
    assert result.success and not result.retryable
    assert set(result.evidence) == {"page_key", "final_url", "page_title", "parsed_item_count", "checked_at"}
    assert not any(value in result.model_dump_json().lower() for value in ("cookie", "token", "<html", "storage"))
    task = registry.get(code)
    assert task.read_only and task.idempotent and not task.scheduled and not task.diagnostic_only
    assert task.category == "QQ_WEB" and task.side_effect_level == "NONE" and task.risk_level == "SAFE_READONLY"
    assert task.timeout_seconds == (20 if code.startswith("QQ_WEB") else 30)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("mode", ["need_login", "need_verification", "parse_error"])
async def test_fake_modes(code, mode):
    result = await run(code, FakeQQSiteAdapter(mode))
    assert not result.retryable
    assert result.status == ("FAILED" if mode == "parse_error" else "NEED_USER_ACTION")


@pytest.mark.parametrize("state", list(LoginState)[1:])
async def test_all_login_challenges(state):
    from app.adapters.sites.qq.exceptions import SiteNeedUserAction
    fake = FakeQQSiteAdapter()
    fake.check_login_status = AsyncMock(side_effect=SiteNeedUserAction(state))
    result = await run(CODES[0], fake)
    assert result.status == "NEED_USER_ACTION" and result.data["login_state"] == state
    assert result.data["authenticated"] is False


@pytest.mark.parametrize("url", ["https://example.com", "file:///etc/passwd", "http://localhost",
    "http://127.0.0.1", "http://169.254.169.254", "http://10.0.0.1", "http://192.168.1.1", "http://[::1]"])
@pytest.mark.parametrize("key", ["url", "page_key"])
async def test_arbitrary_configuration_rejected(url, key):
    fake = FakeQQSiteAdapter()
    result = await run(CODES[1], fake, {key: url})
    assert result.error_code == "TASK_CONFIG_INVALID" and not fake.calls


@pytest.mark.parametrize("key", ["PROFILE", "TASK_CENTER", "ACTIVITY_CENTER"])
async def test_page_key(key):
    assert (await run(CODES[1], values={"page_key": key})).evidence["page_key"] == key


@pytest.mark.parametrize("code", CODES)
async def test_unconfigured_and_capability(code):
    browser = Mock()
    result = await run(code, QQWebSiteAdapter(browser))
    assert result.error_code == "SITE_NOT_CONFIGURED" and not browser.mock_calls
    fake = FakeQQSiteAdapter()
    fake.capabilities = dict
    assert (await run(code, fake)).error_code == "CAPABILITY_UNSUPPORTED"
    assert not fake.calls


@pytest.mark.parametrize("error,retry", [(SiteNavigationFailed, True), (SiteParseFailed, False)])
async def test_retry_policy(error, retry):
    fake = FakeQQSiteAdapter()
    fake.get_task_center_summary = AsyncMock(side_effect=error())
    result = await run(CODES[2], fake)
    assert result.error_code == error.code and result.retryable is retry


@pytest.mark.parametrize("error", [BrowserNavigationTimeout, BrowserPageCrashError])
async def test_browser_transient_translation(error):
    browser = Mock(start=AsyncMock(side_effect=error()))
    site = QQWebSiteAdapter(browser, fixture_profile=FixtureProfile("http://127.0.0.1:12345"))
    result = await run(CODES[0], site)
    assert result.error_code == "SITE_NAVIGATION_FAILED" and result.retryable


@pytest.mark.parametrize("url", ["file:///x", "http://localhost", "https://127.0.0.1", "https://169.254.169.254",
    "https://10.0.0.1", "https://[::1]", "https://foo.local", "https://example.com/?token=secret"])
def test_environment_url_validation(tmp_path, url):
    with pytest.raises(ValidationError):
        config(tmp_path, qq_web_base_url=url)


def test_empty_environment_and_fixture_policy(tmp_path):
    assert config(tmp_path, qq_web_base_url="").qq_web_base_url is None
    profile = FixtureProfile("http://127.0.0.1:1234")
    for value in ["file:///x", "http://localhost:1234/qq/task-center", "http://127.0.0.1:1235/qq/task-center",
                  "http://127.0.0.1:1234/qq/task-center?url=x", "http://169.254.169.254"]:
        assert not profile.permits(value)
    assert not profile.permits(profile.url("TASK_CENTER"), "POST")


@pytest.mark.parametrize("mode,child_count,status", [("navigation", 1, "FAILED"),
    ("parse_error", 0, "FAILED"), ("need_login", 0, "NEED_USER_ACTION")])
async def test_worker_retry_and_schedule(database, management, broker, mode, child_count, status):
    from app.core.config import Settings
    from app.queue.redis_stream import RedisTaskQueue
    from app.schemas.management import AccountCreate, ConfigUpdate, DefinitionCreate
    from app.services.dispatch import DispatchService
    from app.services.unit_of_work import UnitOfWork
    from app.workers.worker import Worker

    load_builtin_tasks()
    redis, prefix = broker
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:",
                        task_lock_prefix=prefix + ":lock:", auto_retry_base_seconds=0)
    queue = RedisTaskQueue(redis, prefix, dlq=prefix + ":dlq")
    service = DispatchService(UnitOfWork(database.sessions), settings, queue)
    account = await management.create_account(AccountCreate(account_no="123456", platform="QQ"))
    for code in CODES:
        await management.create_definition(DefinitionCreate(task_code=code, task_name=code))
        await management.put_config(account.id, code, ConfigUpdate(enabled=True))
    assert await service.schedule() == 0
    fake = FakeQQSiteAdapter(mode)
    if mode == "navigation":
        fake.get_task_center_summary = AsyncMock(side_effect=SiteNavigationFailed())
    worker = Worker(queue, service, TaskEngine(None, adapters={"qq_web": fake}), redis, settings)
    item = await service.submit(account.id, CODES[2])
    await service.publish()
    await worker.process(await queue.dequeue())
    rows = await management.executions()
    assert len(rows) == 1 + child_count
    assert (await service.get(item.execution_id)).status == status
    if child_count:
        assert rows[0].parent_execution_id == item.execution_id
        assert rows[0].status == "PENDING" and rows[0].trigger_type == "RETRY"


async def test_runtime_provider_fail_closed(database, tmp_path):
    from app.services.runtime_adapters import RuntimeAdapters
    from app.services.unit_of_work import UnitOfWork
    provider = RuntimeAdapters(UnitOfWork(database.sessions), config(tmp_path, qq_web_base_url="https://example.com"))
    context = TaskContext(AccountContext(1, "123456", "QQ", "", None), "production-path")
    try:
        result = await TaskEngine(None, adapter_provider=provider).run(CODES[0], context)
        assert result.error_code == "SITE_NOT_CONFIGURED" and not result.retryable
        assert not provider.browser.manager.is_connected
    finally:
        await provider.aclose()


def test_site_and_task_readonly_boundary():
    import ast
    from pathlib import Path
    folder = Path(__file__).parents[1] / "app/tasks/plugins/qq_web"
    for path in folder.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "browser" not in (node.module or "") and "selectors" not in (node.module or "")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"goto", "click", "fill", "evaluate", "new_page"}
    tree = ast.parse((folder.parents[2] / "adapters/sites/qq/web.py").read_text())
    assert not {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)} & {"click", "fill", "evaluate", "screenshot", "save_state"}


async def test_task_timeout_not_retried(monkeypatch):
    import asyncio
    load_builtin_tasks()
    fake = FakeQQSiteAdapter()
    async def slow(*args):
        await asyncio.sleep(1)
    fake.check_login_status = slow
    monkeypatch.setattr(registry.get(CODES[0]), "timeout_seconds", 0.01)
    result = await run(CODES[0], fake)
    assert result.error_code == "TASK_TIMEOUT" and not result.retryable


@pytest.mark.parametrize("status,error,retry", [(401, "SITE_NOT_AUTHENTICATED", False),
    (403, "SITE_NOT_AUTHENTICATED", False), (404, "SITE_LAYOUT_CHANGED", False),
    (400, "SITE_PARSE_FAILED", False), (503, "SITE_NAVIGATION_FAILED", True)])
async def test_http_status_translation(status, error, retry):
    page = Mock(goto=AsyncMock(return_value=status))
    session = Mock(storage_restored=True, guard_state={"blocked": False}, new_page=AsyncMock(return_value=page))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    browser = Mock(start=AsyncMock(), create_session=AsyncMock(return_value=session))
    result = await run(CODES[0], QQWebSiteAdapter(browser, fixture_profile=FixtureProfile("http://127.0.0.1:12345")))
    assert result.error_code == error and result.retryable is retry
    assert result.status == ("NEED_USER_ACTION" if status in {401, 403} else "FAILED")
