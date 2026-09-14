import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.capabilities import router as capabilities_router
from app.api.dispatch import router as dispatch_router
from app.api.management import router as management_router
from app.api.onebot import router as onebot_router
from app.api.system import router
from app.core.config import Settings
from app.core.database import Database
from app.core.errors import BusinessError
from app.core.logging import configure_logging
from app.core.redis import create_redis
from app.queue.factory import make_queue
from app.services.capabilities import CapabilityService
from app.services.dispatch import DispatchService
from app.services.management import ManagementService
from app.services.onebot import OneBotService
from app.services.system_service import SystemService
from app.services.unit_of_work import UnitOfWork
from app.services.worker_status import WorkerStatusService
from app.tasks.registry import load_builtin_tasks


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings if settings is not None else Settings()
        configure_logging()
        load_builtin_tasks()
        database = Database(config)
        redis = create_redis(config)
        app.state.onebot = OneBotService(UnitOfWork(database.sessions), config)
        app.state.settings = config
        app.state.management = ManagementService(UnitOfWork(database.sessions))
        app.state.dispatch = DispatchService(UnitOfWork(database.sessions), config, make_queue(redis, config))
        app.state.worker_status = WorkerStatusService(redis, config)
        app.state.capabilities = CapabilityService(UnitOfWork(database.sessions), config, workers=app.state.worker_status)
        app.state.system_service = SystemService(
            database, redis, config.dependency_timeout_seconds, onebot=app.state.onebot, worker_status=app.state.worker_status,
        )
        try:
            yield
        finally:
            try:
                await app.state.onebot.aclose()
                await redis.aclose()
            finally:
                await database.close()

    application = FastAPI(title="Account Task Platform", version="0.1.0", lifespan=lifespan)
    application.include_router(router)
    application.include_router(management_router)
    application.include_router(dispatch_router)
    application.include_router(onebot_router)
    application.include_router(capabilities_router)

    @application.exception_handler(BusinessError)
    async def business_error(request, exc):
        return JSONResponse(status_code=exc.http_status, content={
            "error_code": exc.code, "message": exc.message,
        })

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # 不回显输入值或校验异常上下文，避免泄露错误提交的凭据。
        logging.getLogger("app.api").warning(
            "validation_error", extra={"event": "validation_error"},
        )
        return JSONResponse(status_code=422, content={
            "error_code": "VALIDATION_ERROR", "message": "请求参数不符合约束",
        })

    return application


app = create_app()
