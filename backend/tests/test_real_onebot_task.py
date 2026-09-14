import os

import pytest

from app.core.config import Settings
from app.core.database import Database
from app.services.management import ManagementService
from app.services.onebot import OneBotService
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import AccountContext, TaskContext
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks


@pytest.mark.real_onebot_task
async def test_real_onebot_probe_task():
    account_id = os.getenv("REAL_ONEBOT_ACCOUNT_ID")
    if not account_id:
        pytest.skip("REAL_ONEBOT_TASK_NOT_TESTED：尚未配置真实账号")
    settings = Settings()
    database = Database(settings)
    provider = OneBotService(UnitOfWork(database.sessions), settings)
    try:
        load_builtin_tasks()
        account = await ManagementService(UnitOfWork(database.sessions)).account(int(account_id))
        context = TaskContext(
            AccountContext(account.id, account.account_no, account.platform, "", account.node_id),
            "real-onebot-task-diagnostic",
        )
        result = await TaskEngine(None, adapter_provider=provider).run(
            "ONEBOT_READONLY_PROBE", context
        )
        assert result.success, result.error_code
        assert result.data["account_verified"] is True
    finally:
        await provider.aclose()
        await database.close()
