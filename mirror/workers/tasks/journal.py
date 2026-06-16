"""Celery tasks for journal: evening reflection polling, monthly synthesis."""
import asyncio
from datetime import date, datetime, time, timezone
from uuid import UUID

import structlog

from mirror.workers.celery_app import celery_app

logger = structlog.get_logger()


def _get_services():
    import redis.asyncio as aioredis
    from mirror.config import settings
    from mirror.core.llm.router import LLMRouter
    from mirror.core.memory.service import MemoryService
    from mirror.services.journal import JournalService
    llm = LLMRouter()
    redis_client = aioredis.from_url(settings.redis_url)
    memory = MemoryService(redis_client=redis_client, llm_router=llm)
    journal = JournalService(llm_router=llm, memory_service=memory, redis_client=redis_client)
    return journal, redis_client


@celery_app.task(name="mirror.workers.tasks.journal.check_evening_reflections")
def check_evening_reflections():
    asyncio.run(_dispatch_evening_reflections())


@celery_app.task(name="mirror.workers.tasks.journal.send_evening_reflection")
def send_evening_reflection(user_id_str: str):
    asyncio.run(_do_evening_reflection(user_id_str))


@celery_app.task(name="mirror.workers.tasks.journal.generate_monthly_synthesis")
def generate_monthly_synthesis():
    asyncio.run(_dispatch_monthly_synthesis())


async def _dispatch_evening_reflections() -> None:
    import zoneinfo
    from sqlalchemy import select
    from mirror.db.session import ensure_db_pool, get_session
    from mirror.models.user import UserProfile

    await ensure_db_pool()
    async with get_session() as session:
        rows = await session.execute(
            select(UserProfile.user_id, UserProfile.timezone, UserProfile.journal_evening_time)
            .where(UserProfile.journal_notifications_enabled.is_(True))
        )
        users = rows.all()

    for user_id, tz_name, evening_time in users:
        try:
            tz = zoneinfo.ZoneInfo(tz_name or "Europe/Moscow")
            local_now = datetime.now(tz)
            target = evening_time or time(21, 0)
            local_time = local_now.time().replace(second=0, microsecond=0)
            delta_minutes = abs(
                (local_time.hour * 60 + local_time.minute)
                - (target.hour * 60 + target.minute)
            )
            if delta_minutes <= 7:
                send_evening_reflection.delay(str(user_id))
        except Exception:
            logger.warning("journal.reflection_dispatch_failed", user_id=str(user_id))


async def _do_evening_reflection(user_id_str: str) -> None:
    from mirror.db.session import ensure_db_pool, get_session
    from mirror.models.user import ChannelIdentity

    await ensure_db_pool()
    user_id = UUID(user_id_str)

    # Idempotency: do not send twice on same day
    import redis.asyncio as aioredis
    from mirror.config import settings
    redis_client = aioredis.from_url(settings.redis_url)
    sent_key = f"journal:evening_sent:{user_id}:{date.today().isoformat()}"
    if await redis_client.exists(sent_key):
        return

    journal, _ = _get_services()
    question = await journal.evening_reflection_prompt(user_id)

    await _deliver_to_user(user_id, question)

    await redis_client.setex(sent_key, 86400, "1")
    logger.info("journal.evening_reflection_sent", user_id=user_id_str)


async def _dispatch_monthly_synthesis() -> None:
    from sqlalchemy import select
    from mirror.db.session import ensure_db_pool, get_session
    from mirror.models.user import UserProfile

    await ensure_db_pool()
    now = datetime.now(timezone.utc)
    # Run for previous month
    month = now.month - 1 or 12
    year = now.year if now.month > 1 else now.year - 1

    async with get_session() as session:
        rows = await session.execute(select(UserProfile.user_id))
        user_ids = [r[0] for r in rows.all()]

    journal, _ = _get_services()
    for user_id in user_ids:
        try:
            await journal.monthly_synthesis(user_id, month, year)
        except Exception:
            logger.warning("journal.monthly_synthesis_failed", user_id=str(user_id))


async def _deliver_to_user(user_id: UUID, text: str) -> None:
    from sqlalchemy import select
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

    bot_token = await _get_bot_token()
    if not bot_token:
        return

    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={"chat_id": int(identity.channel_user_id), "text": text})


async def _get_bot_token() -> str | None:
    """Returns the first available bot token (single-bot deployments)."""
    from sqlalchemy import select
    from mirror.db.session import get_session
    from mirror.models.telegram import TgBot

    try:
        async with get_session() as session:
            result = await session.execute(select(TgBot.token).limit(1))
            return result.scalar_one_or_none()
    except Exception:
        return None
