from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Node, TaskConfig, TaskDefinition, TaskExecution


class AccountRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, account_id: int) -> Account | None:
        return await self.session.scalar(select(Account).where(
            Account.id == account_id, Account.deleted_at.is_(None),
        ).with_for_update())

    async def list(self, offset: int, limit: int):
        return list(await self.session.scalars(select(Account).where(
            Account.deleted_at.is_(None),
        ).order_by(Account.id).offset(offset).limit(limit)))

    async def for_node(self, node_id):
        return list(await self.session.scalars(select(Account).where(
            Account.node_id == node_id, Account.deleted_at.is_(None),
        )))

    async def add(self, values: dict) -> Account:
        account = Account(**values)
        self.session.add(account)
        await self.session.flush()
        return account


class NodeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, node_id: int):
        return await self.session.get(Node, node_id)

    async def list(self, offset: int, limit: int):
        return list(await self.session.scalars(
            select(Node).order_by(Node.id).offset(offset).limit(limit),
        ))

    async def onebot_nodes(self):
        return list(await self.session.scalars(select(Node).where(Node.adapter_type == "ONEBOT")))

    async def locked(self, node_id):
        return await self.session.scalar(select(Node).where(Node.id == node_id).with_for_update())

    async def add(self, values: dict):
        node = Node(**values)
        self.session.add(node)
        await self.session.flush()
        return node


class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def definition(self, code: str):
        return await self.session.scalar(select(TaskDefinition).where(
            TaskDefinition.task_code == code,
        ))

    async def definitions(self, offset: int = 0, limit: int = 100):
        return list(await self.session.scalars(select(TaskDefinition).order_by(
            TaskDefinition.id,
        ).offset(offset).limit(limit)))

    async def add_definition(self, values: dict):
        definition = TaskDefinition(**values)
        self.session.add(definition)
        await self.session.flush()
        return definition

    async def config(self, account_id: int, code: str):
        return await self.session.scalar(select(TaskConfig).where(
            TaskConfig.account_id == account_id, TaskConfig.task_code == code,
        ))

    async def configs(self, account_id: int):
        return list(await self.session.scalars(select(TaskConfig).where(
            TaskConfig.account_id == account_id,
        ).order_by(TaskConfig.id)))

    async def put_config(self, account_id: int, code: str, values: dict):
        item = await self.config(account_id, code)
        if item is None:
            item = TaskConfig(account_id=account_id, task_code=code, **values)
            self.session.add(item)
        else:
            for key, value in values.items():
                setattr(item, key, value)
        await self.session.flush()
        return item


class ExecutionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, execution_id: str):
        return await self.session.scalar(select(TaskExecution).where(
            TaskExecution.execution_id == execution_id,
        ))

    async def list(self, offset: int, limit: int, account_id=None, status=None):
        query = select(TaskExecution)
        if account_id is not None:
            query = query.where(TaskExecution.account_id == account_id)
        if status is not None:
            query = query.where(TaskExecution.status == status)
        return list(await self.session.scalars(query.order_by(
            TaskExecution.id.desc(),
        ).offset(offset).limit(limit)))
