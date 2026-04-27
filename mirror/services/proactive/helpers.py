"""Shared helper functions for the proactive module."""
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import func, insert, select

logger = structlog.get_logger()


def _get_redis():
    import mirror.dependencies as deps
    return deps.redis_client


async def _get_last_user_message_time(user_id: UUID) -> datetime | None:
    redis = _get_redis()
    cached = await redis.get(f"user:last_message_time:{user_id}")
    if cached:
        return datetime.fromisoformat(cached)
    from mirror.db.session import get_session
    from mirror.models.memory import MemoryEpisode
    async with get_session() as session:
        row = await session.execute(
            select(func.max(MemoryEpisode.created_at)).where(MemoryEpisode.user_id == user_id)
        )
        return row.scalar()


async def _get_last_episode(user_id: UUID, exclude_source_modes: list[str]):
    from mirror.db.session import get_session
    from mirror.models.memory import MemoryEpisode
    async with get_session() as session:
        row = await session.execute(
            select(MemoryEpisode)
            .where(MemoryEpisode.user_id == user_id)
            .where(MemoryEpisode.source_mode.notin_(exclude_source_modes))
            .order_by(MemoryEpisode.created_at.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


async def _user_has_natal_chart(user_id: UUID) -> bool:
    from mirror.db.session import get_session
    from mirror.models.user import UserProfile
    async with get_session() as session:
        row = await session.execute(
            select(UserProfile.natal_data).where(UserProfile.user_id == user_id)
        )
        return bool(row.scalar_one_or_none())


async def _get_profile(user_id: UUID):
    from mirror.db.session import get_session
    from mirror.models.user import UserProfile
    async with get_session() as session:
        return await session.get(UserProfile, user_id)


async def _get_bot_token_for_user(user_id: UUID) -> str | None:
    """Returns the first available bot token (single-bot deployments)."""
    from mirror.db.session import get_session
    from mirror.models.telegram import TgBot
    try:
        async with get_session() as session:
            row = await session.execute(select(TgBot.token).limit(1))
            result = row.scalar_one_or_none()
        return result
    except Exception:
        return None


async def _deliver_to_user(user_id: UUID, text: str) -> None:
    from mirror.db.session import get_session
    from mirror.models.user import ChannelIdentity
    async with get_session() as session:
        row = await session.execute(
            select(ChannelIdentity.channel_user_id)
            .where(ChannelIdentity.global_user_id == user_id)
            .where(ChannelIdentity.channel == "telegram")
        )
        identity = row.first()
    if not identity:
        return
    bot_token = await _get_bot_token_for_user(user_id)
    if not bot_token:
        return
    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={"chat_id": int(identity.channel_user_id), "text": text})


async def _log_proactive(user_id: UUID, proactive_type: str, score: float) -> None:
    from mirror.db.session import get_session
    from mirror.models.proactive import ProactiveLog
    try:
        async with get_session() as session:
            session.add(ProactiveLog(user_id=user_id, type=proactive_type, score=score))
            await session.commit()
    except Exception:
        logger.warning("proactive.log_failed", user_id=str(user_id))


async def _get_session_id(user_id: UUID) -> str:
    return f"{user_id}:proactive"
