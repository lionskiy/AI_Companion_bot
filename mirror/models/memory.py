from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from mirror.db.session import Base


class MemoryEpisode(Base):
    __tablename__ = "memory_episodes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    qdrant_point_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    importance: Mapped[float] = mapped_column(Numeric(4, 3), server_default=text("0.5"))
    source_mode: Mapped[str] = mapped_column(Text, nullable=False, default="chat", server_default="chat")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Numeric(4, 3), server_default=text("0.5"))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), server_default=text("1.0"))
    consent_scope: Mapped[str | None] = mapped_column(Text)
    qdrant_point_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    source: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(nullable=False, server_default=text("1"), default=1)
    access_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"), default=0)
    last_accessed: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)
