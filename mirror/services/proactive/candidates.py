"""Proactive candidate scoring."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog

logger = structlog.get_logger()


@dataclass
class ProactiveCandidate:
    type: str
    score: float
    context: dict
    cooldown_hours: int


def _get_redis():
    import mirror.dependencies as deps
    return deps.redis_client


async def score_emotional_checkin(user_id: UUID) -> list[ProactiveCandidate]:
    from mirror.services.proactive.helpers import _get_last_user_message_time
    redis = _get_redis()

    last_msg = await _get_last_user_message_time(user_id)
    if last_msg is None:
        return []
    days_silent = (datetime.utcnow() - last_msg).days
    if days_silent < 2:
        return []

    score = min(0.9, 0.4 + days_silent * 0.1)
    if await redis.exists(f"proactive:last_sent:{user_id}:emotional_checkin"):
        score = max(0.0, score - 0.4)
    if score <= 0:
        return []

    return [ProactiveCandidate(
        type="emotional_checkin",
        score=score,
        context={"days_silent": days_silent},
        cooldown_hours=72,
    )]


async def score_topic_continuation(user_id: UUID) -> list[ProactiveCandidate]:
    from mirror.services.proactive.helpers import _get_last_episode
    redis = _get_redis()

    last_ep = await _get_last_episode(user_id, exclude_source_modes=["journal", "dream"])
    if not last_ep:
        return []
    days_since = (datetime.utcnow() - last_ep.created_at.replace(tzinfo=None)).days
    if days_since < 1 or days_since > 7:
        return []

    score = (last_ep.importance or 0.5) * 0.7
    if await redis.exists(f"proactive:last_sent:{user_id}:topic_continuation"):
        score = max(0.0, score - 0.3)
    if score <= 0:
        return []

    return [ProactiveCandidate(
        type="topic_continuation",
        score=score,
        context={"episode_summary": (last_ep.summary or "")[:200]},
        cooldown_hours=48,
    )]


async def score_astro_event(user_id: UUID, astrology_service=None) -> list[ProactiveCandidate]:
    from mirror.services.proactive.helpers import _user_has_natal_chart

    if astrology_service is None:
        return []
    has_natal = await _user_has_natal_chart(user_id)
    if not has_natal:
        return []
    try:
        event = await astrology_service.get_significant_transit(user_id)
        if not event:
            return []
        score = getattr(event, "significance", 0.5) * 0.8
        return [ProactiveCandidate(
            type="astro_event",
            score=score,
            context={
                "event": getattr(event, "description", ""),
                "planet": getattr(event, "planet", ""),
            },
            cooldown_hours=24,
        )]
    except Exception:
        return []


async def get_ignored_streak(user_id: UUID) -> int:
    redis = _get_redis()
    return int(await redis.get(f"proactive:ignored_streak:{user_id}") or 0)


def apply_streak_penalty(candidate: ProactiveCandidate, streak: int) -> ProactiveCandidate:
    if streak >= 6:
        candidate.cooldown_hours *= 4
    elif streak >= 3:
        candidate.cooldown_hours *= 2
    return candidate
