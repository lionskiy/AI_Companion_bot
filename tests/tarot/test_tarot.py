from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _make_service(llm_response="Интерпретация расклада"):
    llm = MagicMock()
    llm.call = AsyncMock(return_value=llm_response)
    llm.embed = AsyncMock(return_value=[0.0] * 3072)
    from mirror.services.tarot import TarotService
    return TarotService(llm_router=llm)


def _make_state(text="сделай расклад"):
    return {
        "user_id": str(uuid4()), "session_id": str(uuid4()),
        "message": text, "tier": "free",
        "memory_context": {"facts": [], "episodes": []},
        "sales_allowed": True,
    }


# ── deck ──────────────────────────────────────────────────────────────────

def test_deck_has_78_cards():
    from mirror.services.tarot_deck import FULL_DECK
    assert len(FULL_DECK) == 78


def test_deck_no_duplicates():
    from mirror.services.tarot_deck import FULL_DECK
    assert len(FULL_DECK) == len(set(FULL_DECK))


def test_major_arcana_count():
    from mirror.services.tarot_deck import MAJOR_ARCANA
    assert len(MAJOR_ARCANA) == 22


def test_minor_arcana_count():
    from mirror.services.tarot_deck import MINOR_ARCANA
    assert len(MINOR_ARCANA) == 56


# ── draw_cards ────────────────────────────────────────────────────────────

def test_draw_single():
    svc = _make_service()
    cards = svc.draw_cards("single")
    assert len(cards) == 1
    assert cards[0].position == "Ответ"
    assert isinstance(cards[0].is_reversed, bool)
    assert cards[0].name in __import__("mirror.services.tarot_deck", fromlist=["FULL_DECK"]).FULL_DECK


def test_draw_three_card():
    svc = _make_service()
    cards = svc.draw_cards("three_card")
    assert len(cards) == 3
    names = [c.name for c in cards]
    assert len(set(names)) == 3  # no duplicates
    positions = [c.position for c in cards]
    assert "Прошлое" in positions
    assert "Настоящее" in positions
    assert "Будущее" in positions


def test_draw_celtic_cross():
    svc = _make_service()
    cards = svc.draw_cards("celtic_cross")
    assert len(cards) == 10
    names = [c.name for c in cards]
    assert len(set(names)) == 10  # all unique


def test_draw_cards_no_duplicates_across_runs():
    svc = _make_service()
    # Run 10 times, each time all cards unique
    for _ in range(10):
        cards = svc.draw_cards("three_card")
        names = [c.name for c in cards]
        assert len(set(names)) == len(names)


# ── detect_spread_type ────────────────────────────────────────────────────

def test_detect_single_default():
    from mirror.services.tarot import detect_spread_type
    assert detect_spread_type("сделай расклад") == "single"


def test_detect_three_card():
    from mirror.services.tarot import detect_spread_type
    assert detect_spread_type("хочу три карты") == "three_card"
    assert detect_spread_type("прошлое настоящее будущее") == "three_card"


def test_detect_celtic_cross():
    from mirror.services.tarot import detect_spread_type
    assert detect_spread_type("кельтский крест") == "celtic_cross"
    assert detect_spread_type("полный расклад") == "celtic_cross"


# ── handle ────────────────────────────────────────────────────────────────

async def test_handle_calls_llm():
    svc = _make_service("The Moon означает тайны...")
    with patch("mirror.rag.tarot.search_tarot_knowledge", new_callable=AsyncMock, return_value=[]):
        result = await svc.handle(_make_state())
    assert result == "The Moon означает тайны..."
    svc._llm.call.assert_awaited_once()


async def test_handle_three_card():
    svc = _make_service("Три карты рассказывают...")
    with patch("mirror.rag.tarot.search_tarot_knowledge", new_callable=AsyncMock, return_value=["chunk"]):
        result = await svc.handle(_make_state("хочу три карты"))
    assert result == "Три карты рассказывают..."


async def test_handle_rag_chunks_in_prompt():
    """RAG chunks передаются в промпт через meaning_chunks карт."""
    svc = _make_service("ответ")
    captured_messages = []

    async def mock_call(task_kind, messages, tier="free", **kwargs):
        captured_messages.extend(messages)
        return "ответ"

    svc._llm.call = mock_call

    with patch("mirror.rag.tarot.search_tarot_knowledge", new_callable=AsyncMock, return_value=["значение карты"]):
        await svc.handle(_make_state())

    system_content = captured_messages[0]["content"]
    assert "значение карты" in system_content


# ── build_tarot_prompt ────────────────────────────────────────────────────

def test_build_tarot_prompt_contains_card_names():
    from mirror.services.tarot import DrawnCard, build_tarot_prompt
    cards = [
        DrawnCard(name="The Moon", position="Ответ", is_reversed=False, meaning_chunks=[]),
    ]
    messages = build_tarot_prompt(cards, "что меня ждёт?", facts=[], sales_allowed=True)
    assert any("The Moon" in m["content"] for m in messages)


def test_build_tarot_prompt_reversed_label():
    from mirror.services.tarot import DrawnCard, build_tarot_prompt
    cards = [DrawnCard(name="The Tower", position="Прошлое", is_reversed=True, meaning_chunks=[])]
    messages = build_tarot_prompt(cards, "?", facts=[], sales_allowed=True)
    assert "перевёрнутая" in messages[0]["content"]
