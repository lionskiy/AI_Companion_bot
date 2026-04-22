from uuid import UUID

import structlog
from langgraph.graph import END, StateGraph

from mirror.services.dialog_state import DialogState

logger = structlog.get_logger()

HELP_TEXT = """Я умею:
🔮 Таро — расклады и интерпретации
⭐ Астрология — натальная карта и транзиты
🌅 Ежедневный ритуал — карта дня и аффирмация
💬 Просто поговорить

Напиши что тебя интересует."""

CHAT_TASK_KIND: dict[str, str] = {
    "free": "main_chat",
    "basic": "main_chat",
    "plus": "main_chat_premium",
    "pro": "main_chat_premium",
}


def build_dialog_graph(
    intent_router,
    policy_engine,
    memory_service,
    llm_router,
    astrology_service=None,
    tarot_service=None,
    daily_ritual_service=None,
):
    async def classify_intent_node(state: DialogState) -> dict:
        if state.get("is_first_message"):
            return {"intent": "onboarding", "intent_conf": 1.0}
        result = await intent_router.classify(state["message"])
        logger.info("dialog.intent", user_id=state["user_id"], intent=result.intent)
        return {"intent": result.intent, "intent_conf": result.confidence}

    async def check_policy_node(state: DialogState) -> dict:
        result = await policy_engine.check(
            user_id=UUID(state["user_id"]),
            text_=state["message"],
            session_id=UUID(state["session_id"]) if state["session_id"] else None,
        )
        updates: dict = {
            "risk_level": result.risk_level.value,
            "sales_allowed": result.sales_allowed,
            "blocked": result.blocked,
            "crisis_response": result.crisis_response,
            "referral_hint": result.referral_hint,
        }
        if result.blocked:
            updates["response"] = result.crisis_response
        return updates

    async def route_mode_node(state: DialogState) -> dict:
        import asyncio
        from mirror.rag.psych import search_psych_knowledge

        uid = UUID(state["user_id"])

        # Build profile context string for personalized RAG query
        psych_profile = await _load_psych_profile(uid)
        profile_ctx = _profile_context_str(psych_profile)

        session_history, memory_context, psych_chunks = await asyncio.gather(
            memory_service.get_session_history(uid),
            memory_service.search(uid, state["message"]),
            search_psych_knowledge(state["message"], llm_router, profile_context=profile_ctx),
        )
        return {
            "session_history": session_history,
            "memory_context": memory_context,
            "psych_chunks": psych_chunks,
            "psych_profile": psych_profile,
        }

    async def generate_response_node(state: DialogState) -> dict:
        intent = state.get("intent") or "chat"

        if intent == "onboarding":
            response = await _chat_response(state, llm_router)
        elif intent == "astrology" and astrology_service is not None:
            response = await astrology_service.handle(state)
        elif intent == "tarot" and tarot_service is not None:
            response = await tarot_service.handle(state)
        elif intent == "daily_ritual" and daily_ritual_service is not None:
            response = await daily_ritual_service.handle(state)
        elif intent == "help":
            response = HELP_TEXT
        elif intent == "cancel":
            response = "Хорошо, давай поговорим о чём-нибудь другом."
        else:
            response = await _chat_response(state, llm_router)

        if state.get("risk_level") == "referral_hint" and state.get("referral_hint"):
            response += f"\n\n{state['referral_hint']}"

        return {"response": response, "mode_used": intent}

    graph = StateGraph(DialogState)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("check_policy", check_policy_node)
    graph.add_node("route_mode", route_mode_node)
    graph.add_node("generate_response", generate_response_node)

    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "check_policy")
    graph.add_conditional_edges(
        "check_policy",
        lambda s: "end" if s["blocked"] else "route_mode",
        {"end": END, "route_mode": "route_mode"},
    )
    graph.add_edge("route_mode", "generate_response")
    graph.add_edge("generate_response", END)

    return graph.compile()


async def _load_psych_profile(uid) -> dict:
    try:
        from sqlalchemy import select
        import mirror.db.session as db_module
        from mirror.models.user import UserProfile
        async with db_module.async_session_factory() as session:
            result = await session.execute(select(UserProfile).where(UserProfile.user_id == uid))
            p = result.scalar_one_or_none()
        if p is None:
            return {}
        return {
            "mbti_type": p.mbti_type,
            "attachment_style": p.attachment_style,
            "communication_style": p.communication_style,
            "dominant_themes": p.dominant_themes or [],
            "profile_summary": p.profile_summary,
        }
    except Exception:
        return {}


def _profile_context_str(profile: dict) -> str:
    parts = []
    if profile.get("mbti_type"):
        parts.append(f"MBTI: {profile['mbti_type']}")
    if profile.get("attachment_style"):
        parts.append(f"стиль привязанности: {profile['attachment_style']}")
    if profile.get("communication_style"):
        parts.append(f"стиль общения: {profile['communication_style']}")
    if profile.get("dominant_themes"):
        parts.append(f"темы: {', '.join(profile['dominant_themes'])}")
    if profile.get("profile_summary"):
        parts.append(profile["profile_summary"])
    return "; ".join(parts)


async def _chat_response(state: DialogState, llm_router) -> str:
    from mirror.services.dialog import build_messages
    task_kind = CHAT_TASK_KIND.get(state["tier"], "main_chat")
    messages = build_messages(state)
    return await llm_router.call(
        task_kind=task_kind,
        messages=messages,
        tier=state["tier"],
    )
