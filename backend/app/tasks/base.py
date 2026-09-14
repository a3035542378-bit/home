from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.core.security import reject_secrets
from app.models.common import ExecutionStatus, utcnow


@dataclass(frozen=True)
class AccountContext:
    id: int
    account_no: str
    platform: str
    nickname: str
    node_id: int | None = None


@dataclass(frozen=True)
class TaskContext:
    account: AccountContext
    execution_id: str
    config: Mapping[str, Any] = field(default_factory=dict)
    adapters: Mapping[str, Any] = field(default_factory=dict)
    task_code: str = ""
    progress: dict[str, str] = field(default_factory=dict)
    validated_config: BaseModel | None = None
    browser_evidence: list[dict] = field(default_factory=list)
    services: Mapping[str, Any] = field(default_factory=dict)
    onebot_worker_retry: bool = False
    onebot_status_only: bool = False

    def get_service(self, name):
        from app.core.errors import BusinessError
        if name not in self.services:
            raise BusinessError("CONTEXT_SERVICE_UNAVAILABLE", "任务只读服务未注入")
        return self.services[name]

    def set_stage(self, stage: str):
        self.progress["stage"] = stage

    def record_browser_evidence(self, evidence):
        from app.adapters.browser.schemas import BrowserEvidence

        if not isinstance(evidence, BrowserEvidence):
            raise TypeError("浏览器证据必须使用 BrowserEvidence")
        self.browser_evidence.append(evidence.model_dump(exclude_none=True))

    def get_adapter(self, name: str):
        from app.adapters.registry import AdapterRegistry

        return AdapterRegistry(self.adapters).get(name)


class TaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    status: ExecutionStatus
    message: str = Field(max_length=2000)
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=64)
    evidence: dict[str, Any] = Field(default_factory=dict)
    failed_stage: str | None = None
    task_version: str = "1.0.0"
    plugin_version: str = "1.0.0"
    retryable: bool = False
    execution_id: str | None = None
    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime = Field(default_factory=utcnow)

    @field_validator("data", "evidence")
    @classmethod
    def no_secret_fields(cls, data):
        return reject_secrets(data)

    @computed_field
    @property
    def started_at(self) -> datetime:
        return self.start_time

    @computed_field
    @property
    def ended_at(self) -> datetime:
        return self.end_time

    @model_validator(mode="after")
    def consistent(self):
        if self.status in {ExecutionStatus.PENDING, ExecutionStatus.RUNNING}:
            raise ValueError("TaskResult 必须为终态")
        if self.success != (self.status == ExecutionStatus.SUCCESS):
            raise ValueError("success 必须与 status 一致")
        if self.success and self.error_code is not None:
            raise ValueError("成功结果不能包含错误码")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("执行时间必须包含时区")
        if self.end_time < self.start_time:
            raise ValueError("结束时间不能早于开始时间")
        return self


class TaskRiskLevel(StrEnum):
    SAFE_READONLY = "SAFE_READONLY"
    LOW_SIDE_EFFECT = "LOW_SIDE_EFFECT"
    HIGH_SIDE_EFFECT = "HIGH_SIDE_EFFECT"


class BaseTask(ABC):
    config_schema: ClassVar[type[BaseModel] | None] = None
    onebot_worker_retry = False
    onebot_status_only = False
    idempotent = False
    read_only = False
    side_effect_level = "HIGH"
    risk_level = TaskRiskLevel.HIGH_SIDE_EFFECT
    diagnostic_only = False
    scheduled = True
    task_type = "BUSINESS"
    category = "GENERAL"
    retry_policy: ClassVar[set[str] | None] = None
    error_code_aliases: ClassVar[dict[str, str]] = {}
    timeout_seconds: float = 60
    task_version = "1.0.0"
    plugin_version = "1.0.0"

    @classmethod
    def metadata(cls):
        keys = (
            "idempotent",
            "read_only",
            "side_effect_level",
            "risk_level",
            "diagnostic_only",
            "scheduled",
            "task_type",
            "category",
            "timeout_seconds",
            "task_version",
            "plugin_version",
        )
        return {
            **{key: getattr(cls, key) for key in keys},
            "retry_policy": sorted(cls.retry_policy) if cls.retry_policy is not None else None,
            "required_capabilities": {k: sorted(v) for k, v in cls.required_capabilities.items()},
        }

    required_capabilities: ClassVar[dict[str, set[str]]] = {}
    retry_safe: bool = False
    task_code: str
    task_name: str = ""

    @abstractmethod
    async def execute(self, context: TaskContext) -> TaskResult:
        raise NotImplementedError

    async def check_status(self, context: TaskContext) -> TaskResult:
        return TaskResult(
            success=False,
            status=ExecutionStatus.SKIPPED,
            message="未实现状态查询",
            error_code="NOT_IMPLEMENTED",
        )
