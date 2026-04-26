import asyncio
import time
from uuid import UUID

import structlog
from sqlalchemy import select

import mirror.db.session as db_module
from mirror.channels.base import UnifiedMessage, UnifiedResponse
from mirror.core.llm.router import sanitize_input
from mirror.core.memory.session import SESSION_IDLE_SECONDS, get_session_meta, set_session_meta

logger = structlog.get_logger()

_app_config_cache: dict[str, str] = {}


async def load_app_config_cache() -> None:
    from sqlalchemy import text
    async with db_module.async_session_factory() as session:
        try:
            result = await session.execute(text("SELECT key, value FROM app_config"))
            _app_config_cache.update({row[0]: row[1] for row in result.fetchall()})
            logger.info("dialog.app_config_loaded", count=len(_app_config_cache))
        except Exception:
            logger.warning("dialog.app_config_load_failed")


def get_app_config(key: str, default: str = "") -> str:
    return _app_config_cache.get(key, default)


def invalidate_app_config_cache() -> None:
    _app_config_cache.clear()


def build_system_prompt(
    facts: list[dict],
    tier: str,
    sales_allowed: bool,
    is_first_message: bool = False,
    is_returning_user: bool = False,
    psych_profile: dict | None = None,
) -> str:
    if is_first_message and not is_returning_user:
        return get_app_config(
            "onboarding_message",
            "Ты Mirror — тёплый AI-компаньон. Это первое сообщение пользователя. "
            "Поприветствуй тепло, кратко расскажи чем можешь помочь и спроси как его зовут.",
        )
    base = get_app_config(
        "system_prompt_base",
        "Ты Mirror — тёплый, внимательный AI-компаньон для самопознания. "
        "Помогаешь через астрологию, таро и глубокие разговоры. "
        "Говори тепло, лично, как близкий друг. Не осуждай. Задавай вдумчивые вопросы.",
    )
    parts = [base]
    if is_returning_user:
        parts.append(
            get_app_config(
                "returning_user_prompt",
                "Пользователь возвращается после перерыва. Поприветствуй его тепло — "
                "покажи что помнишь, упомяни что-то конкретное из того что знаешь о нём "
                "(из раздела «Что я знаю о тебе» ниже). Не делай вид что видишь его впервые.",
            )
        )

    # Psychological portrait — shapes tone and approach
    if psych_profile:
        portrait_lines = []
        if psych_profile.get("profile_summary"):
            portrait_lines.append(psych_profile["profile_summary"])
        if psych_profile.get("mbti_type"):
            portrait_lines.append(f"Тип личности (MBTI): {psych_profile['mbti_type']}")
        if psych_profile.get("attachment_style"):
            portrait_lines.append(f"Стиль привязанности: {psych_profile['attachment_style']}")
        if psych_profile.get("communication_style"):
            portrait_lines.append(f"Стиль общения: {psych_profile['communication_style']}")
        if psych_profile.get("dominant_themes"):
            portrait_lines.append(f"Ключевые темы: {', '.join(psych_profile['dominant_themes'])}")
        if portrait_lines:
            parts.append("Психологический портрет пользователя (используй для персонализации тона и подхода):\n" + "\n".join(portrait_lines))

    if facts:
        facts_text = "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:20])
        parts.append(f"Что я знаю о тебе:\n{facts_text}")
    if sales_allowed and tier == "free":
        parts.append("Если уместно, можешь мягко упомянуть что есть расширенные возможности.")
    return "\n\n".join(parts)


def build_messages(state) -> list[dict]:
    system = build_system_prompt(
        facts=state["memory_context"].get("facts", []),
        tier=state["tier"],
        sales_allowed=state["sales_allowed"],
        is_first_message=state.get("is_first_message", False),
        is_returning_user=state.get("is_returning_user", False),
        psych_profile=state.get("psych_profile") or {},
    )
    history = list(state["session_history"])[-10:]

    context_blocks = []
    episodes = state["memory_context"].get("episodes", [])
    if episodes:
        episodes_text = "\n".join(ep.get("summary", "") for ep in episodes if ep.get("summary"))
        if episodes_text:
            context_blocks.append(f"Контекст прошлых сессий:\n{episodes_text}")

    psych_chunks = state.get("psych_chunks") or []
    if psych_chunks:
        chunks_text = "\n---\n".join(psych_chunks[:3])
        context_blocks.append(f"Релевантные психологические знания (используй как ориентир, не цитируй дословно):\n{chunks_text}")

    if context_blocks:
        history = [{"role": "system", "content": "\n\n".join(context_blocks)}] + history

    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": sanitize_input(state["message"])},
    ]


