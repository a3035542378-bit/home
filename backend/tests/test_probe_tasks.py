import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.adapters.browser.fake import FakeBrowserAdapter
from app.adapters.onebot.fake import FakeOneBotAdapter
from app.core.config import Settings
from app.models.common import ExecutionStatus
from app.schemas.management import AccountCreate, ConfigUpdate, DefinitionCreate
from app.services.dispatch import DispatchService
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import AccountContext, TaskContext, TaskResult
from app.tasks.engine import TaskEngine
from app.tasks.plugins.probes.browser_readonly import BrowserReadOnlyProbeTask
from app.tasks.plugins.probes.composite_probe import CompositeProbeTask
from app.tasks.plugins.probes.onebot_readonly import OneBotReadOnlyProbeTask
from app.tasks.registry import TaskRegistry, load_builtin_tasks, registry

CONFIG = {
    "url": "http://127.0.0.1:8765/simple",
    "expected_title": "Browser fixture",
    "expected_text": "Mock",
}


async def run_probe(
    task, *, config=None, browser=None, onebot=None, account_no="123456", **options
):
    load_builtin_tasks()
    context = TaskContext(
        AccountContext(1, account_no, "QQ", ""),
        "probe-execution",
        config if config is not None else ({} if task is OneBotReadOnlyProbeTask else CONFIG),
    )
    return await TaskEngine(
        None,
        adapters={
            "browser": browser or FakeBrowserAdapter(),
            "onebot": onebot or FakeOneBotAdapter(user_id=123456),
        },
        **options,
    ).run(task.task_code, context)


@pytest.mark.parametrize(
    "task", [OneBotReadOnlyProbeTask, BrowserReadOnlyProbeTask, CompositeProbeTask]
)
async def test_success_metadata_versions(task):
    result = await run_probe(task)
    assert result.success
    assert result.task_version == result.plugin_version == "1.0.0"
    assert result.started_at <= result.ended_at
    assert not result.retryable
    meta = task.metadata()
    assert meta["diagnostic_only"] and meta["read_only"] and meta["idempotent"]
    assert meta["risk_level"] == "SAFE_READONLY" and not meta["scheduled"]
    assert registry.get(task.task_code) is task


@pytest.mark.parametrize(
    "mode,code,retry",
    [
        ("offline", "ONEBOT_NOT_CONNECTED", False),
        ("timeout", "ONEBOT_TIMEOUT", False),
        ("transient", "ADAPTER_TIMEOUT", True),
        ("invalid", "ONEBOT_INVALID_RESPONSE", False),
    ],
)
async def test_onebot_failures(mode, code, retry):
    result = await run_probe(OneBotReadOnlyProbeTask, onebot=FakeOneBotAdapter(mode))
    assert result.error_code == code
    assert result.failed_stage == "ONEBOT" and result.retryable is retry


async def test_onebot_account_mismatch():
    result = await run_probe(OneBotReadOnlyProbeTask, account_no="87654321")
    assert result.error_code == "ONEBOT_ACCOUNT_MISMATCH" and not result.retryable
    assert "87654321" not in result.model_dump_json()


@pytest.mark.parametrize(
    "mode,code",
    [
        ("timeout", "BROWSER_ACTION_TIMEOUT"),
        ("navigation_error", "BROWSER_NAVIGATION_ERROR"),
        ("user_action", "BROWSER_USER_ACTION_REQUIRED"),
    ],
)
async def test_browser_failures(mode, code):
    adapter = FakeBrowserAdapter(mode)
    result = await run_probe(BrowserReadOnlyProbeTask, browser=adapter)
    assert result.error_code == code and result.failed_stage == "BROWSER"
    assert all(s.closed for s in adapter.sessions)
    assert not result.retryable
    if mode == "user_action":
        assert result.status == ExecutionStatus.NEED_USER_ACTION


@pytest.mark.parametrize(
    "patch", [{"expected_title": "other"}, {"expected_text": "absent"}, {"selector": "#missing"}]
)
async def test_verification_is_business_failure(patch):
    result = await run_probe(BrowserReadOnlyProbeTask, config={**CONFIG, **patch})
    assert result.error_code == "TASK_VERIFICATION_FAILED" and not result.retryable


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"url": "invalid"},
        {"url": "https://example.com/simple"},
        {**CONFIG, "unexpected": True},
        {**CONFIG, "url": "http://127.0.0.1/simple?token=private"},
    ],
)
async def test_config_before_adapter(config):
    provider = AsyncMock()
    result = await run_probe(CompositeProbeTask, config=config, adapter_provider=provider)
    assert result.error_code == "TASK_CONFIG_INVALID" and result.failed_stage == "CONFIG"
    provider.for_context.assert_not_called()


