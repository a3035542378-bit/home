from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from app.api.management import authorize
from app.schemas.management import ExecutionRead, Input
from app.services.dispatch import DispatchService
from app.services.worker_status import WorkerStatusService


def get_dispatch(request: Request):
    return request.app.state.dispatch


def get_worker_status(request: Request):
    return request.app.state.worker_status


Dispatch = Annotated[DispatchService, Depends(get_dispatch)]
router = APIRouter(prefix="/api", dependencies=[Depends(authorize)], tags=["queue"])


class ExecuteRequest(Input):
    account_id: int = Field(gt=0)


class RetryRequest(Input):
    account_id: int | None = Field(default=None, gt=0)
    date: Date | None = None


@router.post("/tasks/{task_code}/execute", response_model=ExecutionRead, status_code=202)
async def execute(task_code: str, body: ExecuteRequest, service: Dispatch):
    # 只落库到 Outbox；独立 Worker/Scheduler 将其投递至 Stream。
    return await service.submit(body.account_id, task_code)


@router.post("/executions/retry-failed", status_code=202)
async def retry_failed(service: Dispatch, body: RetryRequest | None = None):
    body = body or RetryRequest()
    return await service.retry_failed(body.account_id, body.date)


@router.get("/system/worker-status")
async def worker_status(service: Annotated[WorkerStatusService, Depends(get_worker_status)]):
    return await service.list()
