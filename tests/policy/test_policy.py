from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from mirror.core.policy.models import RiskLevel
from mirror.core.policy.patterns import fast_pattern_match

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ── patterns (sync) ───────────────────────────────────────────────────────


def test_pattern_crisis():
    assert fast_pattern_match("не хочу жить") == "crisis"
    assert fast_pattern_match("хочу умереть") == "crisis"
    assert fast_pattern_match("суицид") == "crisis"


def test_pattern_risk_signal():
    assert fast_pattern_match("всё бессмысленно") == "risk_signal"
    assert fast_pattern_match("никому не нужен") == "risk_signal"


def test_pattern_referral_hint():
    assert fast_pattern_match("нужен психолог") == "referral_hint"


def test_pattern_wellbeing():
    assert fast_pattern_match("расскажи про луну") is None


def test_pattern_priority_crisis_wins():
    # если оба — crisis и risk_signal — crisis должен выиграть
    assert fast_pattern_match("не хочу жить, всё бессмысленно") == "crisis"


# ── PolicyEngine (async, db mocked) ───────────────────────────────────────


@pytest.fixture
def engine_no_llm():
    from mirror.core.policy.safety import PolicyEngine
    eng = PolicyEngine(llm_router=None)
    eng._crisis_response = "Crisis template 8-800-2000-122"
    eng._referral_hint = "Referral hint text"
    return eng


async def _check(engine, text_):
    uid = uuid4()
    with (
        patch("mirror.core.policy.safety.db_module") as mock_db,
        patch("mirror.core.policy.safety.publish_crisis_detected", new_callable=AsyncMock),
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_db.async_session_factory = MagicMock(return_value=mock_session)
        return await engine.check(uid, text_)


async def test_check_crisis(engine_no_llm):
    result = await _check(engine_no_llm, "не хочу жить")
    assert result.risk_level == RiskLevel.CRISIS
    assert result.blocked is True
    assert result.sales_allowed is False
    assert "8-800-2000-122" in result.crisis_response


async def test_check_risk_signal(engine_no_llm):
    result = await _check(engine_no_llm, "всё бессмысленно")
    assert result.risk_level == RiskLevel.RISK_SIGNAL
    assert result.blocked is False
    assert result.sales_allowed is False


async def test_check_referral_hint(engine_no_llm):
    result = await _check(engine_no_llm, "нужен психолог")
    assert result.risk_level == RiskLevel.REFERRAL_HINT
    assert result.blocked is False
    assert result.sales_allowed is False
    assert result.referral_hint is not None


async def test_check_wellbeing(engine_no_llm):
    result = await _check(engine_no_llm, "расскажи гороскоп на сегодня")
    assert result.risk_level == RiskLevel.WELLBEING
    assert result.sales_allowed is True
    assert result.blocked is False


async def test_crisis_publishes_nats(engine_no_llm):
    uid = uuid4()
    with (
        patch("mirror.core.policy.safety.db_module") as mock_db,
        patch("mirror.core.policy.safety.publish_crisis_detected", new_callable=AsyncMock) as mock_pub,
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_db.async_session_factory = MagicMock(return_value=mock_session)
        await engine_no_llm.check(uid, "хочу умереть")
    mock_pub.assert_awaited_once()


async def test_safety_log_has_no_message_text(engine_no_llm):
    """safety_log не должен содержать текст сообщения."""
    from mirror.models.policy import SafetyLog
    uid = uuid4()
    logged_objects = []

    with (
        patch("mirror.core.policy.safety.db_module") as mock_db,
        patch("mirror.core.policy.safety.publish_crisis_detected", new_callable=AsyncMock),
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock(side_effect=lambda obj: logged_objects.append(obj))
        mock_session.commit = AsyncMock()
        mock_db.async_session_factory = MagicMock(return_value=mock_session)
        await engine_no_llm.check(uid, "не хочу жить — это секретное сообщение")

    assert len(logged_objects) == 1
    log = logged_objects[0]
    assert isinstance(log, SafetyLog)
    assert "секретное сообщение" not in str(log.__dict__)
    assert log.risk_level == "crisis"
    assert log.user_id == uid
