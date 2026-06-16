"""Celery tasks for proactive messaging."""
import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import structlog

from mirror.workers.celery_app import celery_app

logger = structlog.get_logger()


def _get_redis():
    import redis.asyncio as aioredis
    from mirror.config import settings
    return aioredis.from_url(settings.redis_url)


def _get_services():
    import redis.asyncio as aioredis
    from mirror.config import settings
    from mirror.core.llm.router import LLMRouter
    from mirror.core.memory.service import MemoryService
    from mirror.services.astrology import AstrologyService
    from mirror.services.proactive.orchestrator import ProactiveOrchestrator

    redis_client = aioredis.from_url(settings.redis_url)
    llm = LLMRouter()
    memory = MemoryService(redis_client=redis_client, llm_router=llm)
    astrology = AstrologyService(llm_router=llm, redis_client=redis_client)
    return ProactiveOrchestrator(llm_router=llm, memory_service=memory, astrology_service=astrology), redis_client


@celery_app.task(
    name="mirror.workers.tasks.proactive.proactive_dispatch_batch",
    bind=True,
    max_retries=2,
    soft_time_limit=300,
)
def proactive_dispatch_batch(self, offset: int = 0, batch_size: int = 500):
    asyncio.run(_dispatch_batch(offset, batch_size))


@celery_app.task(
    name="mirror.workers.tasks.proactive.schedule_return",
    bind=True,
    max_retries=2,
)
def schedule_return(self, user_id_str: str, chat_id_str: str, original_message: str, activity: str):
    asyncio.run(_do_return(user_id_str, chat_id_str, original_message, activity))


async def _dispatch_batch(offset: int, batch_size: int) -> None:
    import mirror.dependencies as deps
    from sqlalchemy import func, select, text
    from mirror.db.session import ensure_db_pool, get_session
    from mirror.models.memory import MemoryEpisode
    from mirror.models.user import UserProfile

    await ensure_db_pool()

    orchestrator, redis_client = _get_services()
    # Wire redis into deps for helpers to use
    deps.redis_client = redis_client

    # Increment ignored streaks for all candidate types before processing
    candidate_types = ["emotional_checkin", "topic_continuation", "astro_event"]

    async with get_session() as session:
        result = await session.execute(
            select(
                UserProfile.user_id, UserProfile.timezone, UserProfile.proactive_mode,
                UserProfile.quiet_hours_start, UserProfile.quiet_hours_end,
            )
            .where(UserProfile.proactive_mode != "quiet")
            .where(UserProfile.user_id.in_(
                select(MemoryEpisode.user_id)
                .where(MemoryEpisode.created_at > func.now() - text("interval '30 days'"))
                .distinct()
            ))
            .offset(offset).limit(batch_size)
        )
        rows = result.all()

    for row in rows:
        try:
            for ctype in candidate_types:
                from mirror.services.proactive.orchestrator import _maybe_increment_ignored_streak
                await _maybe_increment_ignored_streak(row.user_id, ctype)
            await orchestrator.process_user(row)
        except Exception:
            logger.warning("proactive.process_user_failed", user_id=str(row.user_id))

    if len(rows) == batch_size:
        proactive_dispatch_batch.apply_async(kwargs={"offset": offset + batch_size, "batch_size": batch_size})


async def _do_return(user_id_str: str, chat_id_str: str, original_message: str, activity: str) -> None:
    from mirror.db.session import ensure_db_pool
    from mirror.services.proactive.helpers import _get_bot_token_for_user

    await ensure_db_pool()
    user_id = UUID(user_id_str)

    redis = _get_redis()
    pending = await redis.get(f"busy_pending:{user_id}")
    if not pending:
        return

    bot_token = await _get_bot_token_for_user(user_id)
    if not bot_token:
        return

    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={
            "chat_id": int(chat_id_str),
            "text": f"Вернулась! Была {activity} 😊",
        })

    from mirror.channels.base import UnifiedMessage
    from mirror.services.dialog import build_dialog_service_for_celery
    from mirror.services.proactive.helpers import _get_session_id

    unified = UnifiedMessage(
        message_id=str(uuid4()),
        channel="telegram",
        chat_id=chat_id_str,
        channel_user_id=chat_id_str,
        global_user_id=user_id_str,
        text=original_message,
        timestamp=datetime.utcnow(),
        is_first_message=False,
        session_id=await _get_session_id(user_id),
        metadata={"after_busy": True},
        raw_payload={},
    )
    dialog_svc = await build_dialog_service_for_celery()
    response = await dialog_svc.handle(unified)

    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={"chat_id": int(chat_id_str), "text": response.text})

    await redis.delete(f"busy_pending:{user_id}")
    logger.info("proactive.returned", user_id=user_id_str)
