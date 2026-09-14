from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdType, TimestampMixin, UTCDateTime


class Node(TimestampMixin, Base):
    __tablename__ = "node"

    id: Mapped[int] = mapped_column(IdType, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    adapter_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")

    onebot_http_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    onebot_ws_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    secret_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    ws_state: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
    ws_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
