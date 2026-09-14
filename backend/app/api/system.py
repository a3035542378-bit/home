from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.schemas.system import HealthResponse
from app.services.system_service import SystemService

router = APIRouter(prefix="/api/system", tags=["system"])


def get_system_service(request: Request) -> SystemService:
    return request.app.state.system_service


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health(
    response: Response, service: Annotated[SystemService, Depends(get_system_service)],
) -> HealthResponse:
    result = await service.health()
    if result.status != "ok":
        response.status_code = 503
    return result
