from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdType, UTCDateTime, utcnow


class TaskOutbox(Base):
    __tablename__ = "task_outbox"
    id: Mapped[int] = mapped_column(IdType, primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("task_execution.execution_id"), unique=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