class DialogService:
    def __init__(self, graph, memory_service, billing_service) -> None:
        self._graph = graph
        self._memory = memory_service
        self._billing = billing_service

    async def handle(self, msg: UnifiedMessage) -> UnifiedResponse:
        t0 = time.monotonic()
        uid = UUID(msg.global_user_id)

        tier = await self._billing.get_tier(uid) or "free"
        try:
            await self._billing.check_quota(uid, tier, "messages")
        except Exception as e:
            from mirror.services.billing import QuotaExceededError
            if isinstance(e, QuotaExceededError):
                return UnifiedResponse(
                    text="Дневной лимит исчерпан. Приходи завтра 💫",
                    chat_id=msg.chat_id,
                    channel=msg.channel,
                )
            raise

        initial_state = {
            "user_id": msg.global_user_id,
            "session_id": msg.session_id,
            "message": msg.text,
            "tier": tier,
            "is_first_message": msg.is_first_message,
            "is_returning_user": False,
            "intent": None,
            "intent_conf": None,
            "risk_level": None,
            "sales_allowed": True,
            "blocked": False,
            "crisis_response": None,
            "referral_hint": None,
            "session_history": [],
            "memory_context": {"episodes": [], "facts": []},
            "psych_chunks": [],
            "psych_profile": {},
            "response": None,
            "mode_used": None,
        }

        try:
            final_state = await self._graph.ainvoke(initial_state)
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception:
            logger.exception("dialog.graph_error", user_id=msg.global_user_id)
            await self._log_intent(uid, "chat", tier)
            return UnifiedResponse(
                text="Сейчас немного занята, вернусь через минуту ✨",
                chat_id=msg.chat_id,
                channel=msg.channel,
            )

        response_text = final_state.get("response") or "Сейчас немного занята, вернусь через минуту ✨"

        await self._memory.add_to_session(uid, "user", msg.text)
        await self._memory.add_to_session(uid, "assistant", response_text)
        await self._maybe_close_session(uid, msg.global_user_id, msg.session_id)
        await self._log_intent(uid, final_state.get("intent") or "chat", tier)

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "dialog.handled",
            user_id=msg.global_user_id,
            intent=final_state.get("intent"),
            mode=final_state.get("mode_used"),
            latency_ms=latency_ms,
        )

        return UnifiedResponse(
            text=response_text,
            chat_id=msg.chat_id,
            channel=msg.channel,
        )

    async def _log_intent(self, uid: UUID, intent: str, tier: str) -> None:
        try:
            from mirror.models.intent_log import IntentLog
            async with db_module.async_session_factory() as session:
                session.add(IntentLog(user_id=uid, intent=intent, tier=tier))
                await session.commit()
        except Exception:
            logger.warning("dialog.intent_log_failed", user_id=str(uid))

    async def _maybe_close_session(self, uid: UUID, user_id_str: str, current_session_id: str) -> None:
        from mirror.events.publishers.dialog import publish_session_closed
        try:
            meta = await get_session_meta(self._memory._redis, uid)
            now = time.time()
            if meta and meta["session_id"] != current_session_id:
                gap = now - meta["last_active_at"]
                if gap >= SESSION_IDLE_SECONDS:
                    await publish_session_closed(user_id_str, meta["session_id"])
                    logger.info(
                        "dialog.session_closed",
                        user_id=user_id_str,
                        session_id=meta["session_id"],
                        gap_hours=round(gap / 3600, 1),
                    )
            await set_session_meta(self._memory._redis, uid, current_session_id)
        except Exception:
            logger.warning("dialog.session_meta_failed", user_id=user_id_str)
