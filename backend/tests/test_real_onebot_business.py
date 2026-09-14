import os
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.database import Database
from app.services.account_runtime import AccountRuntimeReader
from app.services.management import ManagementService
from app.services.onebot import OneBotService
from app.services.unit_of_work import UnitOfWork
from app.tasks.base import AccountContext, TaskContext
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks


@pytest.mark.real_onebot_business
@pytest.mark.parametrize('code', ['QQ_ACCOUNT_STATUS', 'QQ_FRIEND_SUMMARY', 'QQ_GROUP_SUMMARY', 'QQ_RUNTIME_STATUS'])
async def test_real_onebot_business(code):
    account_id = os.getenv('REAL_ONEBOT_ACCOUNT_ID')
    if not account_id:
        pytest.skip('REAL_ONEBOT_BUSINESS_NOT_TESTED：未配置真实账号')
    settings = Settings()
    database = Database(settings)
    uow = UnitOfWork(database.sessions)
    provider = OneBotService(uow, settings)
    try:
        load_builtin_tasks()
        account = await ManagementService(uow).account(int(account_id))
        execution_id = str(uuid4())
        context = TaskContext(AccountContext(account.id, account.account_no, account.platform, '', account.node_id),
                              execution_id, services={'account_runtime': AccountRuntimeReader(uow, account.id, execution_id)})
        result = await TaskEngine(None, adapter_provider=provider).run(code, context)
        assert result.success, result.error_code
    finally:
        try:
            await provider.aclose()
        finally:
            await database.close()