@pytest.mark.parametrize("stage", ["ONEBOT", "BROWSER"])
async def test_composite_failure_stage(stage):
    browser = FakeBrowserAdapter("timeout" if stage == "BROWSER" else "success")
    onebot = FakeOneBotAdapter("offline" if stage == "ONEBOT" else "success")
    result = await run_probe(CompositeProbeTask, browser=browser, onebot=onebot)
    assert not result.success and result.failed_stage == stage
    if stage == "ONEBOT":
        assert not browser.sessions


async def test_capability_before_execute():
    adapter = FakeBrowserAdapter()
    adapter.capabilities = dict
    result = await run_probe(BrowserReadOnlyProbeTask, browser=adapter)
    assert result.error_code == "CAPABILITY_UNSUPPORTED"
    assert not adapter.sessions


@pytest.mark.parametrize(
    "key", ["cookie", "token", "authorization", "password", "storage_state", "localStorage"]
)
def test_sensitive_evidence_rejected(key):
    with pytest.raises(ValidationError):
        TaskResult(
            success=True, status="SUCCESS", message="ok", evidence={"nested": [{key: "private"}]}
        )


async def test_evidence_and_no_private_logs(caplog):
    result = await run_probe(CompositeProbeTask)
    serialized = result.model_dump_json()
    assert result.evidence["title"] == "Browser fixture"
    assert result.evidence["final_url"] == "http://127.0.0.1:8765"
    assert result.evidence["verification"] == {"title": True, "text": True, "http": True}
    assert result.data["onebot"]["login_user_id"] == "***3456"
    assert "12345678" not in serialized + caplog.text


async def test_plugin_timeout_applies(monkeypatch):
    async def slow(self, context):
        await asyncio.sleep(1)

    monkeypatch.setattr(BrowserReadOnlyProbeTask, "execute", slow)
    monkeypatch.setattr(BrowserReadOnlyProbeTask, "timeout_seconds", 0.01)
    result = await run_probe(BrowserReadOnlyProbeTask)
    assert result.error_code == "TASK_TIMEOUT" and not result.retryable


@pytest.mark.parametrize("idempotent,policy", [(False, {"ADAPTER_TIMEOUT"}), (True, set())])
async def test_unsafe_retry_disabled(monkeypatch, idempotent, policy):
    monkeypatch.setattr(OneBotReadOnlyProbeTask, "idempotent", idempotent)
    monkeypatch.setattr(OneBotReadOnlyProbeTask, "retry_policy", policy)
    result = await run_probe(OneBotReadOnlyProbeTask, onebot=FakeOneBotAdapter("transient"))
    assert not result.retryable


async def test_diagnostic_not_scheduled_and_definition_metadata(database, management):
    load_builtin_tasks()
    account = await management.create_account(
        AccountCreate(account_no="diagnostic", platform="WEB")
    )
    for cls in (OneBotReadOnlyProbeTask, BrowserReadOnlyProbeTask, CompositeProbeTask):
        definition = await management.create_definition(
            DefinitionCreate(task_code=cls.task_code, task_name=cls.task_name)
        )
        assert definition.diagnostic_only and definition.category == "PROBE"
        await management.put_config(
            account.id, cls.task_code, ConfigUpdate(enabled=True, config_json=CONFIG)
        )
    service = DispatchService(
        UnitOfWork(database.sessions),
        Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:"),
    )
    assert await service.schedule() == 0
    assert await management.executions() == []
    assert all(d.diagnostic_only for d in await management.definitions())


def test_plugin_import_boundary():
    forbidden = {
        "sqlalchemy",
        "redis",
        "httpx",
        "requests",
        "playwright",
        "socket",
        "urllib.request",
    }
    for path in Path("backend/app/tasks/plugins").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if isinstance(node, ast.ImportFrom) else [])
            )
            assert not any(
                name and any(name == item or name.startswith(item + ".") for item in forbidden)
                for name in names
            )


