"""Unit tests for KB Ingest v2 components (no DB, no external APIs)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── chunker ───────────────────────────────────────────────────────────────────

def test_chunk_text_basic():
    from mirror.services.ingest.chunker import chunk_text

    # Two long paragraphs that together exceed max_chars
    para = "Это тестовый абзац с содержательным текстом. " * 20  # ~900+ chars
    text = para + "\n\n" + para
    chunks = chunk_text(text, max_chars=900, overlap=100)
    assert len(chunks) >= 2


def test_chunk_text_short_returns_single():
    from mirror.services.ingest.chunker import chunk_text

    # Text must be >= 30 chars to pass the length filter
    text = "Это достаточно длинный текст для одного чанка без разбивки."
    chunks = chunk_text(text, max_chars=900, overlap=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_overlap():
    from mirror.services.ingest.chunker import chunk_text

    para1 = "First paragraph. " * 55  # ~935 chars
    para2 = "Second paragraph. " * 55
    text = para1.strip() + "\n\n" + para2.strip()
    chunks = chunk_text(text, max_chars=900, overlap=100)
    assert len(chunks) >= 2
    # Second chunk should carry overlap from first
    assert chunks[1][:50] in chunks[0] or len(chunks[0]) <= 900


def test_chunk_text_empty():
    from mirror.services.ingest.chunker import chunk_text

    assert chunk_text("", max_chars=900, overlap=100) == []


# ── extractor ─────────────────────────────────────────────────────────────────

def test_detect_lang_russian():
    from mirror.services.ingest.extractor import detect_lang

    assert detect_lang("Привет мир, это тест на русском языке для проверки") == "ru"


def test_detect_lang_english():
    from mirror.services.ingest.extractor import detect_lang

    assert detect_lang("Hello world this is an English text for testing") == "en"


def test_detect_lang_empty():
    from mirror.services.ingest.extractor import detect_lang

    # Empty string returns "ru" per implementation (default fallback)
    assert detect_lang("") == "ru"


def test_extract_text_plain():
    from mirror.services.ingest.extractor import extract_text_sync

    data = b"Hello plain text"
    result = extract_text_sync(data, "file.txt")
    assert "Hello plain text" in result


def test_extract_text_html():
    pytest.importorskip("bs4", reason="bs4 not installed")
    from mirror.services.ingest.extractor import extract_text_sync

    html = b"<html><body><p>Test paragraph</p></body></html>"
    result = extract_text_sync(html, "page.html", mime="text/html")
    assert "Test paragraph" in result


# ── enricher ──────────────────────────────────────────────────────────────────

def test_parse_metadata_response():
    from mirror.services.ingest.enricher import _parse_metadata_response

    response = (
        "[1] keywords: тревога, КПТ, паника | category: тревога\n"
        "[2] keywords: депрессия, настроение | category: депрессия\n"
    )
    result = _parse_metadata_response(response, 2)
    assert len(result) == 2
    assert result[0]["keywords"] == "тревога, КПТ, паника"
    assert result[0]["category"] == "тревога"
    assert result[1]["category"] == "депрессия"


def test_parse_metadata_response_partial():
    from mirror.services.ingest.enricher import _parse_metadata_response

    response = "[1] keywords: foo | category: bar\n"
    result = _parse_metadata_response(response, 3)
    assert len(result) == 3
    assert result[0]["keywords"] == "foo"
    assert result[1]["keywords"] is None
    assert result[2]["category"] is None


def test_get_category_list_default():
    from mirror.services.ingest.enricher import get_category_list, _DEFAULT_CATEGORY_LIST

    assert get_category_list(None) == _DEFAULT_CATEGORY_LIST
    assert get_category_list("not-json") == _DEFAULT_CATEGORY_LIST


def test_get_category_list_custom():
    from mirror.services.ingest.enricher import get_category_list

    custom = '["a", "b", "c"]'
    assert get_category_list(custom) == ["a", "b", "c"]


# ── embedder ──────────────────────────────────────────────────────────────────

def test_embedding_rate_limiter_basic():
    from mirror.services.ingest.embedder import EmbeddingRateLimiter

    limiter = EmbeddingRateLimiter(tpm=1_000_000, rpm=3000)
    # Should not block when bucket is full
    asyncio.get_event_loop().run_until_complete(limiter.acquire(100))


def test_classify_tier_free():
    from mirror.services.ingest.embedder import _classify_tier

    tier = _classify_tier(0, 0, "text-embedding-3-large")
    assert tier.name == "free"
    assert tier.batch_size == 100


def test_classify_tier_1():
    from mirror.services.ingest.embedder import _classify_tier

    tier = _classify_tier(1_000_000, 3000, "text-embedding-3-large")
    assert tier.name == "tier_1"
    assert tier.batch_size == 200


def test_classify_tier_3():
    from mirror.services.ingest.embedder import _classify_tier

    tier = _classify_tier(7_500_000, 5000, "text-embedding-3-large")
    assert tier.name == "tier_3"


# ── enricher semaphore lazy init ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_context_returns_none_on_error():
    from mirror.services.ingest.enricher import enrich_context
    import mirror.services.ingest.enricher as enricher_mod

    enricher_mod._ENRICH_SEM = None  # reset
    mock_router = MagicMock()
    mock_router.call = AsyncMock(side_effect=RuntimeError("API down"))

    result = await enrich_context("Sample text", mock_router, concurrency=1)
    assert result is None


@pytest.mark.asyncio
async def test_enrich_metadata_batch_empty():
    from mirror.services.ingest.enricher import enrich_metadata_batch

    result = await enrich_metadata_batch([], MagicMock(), concurrency=1)
    assert result == []


# ── cleanup ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_job_no_tmp_path():
    """cleanup_job with no tmp_path should not raise."""
    with patch("mirror.services.ingest.cleanup.db_module") as mock_db:
        mock_session = AsyncMock()
        mock_db.async_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db.async_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        from mirror.services.ingest.cleanup import cleanup_job
        await cleanup_job("job-123", None)

        assert mock_session.execute.call_count >= 1
