from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _make_service(affirmation="Сегодня день возможностей ✨"):
    llm = MagicMock()
    llm.call = AsyncMock(return_value=affirmation)

    tarot = MagicMock()
    from mirror.services.tarot import DrawnCard
    tarot.draw_cards = MagicMock(return_value=[
        DrawnCard(name="The Sun", position="Ответ", is_reversed=False, meaning_chunks=[])
    ])

    astro = MagicMock()
    astro._get_profile = AsyncMock(return_value=None)
    astro.get_current_transits = AsyncMock(return_value=[])

    from mirror.services.daily_ritual import DailyRitualService
    return DailyRitualService(tarot_service=tarot, astrology_service=astro, llm_router=llm)


def _make_state(uid=None):
    return {
        "user_id": str(uid or uuid4()),
        "memory_context": {"facts": [], "episodes": []},
    }


# ── build_ritual ──────────────────────────────────────────────────────────────

async def test_build_ritual_no_birth_data():
    svc = _make_service()
    state = _make_state()
    ritual = await svc.build_ritual(uid := __import__("uuid").UUID(state["user_id"]), state)
    assert ritual.user_id == uid
    assert ritual.card.name == "The Sun"
    assert ritual.transit is None
    assert ritual.affirmation
    assert isinstance(ritual.date, date)


async def test_build_ritual_with_transit():
    from mirror.services.astrology import Transit
    llm = MagicMock()
    llm.call = AsyncMock(return_value="Аффирмация с транзитом")

    tarot = MagicMock()
    from mirror.services.tarot import DrawnCard
    tarot.draw_cards = MagicMock(return_value=[
        DrawnCard(name="The Moon", position="Ответ", is_reversed=True, meaning_chunks=[])
    ])

    profile = MagicMock()
    profile.birth_date = "1990-01-01"
    astro = MagicMock()
    astro._get_profile = AsyncMock(return_value=profile)
    transit = Transit(planet="Mars", sign="Aries", degree=15.0, is_retrograde=False)
    astro.get_current_transits = AsyncMock(return_value=[transit])

    from mirror.services.daily_ritual import DailyRitualService
    svc = DailyRitualService(tarot_service=tarot, astrology_service=astro, llm_router=llm)
    ritual = await svc.build_ritual(__import__("uuid").uuid4())

    assert ritual.transit is not None
    assert ritual.transit.planet == "Mars"


async def test_build_ritual_astrology_exception_silenced():
    llm = MagicMock()
    llm.call = AsyncMock(return_value="Аффирмация")

    tarot = MagicMock()
    from mirror.services.tarot import DrawnCard
    tarot.draw_cards = MagicMock(return_value=[
        DrawnCard(name="The Tower", position="Ответ", is_reversed=False, meaning_chunks=[])
    ])

    astro = MagicMock()
    astro._get_profile = AsyncMock(side_effect=Exception("db error"))

    from mirror.services.daily_ritual import DailyRitualService
    svc = DailyRitualService(tarot_service=tarot, astrology_service=astro, llm_router=llm)
    ritual = await svc.build_ritual(__import__("uuid").uuid4())
    assert ritual.transit is None


# ── format_ritual_message ─────────────────────────────────────────────────────

def test_format_message_basic():
    svc = _make_service()
    from mirror.services.tarot import DrawnCard
    from mirror.services.daily_ritual import DailyRitual
    ritual = DailyRitual(
        user_id=uuid4(),
        card=DrawnCard(name="The Sun", position="Ответ", is_reversed=False, meaning_chunks=[]),
        transit=None,
        affirmation="Свет всегда побеждает тьму",
        date=date.today(),
    )
    msg = svc.format_ritual_message(ritual)
    assert "The Sun" in msg
    assert "Свет всегда побеждает тьму" in msg
    assert "перевёрнутая" not in msg


def test_format_message_reversed():
    svc = _make_service()
    from mirror.services.tarot import DrawnCard
    from mirror.services.daily_ritual import DailyRitual
    ritual = DailyRitual(
        user_id=uuid4(),
        card=DrawnCard(name="The Tower", position="Ответ", is_reversed=True, meaning_chunks=[]),
        transit=None,
        affirmation="Время перемен",
        date=date.today(),
    )
    msg = svc.format_ritual_message(ritual)
    assert "перевёрнутая" in msg


def test_format_message_with_transit():
    from mirror.services.astrology import Transit
    from mirror.services.tarot import DrawnCard
    from mirror.services.daily_ritual import DailyRitual
    svc = _make_service()
    ritual = DailyRitual(
        user_id=uuid4(),
        card=DrawnCard(name="The Star", position="Ответ", is_reversed=False, meaning_chunks=[]),
        transit=Transit(planet="Venus", sign="Pisces", degree=10.0, is_retrograde=False),
        affirmation="Любовь везде",
        date=date.today(),
    )
    msg = svc.format_ritual_message(ritual)
    assert "Venus" in msg
    assert "Pisces" in msg


# ── handle ────────────────────────────────────────────────────────────────────

async def test_handle_disabled():
    svc = _make_service()
    uid = uuid4()

    profile = MagicMock()
    profile.daily_ritual_enabled = False

    with patch.object(svc, "_get_profile", AsyncMock(return_value=profile)):
        result = await svc.handle({"user_id": str(uid), "memory_context": {"facts": []}})

    assert "отключён" in result


async def test_handle_enabled_returns_formatted():
    svc = _make_service("Иди вперёд с уверенностью")
    uid = uuid4()

    profile = MagicMock()
    profile.daily_ritual_enabled = True

    with patch.object(svc, "_get_profile", AsyncMock(return_value=profile)):
        result = await svc.handle({"user_id": str(uid), "memory_context": {"facts": []}})

    assert "Карта дня" in result
    assert "Иди вперёд с уверенностью" in result


async def test_handle_no_profile():
    svc = _make_service("Новый день — новые возможности")

    with patch.object(svc, "_get_profile", AsyncMock(return_value=None)):
        result = await svc.handle({"user_id": str(uuid4()), "memory_context": {"facts": []}})

    assert result


# ── affirmation fallback ───────────────────────────────────────────────────────

async def test_affirmation_fallback_on_llm_error():
    llm = MagicMock()
    llm.call = AsyncMock(side_effect=Exception("LLM down"))

    tarot = MagicMock()
    from mirror.services.tarot import DrawnCard
    tarot.draw_cards = MagicMock(return_value=[
        DrawnCard(name="The Fool", position="Ответ", is_reversed=False, meaning_chunks=[])
    ])
    astro = MagicMock()
    astro._get_profile = AsyncMock(return_value=None)

    from mirror.services.daily_ritual import DailyRitualService
    svc = DailyRitualService(tarot_service=tarot, astrology_service=astro, llm_router=llm)
    ritual = await svc.build_ritual(__import__("uuid").uuid4())
    assert "день" in ritual.affirmation.lower() or len(ritual.affirmation) > 0


# ── idempotency helpers ────────────────────────────────────────────────────────

def test_celery_tasks_importable():
    from mirror.workers.tasks.daily_ritual import send_daily_rituals, send_ritual_to_user
    assert callable(send_daily_rituals)
    assert callable(send_ritual_to_user)
