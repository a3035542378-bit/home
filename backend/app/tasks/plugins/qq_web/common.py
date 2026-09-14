from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from app.adapters.sites.qq.exceptions import SiteNeedUserAction
from app.adapters.sites.qq.schemas import PageKey
from app.models.common import ExecutionStatus
from app.tasks.base import BaseTask, TaskResult, TaskRiskLevel
from app.tasks.errors import TaskPreconditionError


class EmptyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PageConfig(EmptyConfig):
    page_key: PageKey = PageKey.PROFILE


class QQWebReadOnlyTask(BaseTask):
    category = "QQ_WEB"
    diagnostic_only = False
    scheduled = False
    read_only = True
    idempotent = True
    risk_level = TaskRiskLevel.SAFE_READONLY
    side_effect_level = "NONE"
    task_version = plugin_version = "1.0.0"
    retry_policy: ClassVar[set[str]] = {"SITE_NAVIGATION_FAILED"}

    async def read(self, context, method, *args):
        if context.account.platform != "QQ":
            raise TaskPreconditionError("TASK_PRECONDITION_FAILED", "任务仅支持 QQ 账号")
        context.set_stage("QQ_WEB_READ")
        site = context.get_adapter("qq_web")
        try:
            observation = await getattr(site, method)(*args)
        except SiteNeedUserAction as exc:
            return TaskResult(success=False, status=ExecutionStatus.NEED_USER_ACTION,
                              error_code=exc.code, message=exc.message, failed_stage="QQ_WEB_READ",
                              data={"authenticated": False, "login_state": exc.state.value})
        payload = observation.model_dump(mode="json")
        return TaskResult(success=True, status=ExecutionStatus.SUCCESS, message="Web 只读查询完成",
                          evidence=payload.pop("evidence"), data=payload)
