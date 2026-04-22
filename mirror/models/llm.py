from sqlalchemy import Boolean, ForeignKey, Integer, JSON, Numeric, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from mirror.db.session import Base


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    provider_id: Mapped[str] = mapped_column(Text, primary_key=True)
    base_url: Mapped[str | None] = mapped_column(Text)
    api_key_env: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class LLMRouting(Base):
    __tablename__ = "llm_routing"

    task_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    tier: Mapped[str] = mapped_column(Text, primary_key=True, server_default="*")
    provider_id: Mapped[str] = mapped_column(Text, ForeignKey("llm_providers.provider_id"), nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_chain: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1000"))
    temperature: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, server_default=text("0.7"))
