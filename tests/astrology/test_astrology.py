from datetime import date, time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _make_service(llm_response="Интерпретация натальной карты"):
    llm = MagicMock()
    llm.call = AsyncMock(return_value=llm_response)
    llm.embed = AsyncMock(return_value=[0.0] * 3072)
    redis = AsyncMock()
    redis.get.return_value = None
    from mirror.services.astrology import AstrologyService
    return AstrologyService(llm_router=llm, redis_client=redis)


def _make_profile(with_birth=True):
    from mirror.models.user import UserProfile
    p = UserProfile()
    p.user_id = uuid4()
    if with_birth:
        p.birth_date = date(1990, 3, 15)
        p.birth_time = time(14, 30)
        p.birth_lat = 55.75
        p.birth_lon = 37.62
        p.birth_city = "Moscow"
        p.natal_data = None
    else:
        p.birth_date = None
    return p


# ── NatalChart ────────────────────────────────────────────────────────────

async def test_get_natal_chart_returns_planets():
    svc = _make_service()
    profile = _make_profile(with_birth=True)

    with patch.object(svc, "_get_profile", new_callable=AsyncMock, return_value=profile):
        with patch.object(svc, "_save_natal_cache", new_callable=AsyncMock):
            chart = await svc.get_natal_chart(profile.user_id)

    assert "Sun" in chart.planets or len(chart.planets) > 0
    assert isinstance(chart.planets, dict)


async def test_get_natal_chart_no_birth_data_returns_empty():
    svc = _make_service()
    profile = _make_profile(with_birth=False)

    with patch.object(svc, "_get_profile", new_callable=AsyncMock, return_value=profile):
        chart = await svc.get_natal_chart(profile.user_id)

    assert chart.planets == {}


async def test_get_natal_chart_uses_cache():
    svc = _make_service()
    profile = _make_profile(with_birth=True)
    profile.natal_data = {
        "planets": {"Sun": {"sign": "Pisces", "degree": 24.0, "house": 3}},
        "houses": {},
        "aspects": [],
    }

    with patch.object(svc, "_get_profile", new_callable=AsyncMock, return_value=profile):
        chart = await svc.get_natal_chart(profile.user_id)

    assert chart.planets["Sun"]["sign"] == "Pisces"


# ── Transits ──────────────────────────────────────────────────────────────

async def test_get_current_transits_returns_list():
    svc = _make_service()
    transits = await svc.get_current_transits()
    assert isinstance(transits, list)
    assert len(transits) > 0
    t = transits[0]
    assert hasattr(t, "planet")
    assert hasattr(t, "sign")
    assert isinstance(t.is_retrograde, bool)


# ── collect_birth_data ────────────────────────────────────────────────────

async def test_collect_birth_data_returns_question():
    svc = _make_service()
    state = {
        "user_id": str(uuid4()), "session_id": str(uuid4()),
        "message": "расскажи про мою карту", "tier": "free",
        "memory_context": {"facts": [], "episodes": []},
        "sales_allowed": True,
    }
    result = await svc.collect_birth_data(state)
    assert "дату рождения" in result.lower() or "рождения" in result.lower()


# ── handle without birth_data ─────────────────────────────────────────────

async def test_handle_no_birth_data_asks_question():
    svc = _make_service()
    profile = _make_profile(with_birth=False)
    state = {
        "user_id": str(profile.user_id), "session_id": str(uuid4()),
        "message": "хочу узнать про мою натальную карту", "tier": "free",
        "memory_context": {"facts": [], "episodes": []},
        "sales_allowed": True,
    }
    with patch.object(svc, "_get_profile", new_callable=AsyncMock, return_value=profile):
        result = await svc.handle(state)

    assert "рождения" in result.lower()
    svc._llm.call.assert_not_awaited()


# ── handle with birth_data ────────────────────────────────────────────────

async def test_handle_with_birth_data_calls_llm():
    svc = _make_service("Солнце в Рыбах означает...")
    profile = _make_profile(with_birth=True)
    profile.natal_data = {
        "planets": {"Sun": {"sign": "Pisces", "degree": 24.0, "house": 3}},
        "houses": {}, "aspects": [],
    }
    state = {
        "user_id": str(profile.user_id), "session_id": str(uuid4()),
        "message": "что означает моё солнце?", "tier": "free",
        "memory_context": {"facts": [], "episodes": []},
        "sales_allowed": True,
    }
    with patch.object(svc, "_get_profile", new_callable=AsyncMock, return_value=profile):
        with patch("mirror.rag.astrology.search_astro_knowledge", new_callable=AsyncMock, return_value=[]):
            result = await svc.handle(state)

    assert result == "Солнце в Рыбах означает..."
    svc._llm.call.assert_awaited_once()


# ── formatters ────────────────────────────────────────────────────────────

def test_format_natal_chart():
    from mirror.services.astrology import NatalChart, format_natal_chart
    chart = NatalChart(planets={"Sun": {"sign": "Aries", "degree": 10.0, "house": 1}})
    text = format_natal_chart(chart)
    assert "Sun" in text
    assert "Aries" in text


def test_format_transits():
    from mirror.services.astrology import Transit, format_transits
    transits = [Transit(planet="Mars", sign="Leo", degree=15.0, is_retrograde=True)]
    text = format_transits(transits)
    assert "Mars" in text
    assert "ретроград" in text


# ── RAG ──────────────────────────────────────────────────────────────────

async def test_rag_search_returns_empty_on_error():
    from mirror.rag.astrology import search_astro_knowledge
    llm = MagicMock()
    llm.embed = AsyncMock(side_effect=Exception("embed failed"))
    result = await search_astro_knowledge("тест", "", llm)
    assert result == []
