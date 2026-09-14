import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.system import get_system_service
from app.core.config import Settings
from app.core.database import Database
from app.core.logging import SafeJsonFormatter
from app.main import create_app
from app.services.system_service import SystemService


def settings(**kwargs):
    return Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", **kwargs)


def test_settings_hide_credentials():
    config = settings(redis_url="redis://:secret-token@localhost:6379")
    assert "secret-token" not in repr(config)
    assert "secret-token" not in config.model_dump_json()


@pytest.mark.parametrize("kwargs", [
    {"dependency_timeout_seconds": 0}, {"redis_url": "http://localhost"},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValidationError):
        settings(**kwargs)


def test_invalid_database_driver():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="mysql://localhost/test")


async def test_database_connection_and_session():
    from sqlalchemy import text

    database = Database(settings())
    try:
        await database.ping()
        async with database.sessions() as session:
            assert (await session.execute(text("SELECT 42"))).scalar_one() == 42
    finally:
        await database.close()


@pytest.mark.parametrize("failed", [None, "database", "redis"])
async def test_health_dependencies(failed):
    db, redis = AsyncMock(), AsyncMock()
    if failed:
        {"database": db, "redis": redis}[failed].ping.side_effect = RuntimeError("secret")
    result = await SystemService(db, redis, 1).health()
    assert result.status == ("degraded" if failed else "ok")
    if failed:
        assert result.dependencies[failed] == "unavailable"
    assert "secret" not in result.model_dump_json()


async def test_health_timeout():
    async def slow():
        await asyncio.sleep(10)
    db = AsyncMock()
    db.ping.side_effect = slow
    result = await SystemService(db, AsyncMock(), 0.01).health()
    assert result.dependencies["database"] == "unavailable"


@pytest.mark.parametrize("failed,code", [(False, 200), (True, 503)])
def test_api_health_and_liveness(failed, code):
    app = create_app(settings())
    db, redis = AsyncMock(), AsyncMock()
    if failed:
        db.ping.side_effect = RuntimeError("mysql://user:secret@host")
    app.dependency_overrides[get_system_service] = lambda: SystemService(db, redis, 1)
    with TestClient(app) as client:
        assert client.get("/api/system/live").json() == {"status": "ok"}
        response = client.get("/api/system/health")
        assert response.status_code == code
        assert "secret" not in response.text
        assert client.get("/openapi.json").status_code == 200


def test_lifespan_closes_resources(monkeypatch):
    db, redis = AsyncMock(), AsyncMock()
    worker_status = AsyncMock()
    worker_status.list.return_value = []
    monkeypatch.setattr("app.main.WorkerStatusService", lambda *args: worker_status)
    onebot = AsyncMock()
    onebot.summary.return_value = {}
    monkeypatch.setattr("app.main.OneBotService", lambda *args: onebot)
    monkeypatch.setattr("app.main.Database", lambda _: db)
    monkeypatch.setattr("app.main.create_redis", lambda _: redis)
    with TestClient(create_app(settings())) as client:
        assert client.get("/api/system/health").status_code == 200
    db.close.assert_awaited_once()
    redis.aclose.assert_awaited_once()


def test_logs_discard_secrets_and_keep_context():
    record = logging.LogRecord("app", logging.ERROR, "", 0, "cookie=secret", (), None)
    record.execution_id = "execution-123"
    record.account_id = 7
    record.task_code = "PC_ONLINE"
    record.token = "secret"
    formatted = SafeJsonFormatter().format(record)
    assert "secret" not in formatted
    assert "execution-123" in formatted
    assert "PC_ONLINE" in formatted
