from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_name: str = "Account Task Platform"
    environment: str = "development"
    database_url: SecretStr
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    dependency_timeout_seconds: float = Field(default=3, gt=0, le=30)
    admin_access_token: SecretStr = SecretStr("")
    onebot_http_url: SecretStr | None = None
    onebot_ws_url: SecretStr | None = None
    onebot_access_token: SecretStr = SecretStr("")
    onebot_timeout_seconds: float = Field(default=5, gt=0, le=60)
    onebot_retries: int = Field(default=1, ge=0, le=3)
    onebot_http_timeout: float | None = Field(default=None, gt=0, le=60)
    onebot_connect_timeout: float = Field(default=3, gt=0, le=30)
    onebot_max_retries: int | None = Field(default=None, ge=0, le=2)
    onebot_ws_reconnect_min_seconds: float = Field(default=1, gt=0, le=30)
    onebot_ws_reconnect_max_seconds: float = Field(default=30, gt=0, le=300)
    onebot_ws_heartbeat_timeout: float = Field(default=60, gt=0, le=600)
    onebot_poll_interval: float = Field(default=15, gt=0, le=300)
    onebot_node_tokens: SecretStr = SecretStr("{}")
    qq_web_base_url: SecretStr | None = None
    qq_task_center_url: SecretStr | None = None
    qq_activity_url: SecretStr | None = None
    browser_headless: bool = True
    browser_timeout: float = Field(default=5, gt=0, le=120)
    browser_navigation_timeout: float = Field(default=15, gt=0, le=120)
    browser_max_contexts: int = Field(default=5, ge=1, le=100)
    browser_locale: str = "zh-CN"
    browser_timezone: str = "Asia/Shanghai"
    browser_user_agent: str | None = None
    browser_storage_key: SecretStr = SecretStr("")
    browser_state_dir: str = "artifacts/browser-state"
    browser_screenshot_dir: str = "artifacts/screenshots"
    executor_priorities: dict[str, list[str]] = Field(default_factory=dict)
    task_stream_name: str = "qq:task:stream"
    task_consumer_group: str = "qq-workers"
    task_dlq_name: str = "qq:task:dlq"
    task_lock_prefix: str = "task-lock:"
    worker_key_prefix: str = "worker:"
    worker_concurrency: int = Field(default=5, ge=1, le=100)
    worker_heartbeat_interval: float = Field(default=10, gt=0)
    worker_heartbeat_ttl: int = Field(default=60, ge=1)
    execution_lease_seconds: float = Field(default=60, gt=0)
    task_lock_ttl: float = Field(default=60, gt=0)
    task_timeout_seconds: float = Field(default=30, gt=0)
    worker_shutdown_timeout: float = Field(default=20, ge=0)
    maintenance_interval: float = Field(default=5, gt=0)
    outbox_republish_seconds: float = Field(default=30, gt=0)
    max_auto_retry: int = Field(default=2, ge=0, le=5)
    auto_retry_base_seconds: float = Field(default=5, ge=0)
    scheduler_enabled: bool = True
    schedule_hour: int = Field(default=1, ge=0, le=23)
    schedule_minute: int = Field(default=0, ge=0, le=59)
    business_timezone: str = "Asia/Shanghai"

    @field_validator("executor_priorities")
    @classmethod
    def routing_priorities(cls, value):
        from app.executors.catalog import OPERATIONS
        for code, priorities in value.items():
            if (code not in OPERATIONS or not priorities or len(set(priorities)) != len(priorities)
                    or not set(priorities) <= set(OPERATIONS[code].allowed_executors)):
                raise ValueError("执行器优先级必须为已登记 Operation 的无重复白名单")
        return value

    @field_validator("qq_web_base_url", "qq_task_center_url", "qq_activity_url", mode="before")
    @classmethod
    def qq_web_url(cls, value):
        from app.adapters.sites.qq.url_policy import validate_public_url
        return validate_public_url(value)

    @field_validator("business_timezone", "browser_timezone")
    @classmethod
    def valid_timezone(cls, value):
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def heartbeat_settings(self):
        if self.worker_heartbeat_ttl <= self.worker_heartbeat_interval:
            raise ValueError("Worker 心跳 TTL 必须大于心跳间隔")
        if self.onebot_ws_reconnect_max_seconds < self.onebot_ws_reconnect_min_seconds:
            raise ValueError("WS 重连上限不能小于下限")
        import json
        try:
            tokens = json.loads(self.onebot_node_tokens.get_secret_value())
            if not isinstance(tokens, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in tokens.items()
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("ONEBOT_NODE_TOKENS 必须是字符串映射") from None
        return self

    @field_validator("onebot_http_url", "onebot_ws_url", mode="before")
    @classmethod
    def empty_url(cls, value):
        return None if value == "" else value

    @field_validator("onebot_http_url", "onebot_ws_url")
    @classmethod
    def adapter_url(cls, value, info):
        if value is None:
            return value
        url = urlsplit(value.get_secret_value())
        schemes = {"http", "https"} if info.field_name == "onebot_http_url" else {"ws", "wss"}
        if url.scheme not in schemes or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Adapter URL 协议无效，或包含凭据/查询参数")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("mysql+asyncmy://", "sqlite+aiosqlite://")):
            raise ValueError("Use mysql+asyncmy (production) or sqlite+aiosqlite (tests)")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("Use redis:// or rediss://")
        return value
