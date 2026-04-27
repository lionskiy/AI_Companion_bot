"""OnboardingManager — progressive disclosure of profile questions at the right moment."""
import re
from uuid import UUID

import structlog

from mirror.core.memory.session import SESSION_IDLE_SECONDS

logger = structlog.get_logger()

_PARTNER_RE = re.compile(r"\b(партнёр|партнер|муж|жена|парень|девушка|супруг|супруга)\b", re.IGNORECASE)

_SKIP_TTL = 5 * SESSION_IDLE_SECONDS


class OnboardingManager:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def get_pending_question(
        self,
        user_id: UUID,
        profile,
        intent: str,
        sessions_count: int,
        message_text: str = "",
    ) -> str | None:
        # preferred_name: after 3rd session or 20+ messages
        if not getattr(profile, "preferred_name", None):
            if sessions_count >= 3 and not await self._was_skipped(user_id, "preferred_name"):
                return "Кстати, как тебя называть?"

        # birth_date: when astrology or numerology intent
        if intent in ("astrology", "numerology") and not getattr(profile, "birth_date", None):
            if not await self._was_skipped(user_id, "birth_date"):
                return "Для точного расчёта мне нужна твоя дата рождения (день.месяц.год)."

        # birth_city: when astrology intent, no birth_city
        if intent == "astrology" and not getattr(profile, "birth_city", None):
            if getattr(profile, "birth_date", None) and not await self._was_skipped(user_id, "birth_city"):
                return "И ещё: город или страна рождения — для точной натальной карты."

        # partner_birth_date: mention of partner in message
        if _PARTNER_RE.search(message_text) and not getattr(profile, "partner_birth_date", None):
            if not await self._was_skipped(user_id, "partner_birth_date"):
                return "Хочешь разберём синастрию? Пришли дату рождения партнёра."

        return None

    async def save_skip(self, user_id: UUID, field: str) -> None:
        key = f"onboarding:skip:{user_id}:{field}"
        await self._redis.setex(key, _SKIP_TTL, "1")
        logger.info("onboarding.question_skipped", user_id=str(user_id), field=field)

    async def _was_skipped(self, user_id: UUID, field: str) -> bool:
        key = f"onboarding:skip:{user_id}:{field}"
        return bool(await self._redis.exists(key))
