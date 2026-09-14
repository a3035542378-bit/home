import pytest
from sqlalchemy import event

from app import models  # noqa: F401
from app.core.config import Settings
from app.core.database import Base, Database
from app.services.management import ManagementService
from app.services.unit_of_work import UnitOfWork


@pytest.fixture
async def database(tmp_path):
    db = Database(Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
    ))

    @event.listens_for(db.engine.sync_engine, "connect")
    def foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield db
    await db.close()


@pytest.fixture
def management(database):
    return ManagementService(UnitOfWork(database.sessions))


from uuid import uuid4

from redis.asyncio import Redis


@pytest.fixture
async def broker():
    import os
    client = Redis.from_url(os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/15"), decode_responses=True)
    await client.ping()
    prefix = "test:" + uuid4().hex
    yield client, prefix
    keys = [key async for key in client.scan_iter(match=prefix + "*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()



def pytest_collection_modifyitems(config, items):
    # 即使有人设置真实环境变量，普通 pytest 也不会访问 QQ。
    if config.option.markexpr.strip() != 'real_onebot':
        for item in items:
            if item.get_closest_marker('real_onebot'):
                item.add_marker(pytest.mark.skip(reason='真实联调仅允许显式 -m real_onebot'))

    if config.option.markexpr.strip() != "browser_integration":
        for item in items:
            if item.get_closest_marker("browser_integration"):
                item.add_marker(pytest.mark.skip(reason="Chromium 集成测试需显式 -m browser_integration"))

    if config.option.markexpr.strip() != "real_onebot_task":
        for item in items:
            if item.get_closest_marker("real_onebot_task"):
                item.add_marker(pytest.mark.skip(reason="真实任务仅显式 -m real_onebot_task"))

    if config.option.markexpr.strip() != "real_onebot_business":
        for item in items:
            if item.get_closest_marker("real_onebot_business"):
                item.add_marker(pytest.mark.skip(reason="真实 QQ 业务只读测试仅显式 -m real_onebot_business"))
