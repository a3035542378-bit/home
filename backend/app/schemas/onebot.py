from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.adapters.onebot.schemas import LoginInfo, VersionInfo


class NodeConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    onebot_http_url: str | None = Field(default=None, max_length=2048)
    onebot_ws_url: str | None = Field(default=None, max_length=2048)
    secret_ref: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$")

    @field_validator("onebot_http_url", "onebot_ws_url")
    @classmethod
    def valid_url(cls, value, info):
        if value is None:
            return value
        parsed = urlsplit(value)
        schemes = {"http", "https"} if info.field_name == "onebot_http_url" else {"ws", "wss"}
        if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("节点 URL 不允许凭据或查询参数")
        return value


class OneBotConnectionState(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    DEGRADED = "DEGRADED"
    AUTH_FAILED = "AUTH_FAILED"
    UNKNOWN = "UNKNOWN"


class NodeHealth(BaseModel):
    node_id: int
    adapter_type: str
    connection_state: OneBotConnectionState
    account_id: int | None = None
    account_ids: list[int] = Field(default_factory=list)
    login_info: LoginInfo | None = None
    version: VersionInfo | None = None
    error_code: str | None = None
    checked_at: datetime | None = None
    metrics: dict[str, int] = Field(default_factory=dict)