async def test_missing_task_result():
    result = await TaskEngine(None, TaskRegistry()).run(
        "ABSENT", TaskContext(AccountContext(1, "1", "WEB", ""), "none")
    )
    assert result.error_code == "TASK_NOT_FOUND"


@pytest.mark.parametrize(
    "mode,expected_children", [("transient", 1), ("timeout", 0), ("offline", 0)]
)
async def test_worker_retry_respects_result_metadata(
    database, management, broker, mode, expected_children
):
    from app.queue.redis_stream import RedisTaskQueue
    from app.workers.worker import Worker

    load_builtin_tasks()
    redis, prefix = broker
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        task_lock_prefix=prefix + ":lock:",
        auto_retry_base_seconds=0,
    )
    queue = RedisTaskQueue(redis, prefix, dlq=prefix + ":dlq")
    service = DispatchService(UnitOfWork(database.sessions), settings, queue)
    account = await management.create_account(AccountCreate(account_no="123456", platform="QQ"))
    await management.create_definition(
        DefinitionCreate(task_code="ONEBOT_READONLY_PROBE", task_name="probe")
    )
    await management.put_config(account.id, "ONEBOT_READONLY_PROBE", ConfigUpdate(enabled=True))
    worker = Worker(
        queue,
        service,
        TaskEngine(None, adapters={"onebot": FakeOneBotAdapter(mode)}),
        redis,
        settings,
    )
    original = await service.submit(account.id, "ONEBOT_READONLY_PROBE")
    await service.publish()
    await worker.process(await queue.dequeue())
    parent = await service.get(original.execution_id)
    assert parent.status == "FAILED"
    records = await management.executions()
    children = [r for r in records if r.parent_execution_id == parent.execution_id]
    assert len(children) == expected_children
    if children:
        assert children[0].status == "PENDING" and children[0].trigger_type == "RETRY"
        assert children[0].execution_id != parent.execution_id
        assert parent.result_json["retryable"] is True


async def test_unconfigured_node_fails_before_browser(database):
    from app.services.onebot import OneBotService

    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    provider = OneBotService(UnitOfWork(database.sessions), settings)
    try:
        result = await run_probe(OneBotReadOnlyProbeTask, adapter_provider=provider)
        assert result.error_code == "NODE_NOT_CONFIGURED" and result.failed_stage == "ONEBOT"
    finally:
        await provider.aclose()


def test_structured_log_fields():
    import json
    import logging

    from app.core.logging import SafeJsonFormatter

    record = logging.LogRecord("app.task", logging.INFO, "", 0, "ignored", (), None)
    record.event = "task_completed"
    for key, value in {
        "execution_id": "execution",
        "account_id": 1,
        "task_code": "PROBE",
        "stage": "BROWSER",
        "status": "SUCCESS",
        "duration": 0.1,
    }.items():
        setattr(record, key, value)
    record.cookie = "private"
    output = json.loads(SafeJsonFormatter().format(record))
    assert output["stage"] == "BROWSER" and output["duration"] == 0.1
    assert "private" not in str(output)


async def test_runtime_identity_error_uses_probe_contract():
    from contextlib import asynccontextmanager

    from app.core.errors import BusinessError

    class Provider:
        @asynccontextmanager
        async def for_context(self, context, required):
            raise BusinessError("ONEBOT_IDENTITY_MISMATCH", "节点登录身份与任务账号不匹配")
            yield {}

    result = await run_probe(OneBotReadOnlyProbeTask, adapter_provider=Provider())
    assert result.error_code == "ONEBOT_ACCOUNT_MISMATCH" and result.failed_stage == "ONEBOT"


async def test_unknown_page_title_redacted(monkeypatch):
    from app.adapters.browser.fake import FakeBrowserPage

    async def private_title(self):
        return "private-page-value"

    monkeypatch.setattr(FakeBrowserPage, "title", private_title)
    result = await run_probe(BrowserReadOnlyProbeTask, config={**CONFIG, "expected_title": None})
    assert result.success and result.evidence["title"] == "[REDACTED]"
    assert "private-page-value" not in result.model_dump_json()


async def test_task_user_action_required(monkeypatch):
    from app.tasks.errors import TaskUserActionRequired

    async def challenge(self, context):
        raise TaskUserActionRequired()

    monkeypatch.setattr(BrowserReadOnlyProbeTask, "execute", challenge)
    result = await run_probe(BrowserReadOnlyProbeTask)
    assert result.status == "NEED_USER_ACTION" and not result.retryable
