from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    api: Literal["UP"] = "UP"
    status: Literal["ok", "degraded"]
    dependencies: dict[str, Literal["ok", "unavailable"]]
    onebot: dict[str, str] = Field(default_factory=dict)
    browser: Literal["UP", "DEGRADED", "DOWN"] = "DEGRADED"
