from typing import ClassVar

from app.core.errors import BusinessError
from app.models.common import ExecutionStatus as S


class ExecutionStateMachine:
    transitions: ClassVar = {
        S.PENDING: {S.RUNNING, S.SKIPPED, S.FAILED},
        S.RUNNING: {S.SUCCESS, S.FAILED, S.SKIPPED, S.NEED_USER_ACTION},
    }

    @classmethod
    def validate(cls, previous, following):
        if following not in cls.transitions.get(previous, set()):
            raise BusinessError("INVALID_TRANSITION", "执行状态不允许此变更", 409)
