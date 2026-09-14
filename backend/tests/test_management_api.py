import httpx

from app.api.management import get_management
from app.core.config import Settings
from app.main import create_app


async def test_management_api(management):
    app = create_app()
    app.state.settings = Settings(
        _env_file=None, database_url="sqlite+aiosqlite:///:memory:", admin_access_token="test-only",
    )
    app.dependency_overrides[get_management] = lambda: management
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/accounts")).status_code == 401
        c.headers["Authorization"] = "Bearer test-only"
        assert (await c.post("/api/nodes", json={
            "name": "API测试节点", "adapter_type": "ONEBOT",
        })).status_code == 201
        assert len((await c.get("/api/nodes")).json()) == 1
        created = await c.post("/api/accounts", json={"account_no": "123", "platform": "QQ"})
        assert created.status_code == 201, created.text
        account_id = created.json()["id"]
        assert (await c.get(f"/api/accounts/{account_id}")).status_code == 200
        assert (await c.put(f"/api/accounts/{account_id}", json={"nickname": "测试"})).status_code == 200
        assert (await c.post("/api/tasks", json={"task_code": "TEST", "task_name": "测试"})).status_code == 201
        assert len((await c.get("/api/tasks")).json()) == 1
        assert (await c.put(f"/api/accounts/{account_id}/tasks/TEST", json={"enabled": True})).status_code == 200
        assert len((await c.get(f"/api/accounts/{account_id}/tasks")).json()) == 1
        assert (await c.patch(f"/api/accounts/{account_id}/tasks", json={"enabled": False})).json() == {"updated": 1}
        assert (await c.get("/api/accounts?limit=9999")).status_code == 422
        bad = await c.put(f"/api/accounts/{account_id}/tasks/TEST", json={
            "enabled": True, "config_json": {"token": "never-echo-this"},
        })
        assert bad.status_code == 422
        assert "never-echo-this" not in bad.text
        assert (await c.get("/api/executions")).json() == []
        assert (await c.delete(f"/api/accounts/{account_id}")).status_code == 204
        assert (await c.get(f"/api/accounts/{account_id}")).status_code == 404


async def test_unconfigured_auth():
    app = create_app()
    app.state.settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/accounts")).status_code == 503
