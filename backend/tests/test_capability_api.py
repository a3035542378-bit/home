from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from test_browser_unit import config

from app.adapters.browser.exceptions import BrowserStorageError
from app.api.capabilities import get_capabilities
from app.core.errors import BusinessError
from app.executors.models import ExecutorType as E
from app.main import create_app
from app.models.common import utcnow
from app.schemas.management import AccountCreate, NodeCreate
from app.services.capabilities import BoundExecutorRouter, CapabilityService
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import AccountContext, TaskContext


async def service_for(database, management, tmp_path, *, node_status="CONNECTED", fresh=True, state=None, **settings):
    uow = UnitOfWork(database.sessions)
    node = await management.create_node(NodeCreate(name="capability-node", adapter_type="ONEBOT",
        onebot_http_url="http://private.internal", secret_ref="private_reference"))
    account = await management.create_account(AccountCreate(account_no="private-account", platform="QQ", node_id=node.id))
    async with uow.transaction() as repos:
        stored = await repos.nodes.get(node.id)
        stored.status = node_status
        stored.checked_at = utcnow() - timedelta(hours=1 if not fresh else 0)
        value = await repos.accounts.get(account.id)
        value.online_status = "ONLINE"
    storage = Mock(load=AsyncMock(return_value=state))
    workers = Mock(list=AsyncMock(return_value=[{"worker_id": "private-redis-key", "browser": "UP", "status": "ONLINE"}]))
    settings = config(tmp_path, admin_access_token="testing", **settings)
    service = CapabilityService(uow, settings, storage=storage, workers=workers)
    return account, service, settings


@pytest.mark.parametrize("mode", ["PRODUCTION", "DIAGNOSTIC"])
async def test_capability_api_success_and_sanitization(database, management, tmp_path, mode):
    account, service, settings = await service_for(database, management, tmp_path,
        state={"cookies": [{"name": "private", "value": "private-secret"}], "origins": []})
    app = create_app()
    app.state.settings = settings
    app.dependency_overrides[get_capabilities] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test",
                                headers={"Authorization": "Bearer testing"}) as client:
        response = await client.get(f"/api/accounts/{account.id}/capabilities?mode={mode}")
        assert response.status_code == 200
        values = response.json()
        assert len(values) == 16 and all(v["selected_executor"] is None for v in values)
        assert all(v["mode"] == mode for v in values)
        assert all(word not in response.text.lower() for word in
                   ("private", "cookie", "token", "storage", "redis", "http://"))
        missing = await client.get("/api/accounts/999999/capabilities")
        assert missing.status_code == 404 and missing.json()["error_code"] == "ACCOUNT_NOT_FOUND"
        assert (await client.get(f"/api/accounts/{account.id}/capabilities?mode=INVALID")).status_code == 422
        assert (await client.get(f"/api/accounts/{account.id}/capabilities", headers={"Authorization": "bad"})).status_code == 401


@pytest.mark.parametrize("node_status,fresh,degraded,challenge", [
    ("CONNECTED", True, False, False), ("CONNECTED", False, True, False),
    ("DEGRADED", True, True, False), ("DISCONNECTED", True, True, False), ("AUTH_FAILED", True, False, True),
])
async def test_node_evidence(database, management, tmp_path, node_status, fresh, degraded, challenge):
    account, service, _ = await service_for(database, management, tmp_path, node_status=node_status, fresh=fresh)
    ctx = await service.context(account.id)
    assert ctx.runtime[E.ONEBOT].degraded is degraded
    assert ctx.runtime[E.ONEBOT].need_user_action is challenge
    result = (await service.list(account.id))[0]
    assert result.selected_executor is None
    assert result.status == ("NEED_USER_ACTION" if challenge else "NOT_VERIFIED")


async def test_storage_does_not_imply_authentication(database, management, tmp_path):
    account, service, _ = await service_for(database, management, tmp_path,
        state={"cookies": [{}]}, qq_task_center_url="https://example.com/tasks")
    ctx = await service.context(account.id)
    browser = ctx.runtime[E.BROWSER]
    assert browser.state_present and browser.ready and browser.authenticated is None
    assert browser.site_operations == frozenset({"QQ_TASK_CENTER_READ"})
    result = await service.router.resolve("QQ_TASK_CENTER_READ", ctx)
    assert result.status == "NOT_VERIFIED" and result.candidates[0].runtime_status == "SUPPORTED_NOT_READY"
    other = await service.router.resolve("QQ_ACTIVITY_READ", ctx)
    assert other.candidates[0].runtime_status == "NOT_CONFIGURED"


async def test_corrupt_storage_and_worker_failure(database, management, tmp_path):
    account, service, _ = await service_for(database, management, tmp_path)
    service.storage.load.side_effect = BrowserStorageError()
    service.workers.list.side_effect = BusinessError("REDIS_UNAVAILABLE", "Worker 信息暂不可用")
    ctx = await service.context(account.id)
    assert not ctx.runtime[E.BROWSER].state_present and ctx.runtime[E.BROWSER].degraded
    assert all(v.selected_executor is None for v in await service.list(account.id))


async def test_no_node_and_no_browser(database, management, tmp_path):
    account = await management.create_account(AccountCreate(account_no="no-node", platform="QQ"))
    service = CapabilityService(UnitOfWork(database.sessions), config(tmp_path))
    ctx = await service.context(account.id)
    assert not ctx.runtime[E.ONEBOT].configured and not ctx.runtime[E.BROWSER].ready
    assert not ctx.runtime[E.BROWSER].state_present


async def test_bound_router_and_deleted_account(database, management, tmp_path):
    account, service, _ = await service_for(database, management, tmp_path)
    router = BoundExecutorRouter(service, account.id)
    context = TaskContext(AccountContext(account.id, "private-account", "QQ", "", None), "test")
    result = await router.resolve("QQ_ACCOUNT_STATUS_READ", context)
    assert result.selected_executor is None
    with pytest.raises(BusinessError) as error:
        await router.resolve("QQ_ACCOUNT_STATUS_READ", TaskContext(AccountContext(99999, "", "QQ", "", None), "test"))
    assert error.value.code == "EXECUTOR_NOT_AVAILABLE"
    await management.delete_account(account.id)
    with pytest.raises(BusinessError) as error:
        await service.list(account.id)
    assert error.value.code == "ACCOUNT_NOT_FOUND"
