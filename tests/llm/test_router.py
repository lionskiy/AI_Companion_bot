from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from mirror.core.llm.exceptions import AllModelsUnavailableError

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _make_routing(provider_id="openai", model_id="gpt-4o-mini", fallback_chain=None):
    from mirror.models.llm import LLMRouting
    r = LLMRouting()
    r.task_kind = "main_chat"
    r.tier = "*"
    r.provider_id = provider_id
    r.model_id = model_id
    r.fallback_chain = fallback_chain or []
    r.max_tokens = 1000
    r.temperature = 0.7
    return r


@pytest.fixture
def router():
    from mirror.core.llm.router import LLMRouter
    r = LLMRouter()
    r._routing_cache.clear()
    return r


# ── call: success on first try ────────────────────────────────────────────


async def test_call_success(router):
    routing = _make_routing()
    router._routing_cache[("main_chat", "free")] = routing

    with patch.object(router, "_call_provider", new_callable=AsyncMock, return_value="Hello"):
        result = await router.call("main_chat", [{"role": "user", "content": "hi"}])

    assert result == "Hello"


# ── retry on RateLimitError ───────────────────────────────────────────────


async def test_retry_on_rate_limit(router):
    from openai import RateLimitError as OpenAIRateLimitError
    routing = _make_routing()
    router._routing_cache[("main_chat", "free")] = routing

    call_count = 0

    async def flaky(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise OpenAIRateLimitError("rate limit", response=MagicMock(status_code=429), body={})
        return "OK after retry"

    with patch.object(router, "_call_provider", side_effect=flaky):
        with patch("mirror.core.llm.router.asyncio.sleep", new_callable=AsyncMock):
            result = await router.call("main_chat", [])

    assert result == "OK after retry"
    assert call_count == 3


# ── fallback chain ────────────────────────────────────────────────────────


async def test_fallback_to_anthropic(router):
    from openai import APIError as OpenAIAPIError
    routing = _make_routing(
        fallback_chain=[{"provider_id": "anthropic", "model_id": "claude-haiku-4-5-20251001"}]
    )
    router._routing_cache[("main_chat", "free")] = routing

    async def provider_dispatch(provider_id, model_id, *args, **kwargs):
        if provider_id == "openai":
            raise OpenAIAPIError("error", request=MagicMock(), body={})
        return f"anthropic:{model_id}"

    with patch.object(router, "_call_provider", side_effect=provider_dispatch):
        result = await router.call("main_chat", [])

    assert result == "anthropic:claude-haiku-4-5-20251001"


# ── all models unavailable ────────────────────────────────────────────────


async def test_all_models_unavailable(router):
    from openai import APIError as OpenAIAPIError
    routing = _make_routing(
        fallback_chain=[{"provider_id": "anthropic", "model_id": "claude-haiku-4-5-20251001"}]
    )
    router._routing_cache[("main_chat", "free")] = routing

    with patch.object(router, "_call_provider", side_effect=OpenAIAPIError("error", request=MagicMock(), body={})):
        with pytest.raises(AllModelsUnavailableError):
            await router.call("main_chat", [])


# ── no routing entry → ValueError ────────────────────────────────────────


async def test_missing_routing_raises(router):
    with patch.object(router, "_fetch_routing", new_callable=AsyncMock, return_value=None):
        with pytest.raises(ValueError, match="No routing"):
            await router.call("unknown_task", [])


# ── invalidate_cache ──────────────────────────────────────────────────────


def test_invalidate_cache(router):
    router._routing_cache[("main_chat", "*")] = _make_routing()
    router.invalidate_cache()
    assert len(router._routing_cache) == 0


# ── validate_routing ─────────────────────────────────────────────────────


async def test_validate_routing_all_covered(router):
    from mirror.core.llm.router import CANONICAL_TASK_KINDS
    import mirror.db.session as db_module

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    row_mock = MagicMock()
    row_mock.fetchall.return_value = [(kind,) for kind in CANONICAL_TASK_KINDS]
    mock_session.execute = AsyncMock(return_value=row_mock)

    original = db_module.async_session_factory
    db_module.async_session_factory = MagicMock(return_value=mock_session)
    try:
        await router.validate_routing()  # should not raise
    finally:
        db_module.async_session_factory = original


async def test_validate_routing_missing_raises(router):
    import mirror.db.session as db_module

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    row_mock = MagicMock()
    row_mock.fetchall.return_value = [("main_chat",)]  # only one covered
    mock_session.execute = AsyncMock(return_value=row_mock)

    original = db_module.async_session_factory
    db_module.async_session_factory = MagicMock(return_value=mock_session)
    try:
        with pytest.raises(ValueError, match="LLM routing missing"):
            await router.validate_routing()
    finally:
        db_module.async_session_factory = original


# ── embed ─────────────────────────────────────────────────────────────────


async def test_embed_returns_vector(router):
    routing = _make_routing(provider_id="openai", model_id="text-embedding-3-large")
    router._routing_cache[("embedding", "*")] = routing

    fake_embedding = [0.1] * 3072
    mock_resp = MagicMock()
    mock_resp.data = [MagicMock(embedding=fake_embedding)]

    with patch("mirror.core.llm.router.AsyncOpenAI") as MockOpenAI:
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_resp)
        MockOpenAI.return_value = mock_client

        result = await router.embed("test text")

    assert result == fake_embedding
    assert len(result) == 3072
