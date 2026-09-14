from app.core.errors import BusinessError
from app.models.common import utcnow
from app.schemas.management import AccountRead, ConfigRead, DefinitionRead, ExecutionRead, NodeRead
from app.services.unit_of_work import UnitOfWork
from app.tasks.registry import registry


async def require_account(repos, account_id):
    account = await repos.accounts.get(account_id)
    if account is None:
        raise BusinessError("ACCOUNT_NOT_FOUND", "账号不存在", 404)
    return account


async def require_node(repos, node_id):
    if node_id is not None and await repos.nodes.get(node_id) is None:
        raise BusinessError("NODE_NOT_FOUND", "节点不存在", 404)


class ManagementService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def accounts(self, offset=0, limit=100):
        async with self.uow.transaction() as repos:
            return [AccountRead.model_validate(a) for a in await repos.accounts.list(offset, limit)]

    async def account(self, account_id):
        async with self.uow.transaction() as repos:
            return AccountRead.model_validate(await require_account(repos, account_id))

    async def create_account(self, data):
        async with self.uow.transaction() as repos:
            await require_node(repos, data.node_id)
            return AccountRead.model_validate(await repos.accounts.add(data.model_dump()))

    async def update_account(self, account_id, data):
        async with self.uow.transaction() as repos:
            account = await require_account(repos, account_id)
            values = data.model_dump(exclude_unset=True)
            await require_node(repos, values.get("node_id"))
            if "node_id" in values and values["node_id"] != account.node_id:
                account.online_status = "UNKNOWN"
            for key, value in values.items():
                setattr(account, key, value)
            account.updated_at = utcnow()
            return AccountRead.model_validate(account)

    async def delete_account(self, account_id):
        async with self.uow.transaction() as repos:
            account = await require_account(repos, account_id)
            configs = await repos.tasks.configs(account_id)
            if any(c.active_execution_id for c in configs):
                raise BusinessError("TASK_RUNNING", "账号仍有执行中的任务", 409)
            account.deleted_at, account.status = utcnow(), "DISABLED"
            for config in configs:
                config.enabled = False

    async def nodes(self, offset=0, limit=100):
        async with self.uow.transaction() as repos:
            return [NodeRead.model_validate(n) for n in await repos.nodes.list(offset, limit)]

    async def create_node(self, data):
        async with self.uow.transaction() as repos:
            return NodeRead.model_validate(await repos.nodes.add(data.model_dump()))

    @staticmethod
    def definition_read(record):
        result = DefinitionRead.model_validate(record)
        try:
            metadata = registry.get(record.task_code).metadata()
        except BusinessError:
            return result
        return result.model_copy(update=metadata)

    async def definitions(self, offset=0, limit=100):
        async with self.uow.transaction() as repos:
            return [self.definition_read(t) for t in await repos.tasks.definitions(
                offset, limit,
            )]

    async def create_definition(self, data):
        async with self.uow.transaction() as repos:
            return self.definition_read(await repos.tasks.add_definition(data.model_dump()))

    async def configs(self, account_id):
        async with self.uow.transaction() as repos:
            await require_account(repos, account_id)
            return [ConfigRead.model_validate(c) for c in await repos.tasks.configs(account_id)]

    async def put_config(self, account_id, code, data):
        async with self.uow.transaction() as repos:
            await require_account(repos, account_id)
            if await repos.tasks.definition(code) is None:
                raise BusinessError("TASK_NOT_FOUND", "任务定义不存在", 404)
            return ConfigRead.model_validate(await repos.tasks.put_config(
                account_id, code, data.model_dump(),
            ))

    async def batch_configs(self, account_id, enabled):
        async with self.uow.transaction() as repos:
            await require_account(repos, account_id)
            configs = await repos.tasks.configs(account_id)
            for config in configs:
                config.enabled = enabled
            return {"updated": len(configs)}

    async def executions(self, offset=0, limit=100, account_id=None, status=None):
        async with self.uow.transaction() as repos:
            return [ExecutionRead.model_validate(e) for e in await repos.executions.list(
                offset, limit, account_id, status,
            )]

    async def execution(self, execution_id):
        async with self.uow.transaction() as repos:
            execution = await repos.executions.get(execution_id)
            if execution is None:
                raise BusinessError("EXECUTION_NOT_FOUND", "执行记录不存在", 404)
            return ExecutionRead.model_validate(execution)
