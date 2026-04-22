from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.lrange.return_value = []
    # pipeline() is sync in redis.asyncio; returns a context manager
    pipe = MagicMock()
    pipe.rpush = MagicMock()
    pipe.ltrim = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[1, True, True])
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    r.pipeline = MagicMock(return_value=pipe)  # sync, not coroutine
    return r


@pytest.fixture
def memory_service(mock_redis):
    from mirror.core.memory.service import MemoryService
    return MemoryService(redis_client=mock_redis, llm_router=None)


# ── mem_L1: session history ────────────────────────────────────────────────


async def test_session_history_empty(mock_redis):
    from mirror.core.memory.session import get_session_history
    history = await get_session_history(mock_redis, uuid4())
    assert history == []


async def test_add_to_session_pipeline(mock_redis):
    from mirror.core.memory.session import add_to_session
    uid = uuid4()
    await add_to_session(mock_redis, uid, "user", "hello")
    pipe = mock_redis.pipeline.return_value
    pipe.rpush.assert_called_once()
    pipe.ltrim.assert_called_once()
    pipe.expire.assert_called_once()
    pipe.execute.assert_awaited_once()


# ── mem_L2: episodes ──────────────────────────────────────────────────────


async def test_write_episode(memory_service):
    uid = uuid4()
    sid = uuid4()
    with patch("mirror.core.memory.service.AsyncQdrantClient") as MockQdrant:
        qdrant_instance = AsyncMock()
        MockQdrant.return_value = qdrant_instance

        import mirror.db.session as db_module
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        original_factory = db_module.async_session_factory

        def mock_factory():
            return mock_session

        db_module.async_session_factory = mock_factory
        try:
            episode_id = await memory_service.write_episode(uid, sid, "Test summary")
        finally:
            db_module.async_session_factory = original_factory

    qdrant_instance.upsert.assert_awaited_once()
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


# ── mem_L3: facts ──────────────────────────────────────────────────────────


async def test_write_fact_new(memory_service):
    uid = uuid4()
    with patch("mirror.core.memory.service.AsyncQdrantClient") as MockQdrant:
        qdrant_instance = AsyncMock()
        MockQdrant.return_value = qdrant_instance

        import mirror.db.session as db_module
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=scalar_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        original_factory = db_module.async_session_factory
        db_module.async_session_factory = lambda: mock_session
        try:
            await memory_service.write_fact(uid, "city", "Moscow", fact_type="declared")
        finally:
            db_module.async_session_factory = original_factory

    qdrant_instance.upsert.assert_awaited_once()
    mock_session.add.assert_called_once()


async def test_write_fact_upsert(memory_service):
    """Повторная запись с тем же ключом → обновление, не дублирование."""
    uid = uuid4()
    from mirror.models.memory import MemoryFact
    existing = MemoryFact(user_id=uid, key="city", value="Moscow", fact_type="declared", version=1)
    existing.qdrant_point_id = uuid4()

    with patch("mirror.core.memory.service.AsyncQdrantClient") as MockQdrant:
        qdrant_instance = AsyncMock()
        MockQdrant.return_value = qdrant_instance

        import mirror.db.session as db_module
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=scalar_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        original_factory = db_module.async_session_factory
        db_module.async_session_factory = lambda: mock_session
        try:
            await memory_service.write_fact(uid, "city", "Saint-Petersburg", fact_type="declared")
        finally:
            db_module.async_session_factory = original_factory

    assert existing.value == "Saint-Petersburg"
    assert existing.version == 2
    qdrant_instance.delete.assert_awaited_once()
    mock_session.add.assert_not_called()


# ── search (parallel) ─────────────────────────────────────────────────────


async def test_search_parallel(memory_service):
    uid = uuid4()
    with patch("mirror.core.memory.service.AsyncQdrantClient") as MockQdrant:
        qdrant_instance = AsyncMock()
        qdrant_instance.search.return_value = []
        MockQdrant.return_value = qdrant_instance

        result = await memory_service.search(uid, "test query")

    assert "episodes" in result
    assert "facts" in result
    assert qdrant_instance.search.await_count == 2


# ── forget ────────────────────────────────────────────────────────────────


async def test_forget_marks_deleted(memory_service):
    uid = uuid4()
    from mirror.models.memory import MemoryEpisode, MemoryFact
    ep = MemoryEpisode(user_id=uid, session_id=uuid4(), summary="s", qdrant_point_id=uuid4())
    fact = MemoryFact(user_id=uid, key="k", value="v", fact_type="observed", qdrant_point_id=uuid4())

    with patch("mirror.core.memory.service.AsyncQdrantClient") as MockQdrant:
        qdrant_instance = AsyncMock()
        MockQdrant.return_value = qdrant_instance

        import mirror.db.session as db_module
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        ep_result = MagicMock()
        ep_result.scalars.return_value.all.return_value = [ep]
        fact_result = MagicMock()
        fact_result.scalars.return_value.all.return_value = [fact]
        mock_session.execute = AsyncMock(side_effect=[None, ep_result, fact_result])
        mock_session.commit = AsyncMock()

        original_factory = db_module.async_session_factory
        db_module.async_session_factory = lambda: mock_session
        try:
            await memory_service.forget(uid)
        finally:
            db_module.async_session_factory = original_factory

    assert ep.deleted_at is not None
    assert fact.deleted_at is not None
    qdrant_instance.delete.assert_awaited()
