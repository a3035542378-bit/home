from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.adapters.browser.schemas import safe_origin
from app.adapters.onebot.exceptions import OneBotNotConnectedError
from app.models.common import ExecutionStatus
from app.tasks.base import BaseTask, TaskResult, TaskRiskLevel
from app.tasks.errors import TaskPreconditionError, TaskVerificationError


class OneBotProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BrowserProbeConfig(OneBotProbeConfig):
    url: HttpUrl
    selector: str = Field(default="h1", min_length=1, max_length=200)
    expected_title: str | None = Field(default=None, max_length=200)
    expected_text: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def local_test_only(cls, value):
        # 首批插件限定本机测试服务；不恢复登录态，不读取外部业务页面。
        parsed = urlsplit(str(value))
        if (
            parsed.hostname != "127.0.0.1"
            or parsed.scheme != "http"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"/simple", "/form", "/delay", "/redirect", "/error", "/storage"}
        ):
            raise ValueError("仅允许本地测试站点")
        return value


class ProbeTask(BaseTask):
    idempotent = True
    read_only = True
    side_effect_level = "NONE"
    risk_level = TaskRiskLevel.SAFE_READONLY
    diagnostic_only = True
    scheduled = False
    task_type = "DIAGNOSTIC"
    category = "PROBE"
    retry_safe = True
    error_code_aliases: ClassVar[dict[str, str]] = {
        "ONEBOT_IDENTITY_MISMATCH": "ONEBOT_ACCOUNT_MISMATCH"
    }
    retry_policy: ClassVar[set[str]] = {
        "ADAPTER_TIMEOUT",
        "ADAPTER_CONNECTION_ERROR",
        "ONEBOT_TIMEOUT",
        "ONEBOT_CONNECTION_ERROR",
    }


def success(data, evidence=None):
    return TaskResult(
        success=True,
        status=ExecutionStatus.SUCCESS,
        message="只读诊断通过",
        data=data,
        evidence=evidence or {},
    )


async def onebot_probe(context):
    context.set_stage("ONEBOT")
    onebot = context.get_adapter("onebot")
    status = await onebot.health_check()
    if not status.online or not status.good:
        raise OneBotNotConnectedError()
    login = await onebot.get_login_info()
    if str(login.user_id) != context.account.account_no or context.account.platform != "QQ":
        raise TaskPreconditionError("ONEBOT_ACCOUNT_MISMATCH", "OneBot 登录账号与任务账号不一致")
    return {"login_user_id": "***" + str(login.user_id)[-4:], "account_verified": True}


async def browser_probe(context):
    context.set_stage("BROWSER")
    config = context.validated_config
    browser = context.get_adapter("browser")
    async with await browser.create_session(context.account.id, restore_state=False) as session:
        page = await session.new_page()
        status = await page.goto(str(config.url))
        title = await page.title()
        found = await page.exists(config.selector)
        text = await page.text(config.selector) if found else ""
        title_ok = config.expected_title is None or title == config.expected_title
        text_ok = found and (config.expected_text is None or config.expected_text in text)
        if status is None or status >= 400 or not title_ok or not text_ok:
            raise TaskVerificationError()
        # 动态页面文字不持久化；只保留已知 fixture 标题和验证布尔值。
        evidence = {
            "title": title if title == "Browser fixture" else "[REDACTED]",
            "final_url": safe_origin(page.url),
            "verification": {"title": title_ok, "text": text_ok, "http": True},
        }
        return {"http_status": status, "text_found": found}, evidence
