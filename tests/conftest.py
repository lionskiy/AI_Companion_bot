import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import mirror.db.session as db_module
from mirror.db.session import Base

TEST_DATABASE_URL = "postgresql+asyncpg://mirror:mirror@localhost:19102/mirror_test"


@pytest.fixture(scope="session")
async def test_engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture(scope="session", autouse=True)
async def setup_db_pool(test_engine):
    """Установить глобальный async_session_factory на тестовый engine."""
    db_module.async_session_factory = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )


@pytest.fixture
async def db_session(test_engine):
    async with AsyncSession(test_engine) as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client():
    from mirror.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
