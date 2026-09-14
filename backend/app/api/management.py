import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import BusinessError
from app.models.common import ExecutionStatus
from app.schemas.management import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    BatchConfig,
    ConfigRead,
    ConfigUpdate,
    DefinitionCreate,
    DefinitionRead,
    ExecutionRead,
    NodeCreate,
    NodeRead,
)
from app.services.management import ManagementService

bearer = HTTPBearer(auto_error=False)


async def authorize(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    expected = request.app.state.settings.admin_access_token.get_secret_value()
    if not expected:
        raise BusinessError("AUTH_NOT_CONFIGURED", "请配置管理接口访问凭据", 503)
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), expected.encode("utf-8"),
    ):
        raise BusinessError("UNAUTHORIZED", "管理接口需要有效凭据", 401)


def get_management(request: Request) -> ManagementService:
    return request.app.state.management


Service = Annotated[ManagementService, Depends(get_management)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
router = APIRouter(prefix="/api", dependencies=[Depends(authorize)], tags=["management"])


@router.get("/accounts", response_model=list[AccountRead])
async def accounts(service: Service, offset: Offset = 0, limit: Limit = 100):
    return await service.accounts(offset, limit)


@router.post("/accounts", response_model=AccountRead, status_code=201)
async def create_account(data: AccountCreate, service: Service):
    return await service.create_account(data)


@router.get("/accounts/{account_id}", response_model=AccountRead)
async def account(account_id: int, service: Service):
    return await service.account(account_id)


@router.put("/accounts/{account_id}", response_model=AccountRead)
async def update_account(account_id: int, data: AccountUpdate, service: Service):
    return await service.update_account(account_id, data)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: int, service: Service):
    await service.delete_account(account_id)
    return Response(status_code=204)


@router.get("/accounts/{account_id}/tasks", response_model=list[ConfigRead])
async def configs(account_id: int, service: Service):
    return await service.configs(account_id)


@router.put("/accounts/{account_id}/tasks/{task_code}", response_model=ConfigRead)
async def put_config(account_id: int, task_code: str, data: ConfigUpdate, service: Service):
    return await service.put_config(account_id, task_code, data)


@router.patch("/accounts/{account_id}/tasks")
async def batch_config(account_id: int, data: BatchConfig, service: Service):
    return await service.batch_configs(account_id, data.enabled)


@router.get("/tasks", response_model=list[DefinitionRead])
async def definitions(service: Service, offset: Offset = 0, limit: Limit = 100):
    return await service.definitions(offset, limit)


@router.post("/tasks", response_model=DefinitionRead, status_code=201)
async def create_definition(data: DefinitionCreate, service: Service):
    return await service.create_definition(data)


@router.get("/nodes", response_model=list[NodeRead])
async def nodes(service: Service, offset: Offset = 0, limit: Limit = 100):
    return await service.nodes(offset, limit)


@router.post("/nodes", response_model=NodeRead, status_code=201)
async def create_node(data: NodeCreate, service: Service):
    return await service.create_node(data)


@router.get("/executions", response_model=list[ExecutionRead])
async def executions(
    service: Service, offset: Offset = 0, limit: Limit = 100,
    account_id: int | None = None, status: ExecutionStatus | None = None,
):
    return await service.executions(offset, limit, account_id, status)


@router.get("/executions/{execution_id}", response_model=ExecutionRead)
async def execution(execution_id: str, service: Service):
    return await service.execution(execution_id)
