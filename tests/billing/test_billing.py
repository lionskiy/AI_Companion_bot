from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _make_redis(eval_return=1, get_return=b"5"):
    r = MagicMock()
    r.eval = AsyncMock(return_value=eval_return)
    r.get = AsyncMock(return_value=get_return)
    return r


def _make_service(redis=None):
    from mirror.services.billing import BillingService
    return BillingService(redis=redis or _make_redis())


# ── quota_limit helper ────────────────────────────────────────────────────────

def test_quota_limit_messages():
    from mirror.services.billing import BillingService
    quota = {"daily_messages": 20, "tarot_per_day": 3, "astrology_per_day": 3}
    assert BillingService._quota_limit(quota, "messages") == 20


def test_quota_limit_tarot():
    from mirror.services.billing import BillingService
    quota = {"daily_messages": 20, "tarot_per_day": 5, "astrology_per_day": 3}
    assert BillingService._quota_limit(quota, "tarot") == 5


def test_quota_limit_unknown_defaults():
    from mirror.services.billing import BillingService
    quota = {"daily_messages": 15}
    assert BillingService._quota_limit(quota, "unknown") == 15


# ── check_quota ───────────────────────────────────────────────────────────────

async def test_check_quota_ok():
    svc = _make_service(_make_redis(eval_return=3))
    quota_cfg = {"daily_messages": 20, "tarot_per_day": 3, "astrology_per_day": 3}

    with patch.object(svc, "_get_quota_config", AsyncMock(return_value=quota_cfg)):
        await svc.check_quota(uuid4(), "free", "messages")


async def test_check_quota_exceeded_raises():
    from mirror.services.billing import QuotaExceededError
    svc = _make_service(_make_redis(eval_return=-1))
    quota_cfg = {"daily_messages": 20, "tarot_per_day": 3, "astrology_per_day": 3}

    with patch.object(svc, "_get_quota_config", AsyncMock(return_value=quota_cfg)):
        with pytest.raises(QuotaExceededError) as exc_info:
            await svc.check_quota(uuid4(), "free", "messages")

    assert exc_info.value.tier == "free"
    assert exc_info.value.quota_type == "messages"


async def test_check_quota_tarot_exceeded():
    from mirror.services.billing import QuotaExceededError
    svc = _make_service(_make_redis(eval_return=-1))
    quota_cfg = {"daily_messages": 20, "tarot_per_day": 3, "astrology_per_day": 3}

    with patch.object(svc, "_get_quota_config", AsyncMock(return_value=quota_cfg)):
        with pytest.raises(QuotaExceededError) as exc_info:
            await svc.check_quota(uuid4(), "free", "tarot")

    assert exc_info.value.quota_type == "tarot"


# ── get_tier ──────────────────────────────────────────────────────────────────

async def test_get_tier_returns_free_when_no_subscription():
    svc = _make_service()
    uid = uuid4()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    import mirror.db.session as db_module
    with patch.object(db_module, "async_session_factory", return_value=mock_ctx):
        tier = await svc.get_tier(uid)

    assert tier == "free"


async def test_get_tier_returns_premium():
    svc = _make_service()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = "premium"
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    import mirror.db.session as db_module
    with patch.object(db_module, "async_session_factory", return_value=mock_ctx):
        tier = await svc.get_tier(uuid4())

    assert tier == "premium"


# ── get_remaining_quota ───────────────────────────────────────────────────────

async def test_get_remaining_quota():
    redis = _make_redis(get_return=b"7")
    svc = _make_service(redis)
    quota_cfg = {"daily_messages": 20, "tarot_per_day": 3, "astrology_per_day": 3}

    with patch.object(svc, "_get_quota_config", AsyncMock(return_value=quota_cfg)):
        remaining = await svc.get_remaining_quota(uuid4(), "free", "messages")

    assert remaining == 13  # 20 - 7


async def test_get_remaining_quota_none_key():
    redis = _make_redis(get_return=None)
    svc = _make_service(redis)
    quota_cfg = {"daily_messages": 20, "tarot_per_day": 3, "astrology_per_day": 3}

    with patch.object(svc, "_get_quota_config", AsyncMock(return_value=quota_cfg)):
        remaining = await svc.get_remaining_quota(uuid4(), "free", "messages")

    assert remaining == 20


# ── helpers ───────────────────────────────────────────────────────────────────

def test_today_str_format():
    from mirror.services.billing import _today_str
    s = _today_str()
    assert len(s) == 10
    assert s[4] == "-" and s[7] == "-"


def test_midnight_ts_is_future():
    from mirror.services.billing import _midnight_ts
    import time
    ts = _midnight_ts()
    assert ts > int(time.time())


def test_invalidate_quota_cache():
    from mirror.services.billing import _QUOTA_CACHE, invalidate_quota_cache
    _QUOTA_CACHE["free"] = {"daily_messages": 20}
    invalidate_quota_cache()
    assert "free" not in _QUOTA_CACHE
