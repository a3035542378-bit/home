from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdType, TimestampMixin, UTCDateTime


class Account(TimestampMixin, Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("platform", "account_no"),)

    id: Mapped[int] = mapped_column(IdType, primary_key=True)
    account_no: Mapped[str] = mapped_column(String(128))
    nickname: Mapped[str] = mapped_column(String(128), default="")
    platform: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    online_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    node_id: Mapped[int | None] = mapped_column(ForeignKey("node.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
