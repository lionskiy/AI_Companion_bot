from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ── helpers ───────────────────────────────────────────────────────────────

def _make_msg(text="привет", user_id=None):
    from mirror.channels.base import UnifiedMessage
    return UnifiedMessage(
        message_id="1",
        channel="telegram",
        chat_id="42",
        channel_user_id="42",
        global_user_id=str(user_id or uuid4()),
        text=text,
        timestamp=datetime.now(timezone.utc),
        session_id=str(uuid4()),
        metadata={},
        raw_payload={},
    )


@dataclass
class _QuotaResult:
    allowed: bool
    message: str | None = None


def _make_billing(tier="free", allowed=True):
    from mirror.services.billing import QuotaExceededError
    b = AsyncMock()
    b.get_tier.return_value = tier
    if not allowed:
        b.check_quota.side_effect = QuotaExceededError(tier=tier, quota_type="messages")
    else:
        b.check_quota.return_value = None
    return b


def _make_memory():
    m = AsyncMock()
    m.get_session_history.return_value = []
    m.search.return_value = {"episodes": [], "facts": []}
    m.add_to_session.return_value = None
    return m


def _make_policy(risk_level="wellbeing", blocked=False, crisis_response=None):
    from mirror.core.policy.models import PolicyResult, RiskLevel
    p = AsyncMock()
    p.check.return_value = PolicyResult(
        risk_level=RiskLevel(risk_level),
        sales_allowed=(risk_level == "wellbeing"),
        blocked=blocked,
        crisis_response=crisis_response,
        referral_hint=None,
    )
    return p


def _make_intent(intent="chat", confidence=0.9):
    from mirror.services.dialog_state import IntentResult
    r = AsyncMock()
    r.classify.return_value = IntentResult(intent=intent, confidence=confidence)
    return r


def _make_llm(response="Ответ от LLM"):
    r = MagicMock()
    r.call = AsyncMock(return_value=response)
    r.complete = AsyncMock(return_value=response)
    return r


def _build_graph(intent_router=None, policy=None, memory=None, llm=None):
    from mirror.services.dialog_graph import build_dialog_graph
    return build_dialog_graph(
        intent_router=intent_router or _make_intent(),
        policy_engine=policy or _make_policy(),
        memory_service=memory or _make_memory(),
        llm_router=llm or _make_llm(),
    )


# ── IntentRouter ──────────────────────────────────────────────────────────

async def test_intent_tarot():
    llm = _make_llm(response='{"intent": "tarot", "confidence": 0.95}')
    from mirror.services.intent_router import IntentRouter
    router = IntentRouter(llm_router=llm)
    result = await router.classify("покажи мне таро")
    assert result.intent == "tarot"


async def test_intent_astrology():
    llm = _make_llm(response='{"intent": "astrology", "confidence": 0.9}')
    from mirror.services.intent_router import IntentRouter
    router = IntentRouter(llm_router=llm)
    result = await router.classify("расскажи про мою натальную карту")
    assert result.intent == "astrology"


async def test_intent_low_confidence_falls_back_to_chat():
    llm = _make_llm(response='{"intent": "tarot", "confidence": 0.3}')
    from mirror.services.intent_router import IntentRouter
    router = IntentRouter(llm_router=llm)
    result = await router.classify("привет")
    assert result.intent == "chat"


async def test_intent_llm_error_falls_back_to_chat():
    llm = AsyncMock()
    llm.call.side_effect = Exception("LLM down")
    from mirror.services.intent_router import IntentRouter
    router = IntentRouter(llm_router=llm)
    result = await router.classify("что-то")
    assert result.intent == "chat"


# ── LangGraph: crisis blocked ─────────────────────────────────────────────

