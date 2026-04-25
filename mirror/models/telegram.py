from sqlalchemy import BigInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from mirror.db.session import Base


class TgBot(Base):
    __tablename__ = "tg_bots"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    token: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("now()::text")
    )
