from fastapi import APIRouter, Depends, Request

from app.api.management import authorize
from app.schemas.onebot import NodeConnection, NodeHealth

router = APIRouter(prefix="/api/nodes", dependencies=[Depends(authorize)], tags=["onebot"])


@router.get("/{node_id}/health", response_model=NodeHealth)
async def node_health(node_id: int, request: Request):
    return await request.app.state.onebot.health(node_id)


@router.put("/{node_id}/connection", status_code=204)
async def configure_node(node_id: int, data: NodeConnection, request: Request):
    await request.app.state.onebot.configure(node_id, data)
