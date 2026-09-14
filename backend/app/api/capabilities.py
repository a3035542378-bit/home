from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.management import authorize
from app.executors.models import CapabilityResolution, RoutingMode
from app.services.capabilities import CapabilityService


def get_capabilities(request: Request) -> CapabilityService:
    return request.app.state.capabilities


router = APIRouter(prefix="/api", tags=["capabilities"], dependencies=[Depends(authorize)])


@router.get("/accounts/{account_id}/capabilities", response_model=list[CapabilityResolution])
async def capabilities(account_id: int, service: Annotated[CapabilityService, Depends(get_capabilities)],
                       mode: RoutingMode = RoutingMode.PRODUCTION):
    return await service.list(account_id, mode)
