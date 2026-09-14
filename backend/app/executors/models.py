from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.tasks.base import TaskRiskLevel as RiskLevel


class ExecutorType(StrEnum):
    ONEBOT = "ONEBOT"
    BROWSER = "BROWSER"
    MOBILE = "MOBILE"
    NONE = "NONE"


class VerificationLevel(StrEnum):
    NOT_VERIFIED = "NOT_VERIFIED"
    MOCK_ONLY = "MOCK_ONLY"
    FIXTURE_VERIFIED = "FIXTURE_VERIFIED"
    REAL_ENV_VERIFIED = "REAL_ENV_VERIFIED"


class CapabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    SUPPORTED_NOT_READY = "SUPPORTED_NOT_READY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    NEED_USER_ACTION = "NEED_USER_ACTION"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_VERIFIED = "NOT_VERIFIED"
    DEGRADED = "DEGRADED"


class RoutingMode(StrEnum):
    PRODUCTION = "PRODUCTION"
    DIAGNOSTIC = "DIAGNOSTIC"


class OperationCode(StrEnum):
    QQ_ACCOUNT_STATUS_READ = "QQ_ACCOUNT_STATUS_READ"
    QQ_FRIEND_SUMMARY_READ = "QQ_FRIEND_SUMMARY_READ"
    QQ_GROUP_SUMMARY_READ = "QQ_GROUP_SUMMARY_READ"
    QQ_RUNTIME_STATUS_READ = "QQ_RUNTIME_STATUS_READ"
    QQ_WEB_LOGIN_STATUS_READ = "QQ_WEB_LOGIN_STATUS_READ"
    QQ_WEB_PAGE_STATUS_READ = "QQ_WEB_PAGE_STATUS_READ"
    QQ_TASK_CENTER_READ = "QQ_TASK_CENTER_READ"
    QQ_ACTIVITY_READ = "QQ_ACTIVITY_READ"
    QQ_DAILY_CHECKIN = "QQ_DAILY_CHECKIN"
    QQ_ACTIVITY_CLAIM = "QQ_ACTIVITY_CLAIM"
    QQ_FEED_BROWSE = "QQ_FEED_BROWSE"
    QQ_VIDEO_TASK = "QQ_VIDEO_TASK"
    QQ_NOVEL_TASK = "QQ_NOVEL_TASK"
    QQ_GAME_TASK = "QQ_GAME_TASK"
    QQ_QZONE_PUBLISH = "QQ_QZONE_PUBLISH"
    QQ_ADD_FRIEND = "QQ_ADD_FRIEND"


@dataclass(frozen=True)
class Operation:
    code: OperationCode
    read_only: bool
    idempotent: bool
    risk_level: RiskLevel
    side_effect_level: str
    allowed_executors: tuple[ExecutorType, ...]
    capabilities: tuple[str, ...] = ()
    implemented: bool = True


@dataclass(frozen=True)
class ExecutorRuntime:
    configured: bool = False
    ready: bool = False
    authenticated: bool | None = None
    state_present: bool = False
    site_configured: bool = False
    site_operations: frozenset[str] | None = None
    need_user_action: bool = False
    degraded: bool = False
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RoutingContext:
    account_id: int
    platform: str = "QQ"
    active: bool = True
    runtime: dict[ExecutorType, ExecutorRuntime] = field(default_factory=dict)


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    executor: ExecutorType
    status: CapabilityStatus
    runtime_status: CapabilityStatus
    verification_level: VerificationLevel
    reason: str


class CapabilityResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: OperationCode
    selected_executor: ExecutorType | None = None
    risk_level: RiskLevel
    status: CapabilityStatus
    mode: RoutingMode
    reason: str
    error_code: str | None = None
    candidates: list[Candidate]
