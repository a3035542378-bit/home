from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PageKey(StrEnum):
    TASK_CENTER = "TASK_CENTER"
    ACTIVITY_CENTER = "ACTIVITY_CENTER"
    PROFILE = "PROFILE"


class QQWebLoginState(StrEnum):
    AUTHENTICATED = "AUTHENTICATED"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    NEED_QR_LOGIN = "NEED_QR_LOGIN"
    NEED_CAPTCHA = "NEED_CAPTCHA"
    NEED_DEVICE_VERIFICATION = "NEED_DEVICE_VERIFICATION"
    UNKNOWN = "UNKNOWN"


LoginState = QQWebLoginState


class ItemStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CLAIMABLE = "CLAIMABLE"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


class SafeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class SiteEvidence(SafeModel):
    page_key: PageKey
    final_url: str
    page_title: str
    parsed_item_count: int = Field(default=0, ge=0, le=100)
    checked_at: str


class LoginStatus(SafeModel):
    authenticated: bool = True
    login_state: LoginState
    evidence: SiteEvidence


class PageStatus(LoginStatus):
    available: bool = True


class TaskItem(SafeModel):
    task_key: str = Field(max_length=64)
    title: str = Field(max_length=100)
    status: ItemStatus


class TaskCenterSummary(SafeModel):
    total: int = Field(ge=0, le=100)
    completed: int = Field(ge=0, le=100)
    pending: int = Field(ge=0, le=100)
    items: list[TaskItem] = Field(max_length=100)
    evidence: SiteEvidence


class ActivitySummary(SafeModel):
    activity_count: int = Field(ge=0, le=100)
    available_count: int = Field(ge=0, le=100)
    evidence: SiteEvidence
