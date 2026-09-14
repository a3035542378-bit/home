import pytest
from sqlalchemy import text

from app.core.errors import BusinessError
from app.schemas.management import (
    AccountCreate,
    AccountUpdate,
    ConfigUpdate,
    DefinitionCreate,
    NodeCreate,
)


async def test_account_crud_and_soft_delete(management):
    node = await management.create_node(NodeCreate(name="本机", adapter_type="ONEBOT"))
    account = await management.create_account(AccountCreate(
        account_no="123", nickname="本人", platform="QQ", node_id=node.id,
    ))
    assert account.online_status == "UNKNOWN"
    assert account.created_at.tzinfo is not None
    updated = await management.update_account(account.id, AccountUpdate(nickname="新名字"))
    assert updated.nickname == "新名字"
    assert len(await management.accounts()) == 1
    await management.delete_account(account.id)
    assert await management.accounts() == []
    with pytest.raises(BusinessError, match="账号不存在"):
        await management.account(account.id)


async def test_unique_and_rollback(management):
    data = AccountCreate(account_no="123", platform="QQ")
    await management.create_account(data)
    with pytest.raises(BusinessError) as caught:
        await management.create_account(data)
    assert caught.value.code == "CONFLICT"
    assert len(await management.accounts()) == 1
    await management.create_account(AccountCreate(account_no="456", platform="QQ"))
    assert len(await management.accounts()) == 2


async def test_foreign_key_validation(management):
    with pytest.raises(BusinessError) as caught:
        await management.create_account(AccountCreate(account_no="123", platform="QQ", node_id=999))
    assert caught.value.code == "NODE_NOT_FOUND"


async def test_config_upsert_batch_and_missing(management):
    account = await management.create_account(AccountCreate(account_no="123", platform="QQ"))
    await management.create_definition(DefinitionCreate(task_code="TEST", task_name="测试"))
    config = await management.put_config(account.id, "TEST", ConfigUpdate(enabled=True))
    again = await management.put_config(account.id, "TEST", ConfigUpdate(enabled=False))
    assert again.id == config.id
    assert (await management.batch_configs(account.id, True))["updated"] == 1
    assert (await management.configs(account.id))[0].enabled is True
    with pytest.raises(BusinessError) as caught:
        await management.put_config(account.id, "MISSING", ConfigUpdate(enabled=True))
    assert caught.value.code == "TASK_NOT_FOUND"


async def test_database_constraints(database):
    from sqlalchemy.exc import IntegrityError
    async with database.sessions() as session:
        with pytest.raises(IntegrityError):
            await session.execute(text(
                "INSERT INTO account (account_no,nickname,platform,status,online_status,node_id,"
                "created_at,updated_at) VALUES ('1','','QQ','ACTIVE','UNKNOWN',999,"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ))
        await session.rollback()


async def test_empty_execution_queries(management):
    assert await management.executions() == []
    with pytest.raises(BusinessError) as caught:
        await management.execution("missing")
    assert caught.value.code == "EXECUTION_NOT_FOUND"
