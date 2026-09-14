from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdType, TimestampMixin


class TaskDefinition(TimestampMixin, Base):
    __tablename__ = "task_definition"

    id: Mapped[int] = mapped_column(IdType, primary_key=True)
    task_code: Mapped[str] = mapped_column(String(64), unique=True)
    task_name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="GENERAL")
    default_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    executor_type: Mapped[str] = mapped_column(String(32), default="NONE")
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
