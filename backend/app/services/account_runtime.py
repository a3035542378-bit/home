from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import BusinessError
from app.models.common import utcnow


class RuntimeQuery(BaseModel):
    model_config = ConfigDict(strict=True)
    hours: int = Field(default=24, ge=1, le=168)


class AccountRuntimeReader:
    """能力固定绑定一个账号与当前执行，不接受其他账号 ID。"""

    def __init__(self, uow, account_id, execution_id, clock=utcnow):
        self._uow, self._account_id, self._execution_id, self._clock = (
            uow,
            account_id,
            execution_id,
            clock,
        )

    async def snapshot(self, hours=24):
        query = RuntimeQuery(hours=hours)
        now = self._clock()
        async with self._uow.transaction() as repos:
            result = await repos.account_runtime.snapshot(
                self._account_id,
                self._execution_id,
                now - timedelta(hours=query.hours),
                now,
            )
        if result is None:
            raise BusinessError("ACCOUNT_NOT_FOUND", "账号不存在", 404)
        return result
