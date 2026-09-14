from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import reject_secrets
from app.models.common import ExecutionStatus, TriggerType

Name = Annotated[str, Field(min_length=1, max_length=128)]
Code = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


from app.schemas.onebot import NodeConnection


class NodeCreate(NodeConnection, Input):
    name: Name
    adapter_type: Literal["ONEBOT", "BROWSER", "MOBILE"]


class NodeRead(NodeConnection, Output):
    id: int
    name: str
    adapter_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class AccountCreate(Input):
    account_no: Name
    nickname: str = Field(default="", max_length=128)
    platform: Literal["QQ", "WEB", "MOBILE"]
    node_id: int | None = Field(default=None, gt=0)


class AccountUpdate(Input):
    nickname: str | None = Field(default=None, max_length=128)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    node_id: int | None = Field(default=None, gt=0)

    @field_validator("nickname", "status")
    @classmethod
    def nonnull(cls, value):
        if value is None:
            raise ValueError("字段不能为 null")
        return value


class AccountRead(Output):
    id: int
    account_no: str
    nickname: str
    platform: str
    status: str
    online_status: str
    node_id: int | None
    created_at: datetime
    updated_at: datetime


class DefinitionCreate(Input):
    task_code: Code
    task_name: Name
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="GENERAL", min_length=1, max_length=64)
    default_enabled: bool = False
    executor_type: Literal["NONE", "ONEBOT", "BROWSER", "MOBILE"] = "NONE"


class DefinitionRead(DefinitionCreate, Output):
    retry_policy: list[str] | None = None
    task_type: str = "BUSINESS"
    diagnostic_only: bool = False
    read_only: bool = False
    idempotent: bool = False
    scheduled: bool = True
    side_effect_level: str = "HIGH"
    risk_level: str = "HIGH_SIDE_EFFECT"
    required_capabilities: dict[str, list[str]] = Field(default_factory=dict)
    timeout_seconds: float = 60
    task_version: str = "1.0.0"
    plugin_version: str = "1.0.0"
    id: int
    status: str
    created_at: datetime
    updated_at: datetime


class ConfigUpdate(Input):
    enabled: bool
    config_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config_json")
    @classmethod
    def no_secrets(cls, value):
        return reject_secrets(value)


class ConfigRead(Output):
    id: int
    account_id: int
    task_code: str
    enabled: bool
    config_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class BatchConfig(Input):
    enabled: bool


class ExecutionRead(Output):
    execution_id: str
    account_id: int
    task_code: str
    trigger_type: TriggerType
    status: ExecutionStatus
    retry_count: int
    start_time: datetime | None
    end_time: datetime | None
    result_json: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    parent_execution_id: str | None = None
    business_date: date | None = None
    worker_id: str | None = None
    lease_until: datetime | None = None
    heartbeat_at: datetime | None = None
