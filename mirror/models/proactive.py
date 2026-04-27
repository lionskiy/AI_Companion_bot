from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from mirror.db.session import Base


class ProactiveLog(Base):
    __tablename__ = "proactive_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
