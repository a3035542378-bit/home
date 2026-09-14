from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdType, TimestampMixin


class TaskConfig(TimestampMixin, Base):
    __tablename__ = "task_config"
    __table_args__ = (UniqueConstraint("account_id", "task_code"),)

    id: Mapped[int] = mapped_column(IdType, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    task_code: Mapped[str] = mapped_column(ForeignKey("task_definition.task_code"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 非空表示已被执行占用；原子条件更新保护多进程并发。
    active_execution_id: Mapped[str | None] = mapped_column(String(36))
