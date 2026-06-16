"""ProactiveOrchestrator — selects and sends best proactive candidate."""
import json
from datetime import date, datetime, time
from uuid import UUID

import structlog

from mirror.services.proactive.candidates import (
    ProactiveCandidate,
    apply_streak_penalty,
    get_ignored_streak,
    score_astro_event,
    score_emotional_checkin,
    score_topic_continuation,
)
from mirror.services.proactive.helpers import _deliver_to_user, _log_proactive

logger = structlog.get_logger()


def _get_redis():
    import mirror.dependencies as deps
    return deps.redis_client


class ProactiveOrchestrator:
    def __init__(self, llm_router, memory_service, astrology_service=None) -> None:
        self._llm = llm_router
        self._memory = memory_service
        self._astrology = astrology_service

    async def process_user(self, user) -> None:
        redis = _get_redis()

        if not await self._in_active_hours(user):
            return
        if await self._daily_limit_reached(user.user_id, redis):
            return

        from mirror.services.dialog import get_app_config
        threshold = float(get_app_config("proactive_score_threshold", "0.5"))

        candidates = await self._build_candidates(user.user_id)
        if not candidates:
            return

        streak = await get_ignored_streak(user.user_id)
        candidates = [apply_streak_penalty(c, streak) for c in candidates]
        # Filter out candidates blocked by cooldown after penalty
        active = [c for c in candidates if c.score > 0]
        if not active:
            return

        best = max(active, key=lambda c: c.score)
        if best.score >= threshold:
            await self._send(user.user_id, best, redis)

    async def _in_active_hours(self, user) -> bool:
        import zoneinfo
        try:
            tz = zoneinfo.ZoneInfo(user.timezone or "Europe/Moscow")
            local_now = datetime.now(tz).time()
            start = user.quiet_hours_start or time(23, 0)
            end = user.quiet_hours_end or time(8, 0)
            if start > end:
                return not (local_now >= start or local_now < end)
            return not (start <= local_now < end)
        except Exception:
            return True

    async def _daily_limit_reached(self, user_id: UUID, redis) -> bool:
        from mirror.services.dialog import get_app_config
        count_key = f"proactive:daily_count:{user_id}:{date.today().isoformat()}"
        count = int(await redis.get(count_key) or 0)
        limit = int(get_app_config("proactive_daily_limit", "2"))
        return count >= limit

    async def _build_candidates(self, user_id: UUID) -> list[ProactiveCandidate]:
        candidates: list[ProactiveCandidate] = []
        candidates += await score_emotional_checkin(user_id)
        candidates += await score_topic_continuation(user_id)
        candidates += await score_astro_event(user_id, self._astrology)
        return [c for c in candidates if c.score > 0]

    async def _send(self, user_id: UUID, candidate: ProactiveCandidate, redis) -> None:
        text = await self._compose(user_id, candidate)
        await _deliver_to_user(user_id, text)

        count_key = f"proactive:daily_count:{user_id}:{date.today().isoformat()}"
        await redis.incr(count_key)
        await redis.expire(count_key, 86400)

        cooldown_key = f"proactive:last_sent:{user_id}:{candidate.type}"
        await redis.setex(cooldown_key, candidate.cooldown_hours * 3600, datetime.utcnow().isoformat())

        await _log_proactive(user_id, candidate.type, candidate.score)
        logger.info("proactive.sent", user_id=str(user_id), type=candidate.type, score=candidate.score)

    async def _compose(self, user_id: UUID, candidate: ProactiveCandidate) -> str:
        memory = await self._memory.search(user_id, query=candidate.type, top_k=3)
        facts_snippet = [f["value"] for f in memory.get("facts", [])[:3]]
        return await self._llm.call(
            task_kind="proactive_compose",
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "type": candidate.type,
                    "context": candidate.context,
                    "memory_facts": facts_snippet,
                }, ensure_ascii=False),
            }],
        )


async def _maybe_increment_ignored_streak(user_id: UUID, candidate_type: str) -> None:
    redis = _get_redis()
    last_sent = await redis.get(f"proactive:last_sent:{user_id}:{candidate_type}")
    if not last_sent:
        return
    sent_at = datetime.fromisoformat(last_sent)
    if (datetime.utcnow() - sent_at).total_seconds() < 86400:
        return
    last_reply = await redis.get(f"user:last_message_time:{user_id}")
    if last_reply:
        reply_at = datetime.fromisoformat(last_reply)
        if reply_at > sent_at:
            return
    streak_key = f"proactive:ignored_streak:{user_id}"
    await redis.incr(streak_key)
    await redis.expire(streak_key, 604800)
    logger.info("proactive.ignored", user_id=str(user_id), type=candidate_type)


async def _update_ignored_streak(user_id: UUID) -> None:
    redis = _get_redis()
    streak_key = f"proactive:ignored_streak:{user_id}"
    await redis.delete(streak_key)
