from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.common import TriggerType, utcnow


class TaskJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    execution_id: str = Field(min_length=1, max_length=36)
    account_id: int = Field(gt=0)
    task_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    trigger_type: TriggerType
    created_at: datetime = Field(default_factory=utcnow)
    retry_count: int = Field(default=0, ge=0)

    @field_validator("created_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("消息时间必须带时区")
        return value


@dataclass(frozen=True)
class Delivery:
    message_id: str
    payload: str


class TaskQueue(Protocol):
    async def enqueue(self, job: TaskJob) -> str: ...
    async def dequeue(self) -> Delivery | None: ...
    async def ack(self, delivery: Delivery) -> None: ...
    async def retry(self, job: TaskJob) -> str: ...
    async def size(self) -> int: ...
