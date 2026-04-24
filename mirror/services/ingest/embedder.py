"""Tier detection + Token Bucket rate limiter for OpenAI Embeddings API."""
import asyncio
import time
from dataclasses import dataclass

import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger()

_EMBEDDING_TIER: "EmbeddingTierConfig | None" = None
_EMBEDDING_TIER_AT: float = 0.0
_EMBEDDING_TIER_TTL: float = 3600.0
_EMBEDDING_TIER_LOCK: asyncio.Lock | None = None  # lazy — created on first use


def _get_tier_lock() -> asyncio.Lock:
    global _EMBEDDING_TIER_LOCK
    if _EMBEDDING_TIER_LOCK is None:
        _EMBEDDING_TIER_LOCK = asyncio.Lock()
    return _EMBEDDING_TIER_LOCK


@dataclass
class EmbeddingTierConfig:
    name: str
    tpm: int
    rpm: int
    batch_size: int
    max_concurrent: int
    model_id: str


_TIER_TABLE = [
    # (tpm_min, name, batch_size, max_concurrent)
    (50_000_000, "tier_5",  2048, 40),
    (20_000_000, "tier_4",  2048, 15),
    (7_000_000,  "tier_3",  1000,  8),
    (3_000_000,  "tier_2",   500,  5),
    (800_000,    "tier_1",   200,  2),
    (0,          "free",     100,  1),
]


def _classify_tier(tpm: int, rpm: int, model_id: str) -> EmbeddingTierConfig:
    for tpm_min, name, batch_size, max_concurrent in _TIER_TABLE:
        if tpm >= tpm_min:
            return EmbeddingTierConfig(
                name=name, tpm=tpm, rpm=rpm,
                batch_size=batch_size,
                max_concurrent=max_concurrent,
                model_id=model_id,
            )
    return EmbeddingTierConfig(
        name="free", tpm=max(tpm, 1_000_000), rpm=max(rpm, 3000),
        batch_size=100, max_concurrent=1, model_id=model_id,
    )


async def get_embedding_tier(llm_router) -> EmbeddingTierConfig:
    global _EMBEDDING_TIER, _EMBEDDING_TIER_AT
    lock = _get_tier_lock()
    async with lock:
        if _EMBEDDING_TIER and time.monotonic() - _EMBEDDING_TIER_AT < _EMBEDDING_TIER_TTL:
            return _EMBEDDING_TIER
        tier = await _probe_embedding_tier(llm_router)
        _EMBEDDING_TIER = tier
        _EMBEDDING_TIER_AT = time.monotonic()
        logger.info("embedder.tier_detected", tier=tier.name, tpm=tier.tpm,
                    batch_size=tier.batch_size, max_concurrent=tier.max_concurrent)
        return tier


async def _probe_embedding_tier(llm_router) -> EmbeddingTierConfig:
    routing = await llm_router._get_routing("embedding", "*")
    api_key = llm_router._get_api_key(routing.provider_id)
    client = AsyncOpenAI(api_key=api_key, timeout=15)
    try:
        resp = await client.embeddings.create(
            model=routing.model_id,
            input=["probe"],
            encoding_format="float",
        )
        raw = resp._raw_response
        tpm = int(raw.headers.get("x-ratelimit-limit-tokens", 0))
        rpm = int(raw.headers.get("x-ratelimit-limit-requests", 0))
        if tpm == 0:
            tpm = 1_000_000
        if rpm == 0:
            rpm = 3000
        return _classify_tier(tpm, rpm, routing.model_id)
    except Exception as e:
        logger.warning("embedder.probe_failed", error=str(e))
        return _classify_tier(1_000_000, 3000, routing.model_id)
    finally:
        await client.close()


class EmbeddingRateLimiter:
    """Token Bucket rate limiter for OpenAI Embeddings API."""

    def __init__(self, tpm: int, rpm: int) -> None:
        self._tpm = max(tpm, 1)
        self._rpm = max(rpm, 1)
        self._token_bucket = float(self._tpm)
        self._request_bucket = float(self._rpm)
        self._last_refill = time.monotonic()
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self, tokens_needed: int) -> None:
        lock = self._get_lock()
        while True:
            async with lock:
                self._refill()
                if self._token_bucket >= tokens_needed and self._request_bucket >= 1:
                    self._token_bucket -= tokens_needed
                    self._request_bucket -= 1
                    return
                needed = max(
                    (tokens_needed - self._token_bucket) / self._tpm * 60,
                    (1 - self._request_bucket) / self._rpm * 60,
                    0.05,
                )
            await asyncio.sleep(needed)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._token_bucket = min(
            float(self._tpm),
            self._token_bucket + self._tpm * elapsed / 60,
        )
        self._request_bucket = min(
            float(self._rpm),
            self._request_bucket + self._rpm * elapsed / 60,
        )
        self._last_refill = now
