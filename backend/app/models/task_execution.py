from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdType, UTCDateTime, utcnow


class TaskExecution(Base):
    __tablename__ = "task_execution"
    __table_args__ = (
        Index("ix_execution_created_status", "created_at", "status"),
        Index("ix_execution_account_task", "account_id", "task_code", "created_at"),
        CheckConstraint("retry_count >= 0", name="retry_nonnegative"),
        Index("ix_execution_status_lease", "status", "lease_until"),
    )

    id: Mapped[int] = mapped_column(IdType, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(36), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    task_code: Mapped[str] = mapped_column(ForeignKey("task_definition.task_code"))
    trigger_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_execution.execution_id"), unique=True,
    )
    business_date: Mapped[date | None] = mapped_column(Date)
    schedule_key: Mapped[str | None] = mapped_column(String(180), unique=True)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dlq_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    start_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    end_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