async def test_graph_crisis_blocks_generate():
    intent_router = _make_intent(intent="chat")
    policy = _make_policy(risk_level="crisis", blocked=True, crisis_response="Кризисный ответ 8-800-2000-122")
    memory = _make_memory()
    llm = _make_llm()

    graph = _build_graph(intent_router=intent_router, policy=policy, memory=memory, llm=llm)
    state = {
        "user_id": str(uuid4()), "session_id": str(uuid4()),
        "message": "не хочу жить", "tier": "free",
        "intent": None, "intent_conf": None,
        "risk_level": None, "sales_allowed": True, "blocked": False, "crisis_response": None,
        "session_history": [], "memory_context": {"episodes": [], "facts": []},
        "response": None, "mode_used": None,
    }
    result = await graph.ainvoke(state)

    assert result["blocked"] is True
    assert result["response"] == "Кризисный ответ 8-800-2000-122"
    llm.call.assert_not_awaited()  # LLM не вызывался


# ── LangGraph: intent routing ─────────────────────────────────────────────

async def test_graph_chat_calls_llm():
    llm = _make_llm("Хороший ответ")
    graph = _build_graph(intent_router=_make_intent("chat"), llm=llm)
    state = {
        "user_id": str(uuid4()), "session_id": str(uuid4()),
        "message": "привет", "tier": "free",
        "intent": None, "intent_conf": None,
        "risk_level": None, "sales_allowed": True, "blocked": False, "crisis_response": None,
        "session_history": [], "memory_context": {"episodes": [], "facts": []},
        "response": None, "mode_used": None,
    }
    result = await graph.ainvoke(state)
    assert result["response"] == "Хороший ответ"
    assert result["mode_used"] == "chat"
    llm.call.assert_awaited_once()


async def test_graph_help_static():
    graph = _build_graph(intent_router=_make_intent("help"))
    state = {
        "user_id": str(uuid4()), "session_id": str(uuid4()),
        "message": "/help", "tier": "free",
        "intent": None, "intent_conf": None,
        "risk_level": None, "sales_allowed": True, "blocked": False, "crisis_response": None,
        "session_history": [], "memory_context": {"episodes": [], "facts": []},
        "response": None, "mode_used": None,
    }
    result = await graph.ainvoke(state)
    assert "Таро" in result["response"]


# ── DialogService ─────────────────────────────────────────────────────────

async def test_dialog_service_quota_exceeded():
    billing = _make_billing(allowed=False)
    svc = _make_dialog_service(billing=billing)
    resp = await svc.handle(_make_msg())
    assert "лимит" in resp.text.lower()


async def test_dialog_service_normal():
    llm = _make_llm("Привет! Рада тебя видеть.")
    svc = _make_dialog_service(llm=llm)
    resp = await svc.handle(_make_msg("привет"))
    assert resp.text == "Привет! Рада тебя видеть."
    assert resp.channel == "telegram"


async def test_dialog_service_graph_exception_returns_fallback():
    billing = _make_billing()
    memory = _make_memory()
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = Exception("graph crashed")

    from mirror.services.dialog import DialogService
    svc = DialogService(graph=mock_graph, memory_service=memory, billing_service=billing)
    resp = await svc.handle(_make_msg("привет"))
    assert "занята" in resp.text.lower() or "попробуй" in resp.text.lower()


async def test_dialog_service_saves_to_session():
    memory = _make_memory()
    svc = _make_dialog_service(memory=memory, llm=_make_llm("ответ"))
    await svc.handle(_make_msg("текст"))
    assert memory.add_to_session.await_count == 2  # user + assistant


def _make_dialog_service(billing=None, memory=None, llm=None):
    from mirror.services.dialog import DialogService
    from mirror.services.dialog_graph import build_dialog_graph
    _memory = memory or _make_memory()
    graph = build_dialog_graph(
        intent_router=_make_intent(),
        policy_engine=_make_policy(),
        memory_service=_memory,
        llm_router=llm or _make_llm(),
    )
    return DialogService(
        graph=graph,
        memory_service=_memory,
        billing_service=billing or _make_billing(),
    )
