import logging
from contextlib import contextmanager
from time import monotonic
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import ExecutionStatus, utcnow
from app.tasks.base import BaseTask, TaskResult, TaskRiskLevel
from app.tasks.errors import TaskPreconditionError

logger = logging.getLogger("app.qq.task")


class EmptyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class FriendConfig(EmptyConfig):
    include_category_counts: bool = False


class GroupConfig(EmptyConfig):
    include_role_counts: bool = False


class RuntimeConfig(EmptyConfig):
    execution_history_hours: int = Field(default=24, ge=1, le=168)


class QQReadOnlyTask(BaseTask):
    category = "QQ_ACCOUNT"
    diagnostic_only = False
    scheduled = False
    read_only = True
    idempotent = True
    risk_level = TaskRiskLevel.SAFE_READONLY
    side_effect_level = "NONE"
    onebot_worker_retry = True
    retry_policy: ClassVar[set[str]] = {"ONEBOT_TIMEOUT", "ONEBOT_CONNECTION_ERROR"}
    error_code_aliases: ClassVar[dict[str, str]] = {
        "ONEBOT_NOT_CONNECTED": "ONEBOT_OFFLINE",
        "ONEBOT_IDENTITY_MISMATCH": "ONEBOT_ACCOUNT_MISMATCH",
        "ONEBOT_AUTHENTICATION_ERROR": "ONEBOT_AUTH_FAILED",
    }
    task_version = "1.0.0"
    plugin_version = "1.0.0"


def adapter(context):
    context.set_stage("ONEBOT")
    if context.account.platform != "QQ":
        raise TaskPreconditionError("TASK_PRECONDITION_FAILED", "任务仅支持 QQ 账号")
    return context.get_adapter("onebot")


def result(context, data, connection_state=None):
    evidence = {"node_id": context.account.node_id, "checked_at": utcnow().isoformat()}
    if connection_state:
        evidence["connection_state"] = connection_state
    return TaskResult(
        success=True,
        status=ExecutionStatus.SUCCESS,
        message="只读状态查询完成",
        data=data,
        evidence=evidence,
    )


@contextmanager
def measure(context, stage):
    context.set_stage(stage)
    start = monotonic()
    try:
        yield
    finally:
        logger.info(
            "qq_read_latency",
            extra={
                "event": "qq_read_latency",
                "stage": stage,
                "execution_id": context.execution_id,
                "account_id": context.account.id,
                "task_code": context.task_code,
                "duration": monotonic() - start,
            },
        )
