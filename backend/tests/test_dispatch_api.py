from unittest.mock import AsyncMock

import httpx

from app.api.dispatch import get_dispatch, get_worker_status
from app.core.config import Settings
from app.main import create_app
from app.schemas.management import AccountCreate, ConfigUpdate, DefinitionCreate
from app.services.dispatch import DispatchService
from app.services.unit_of_work import UnitOfWork
from app.tasks.registry import load_builtin_tasks


async def test_execute_api_202_without_engine(database, management):
    load_builtin_tasks()
    config = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", admin_access_token="testing")
    account = await management.create_account(AccountCreate(account_no="api", platform="WEB"))
    await management.create_definition(DefinitionCreate(task_code="MOCK_SUCCESS", task_name="mock"))
    await management.put_config(account.id, "MOCK_SUCCESS", ConfigUpdate(enabled=True))
    service = DispatchService(UnitOfWork(database.sessions), config)
    app = create_app()
    app.state.settings = config
    app.dependency_overrides[get_dispatch] = lambda: service
    status = AsyncMock()
    status.list.return_value = []
    app.dependency_overrides[get_worker_status] = lambda: status
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test",
                                 headers={"Authorization": "Bearer testing"}) as client:
        response = await client.post("/api/tasks/MOCK_SUCCESS/execute", json={"account_id": account.id})
        assert response.status_code == 202
        assert response.json()["status"] == "PENDING"
        saved = await service.get(response.json()["execution_id"])
        assert saved.status == "PENDING"
        duplicate = await client.post("/api/tasks/MOCK_SUCCESS/execute", json={"account_id": account.id})
        assert duplicate.status_code == 409
        assert (await client.post("/api/executions/retry-failed", json={"date": "2026-01-01"})).status_code == 202
        assert (await client.get("/api/system/worker-status")).json() == []


async def test_scheduler_configuration():
    from app.scheduler.scheduler import Scheduler
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:",
                        schedule_hour=3, schedule_minute=15)
    service = AsyncMock()
    scheduler = Scheduler(service, settings)
    scheduler.start()
    try:
        jobs = {job.id: job for job in scheduler.scheduler.get_jobs()}
        assert set(jobs) == {"daily", "maintenance"}
        assert "hour='3'" in str(jobs["daily"].trigger)
        await scheduler.daily()
        service.schedule.assert_awaited_once()
        service.publish.assert_awaited_once()
    finally:
        scheduler.shutdown()


async def test_scheduler_disabled():
    from app.scheduler.scheduler import Scheduler
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", scheduler_enabled=False)
    scheduler = Scheduler(AsyncMock(), settings)
    scheduler.start()
    try:
        assert {job.id for job in scheduler.scheduler.get_jobs()} == {"maintenance"}
    finally:
        scheduler.shutdown()
