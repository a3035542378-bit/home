from contextlib import asynccontextmanager

from app.core.config import Settings
from app.core.database import Database
from app.services.runtime_adapters import RuntimeAdapters
from app.services.task_runtime import TaskRuntimeService
from app.services.unit_of_work import UnitOfWork
from app.tasks.engine import TaskEngine
from app.tasks.registry import load_builtin_tasks


@asynccontextmanager
async def task_engine(settings: Settings):
    load_builtin_tasks()
    database = Database(settings)
    adapters = RuntimeAdapters(UnitOfWork(database.sessions), settings)
    try:
        await adapters.start()
        yield TaskEngine(TaskRuntimeService(UnitOfWork(database.sessions)), adapter_provider=adapters)
    finally:
        try:
            await adapters.aclose()
        finally:
            await database.close()
