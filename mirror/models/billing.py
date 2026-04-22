from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from mirror.db.session import Base


class QuotaConfig(Base):
    __tablename__ = "quota_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    daily_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    tarot_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    astrology_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
