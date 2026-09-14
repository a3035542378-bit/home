from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.errors import BusinessError
from app.repositories.account_runtime import AccountRuntimeRepository
from app.repositories.dispatch import DispatchRepository
from app.repositories.management import (
    AccountRepository,
    ExecutionRepository,
    NodeRepository,
    TaskRepository,
)
from app.repositories.runtime import RuntimeRepository


class Repositories:
    def __init__(self, session):
        self.account_runtime = AccountRuntimeRepository(session)
        self.accounts = AccountRepository(session)
        self.nodes = NodeRepository(session)
        self.tasks = TaskRepository(session)
        self.executions = ExecutionRepository(session)
        self.runtime = RuntimeRepository(session)
        self.dispatch = DispatchRepository(session)


class UnitOfWork:
    def __init__(self, sessions):
        self.sessions = sessions

    @asynccontextmanager
    async def transaction(self):
        try:
            async with self.sessions() as session, session.begin():
                yield Repositories(session)
        except IntegrityError as exc:
            raise BusinessError("CONFLICT", "记录重复或关联约束冲突", 409) from exc
        except SQLAlchemyError as exc:
            raise BusinessError("DATABASE_ERROR", "数据库操作失败", 503) from exc
