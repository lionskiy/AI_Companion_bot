from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from mirror.config import settings


class Base(DeclarativeBase):
    pass


_engine = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db_pool() -> None:
    global _engine, async_session_factory
    _engine = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=10,
        max_overflow=20,
        echo=settings.app_env == "development",
    )
    async_session_factory = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )


async def close_db_pool() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
