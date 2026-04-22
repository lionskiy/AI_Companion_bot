import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Numeric, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from mirror.db.session import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("subscription IN ('free','basic','plus','pro')", name="users_subscription_check"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    is_tester: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Moscow")
    language_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    channel_identities: Mapped[list["ChannelIdentity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint("channel", "channel_user_id", name="uq_channel_identities"),
        CheckConstraint("channel IN ('telegram','vk','whatsapp','web','mobile')", name="channel_identities_channel_check"),
        Index("idx_channel_identities_global", "global_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    channel_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    global_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    # Telegram metadata (populated/updated on every message)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    meta_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship(back_populates="channel_identities")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Astrology / birth data (migration 005)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    birth_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    birth_city: Mapped[str | None] = mapped_column(Text, nullable=True)
    birth_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    birth_lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    zodiac_sign: Mapped[str | None] = mapped_column(Text, nullable=True)
    natal_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Daily ritual (migration 006)
    daily_ritual_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Psychological portrait (migration 010)
    mbti_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    communication_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    dominant_themes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    profile_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship(back_populates="profile")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("tier IN ('free','basic','plus','pro')", name="subscriptions_tier_check"),
        Index("idx_subscriptions_active_user", "user_id", unique=True, postgresql_where="is_active = true"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship(back_populates="subscriptions")
