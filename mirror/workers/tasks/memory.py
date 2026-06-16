import asyncio
from uuid import UUID

import structlog

from mirror.workers.celery_app import celery_app

logger = structlog.get_logger()


def _get_services():
    import redis.asyncio as aioredis
    from mirror.config import settings
    from mirror.core.llm.router import LLMRouter
    from mirror.core.memory.service import MemoryService
    llm = LLMRouter()
    redis_client = aioredis.from_url(settings.redis_url)
    return llm, MemoryService(redis_client=redis_client, llm_router=llm)


@celery_app.task(queue="default", max_retries=3, bind=True)
def summarize_episode(self, user_id: str, session_id: str) -> None:
    try:
        asyncio.run(_summarize_episode_async(user_id, session_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(queue="default", max_retries=3, bind=True)
def extract_facts(self, user_id: str, episode_id: str) -> None:
    try:
        asyncio.run(_extract_facts_async(user_id, episode_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


async def _summarize_episode_async(user_id: str, session_id: str) -> None:
    from mirror.db.session import ensure_db_pool
    await ensure_db_pool()
    llm_router, memory_service = _get_services()

    history = await memory_service.get_session_history(UUID(user_id))
    if not history:
        logger.info("memory.summarize_skip_empty", user_id=user_id, session_id=session_id)
        return

    messages = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    prompt = (
        "Сделай краткое резюме этого диалога на русском языке (2-4 предложения). "
        "Выдели главные темы, настроение пользователя и ключевые факты о нём.\n\n"
        f"{messages}"
    )
    summary = await llm_router.call(
        task_kind="memory_summarize",
        messages=[{"role": "user", "content": prompt}],
    )
    episode_id = await memory_service.write_episode(
        user_id=UUID(user_id),
        session_id=UUID(session_id),
        text_=summary,
    )
    extract_facts.delay(user_id, str(episode_id))
    logger.info("memory.episode_summarized", user_id=user_id, session_id=session_id)


async def _extract_facts_async(user_id: str, episode_id: str) -> None:
    import json
    import re
    from sqlalchemy import select

    from mirror.db.session import ensure_db_pool, get_session
    await ensure_db_pool()
    from mirror.models.memory import MemoryEpisode
    llm_router, memory_service = _get_services()

    async with get_session() as session:
        result = await session.execute(
            select(MemoryEpisode).where(MemoryEpisode.id == UUID(episode_id))
        )
        episode = result.scalar_one_or_none()

    if not episode:
        return

    prompt = (
        "Извлеки ключевые факты о пользователе из этого резюме диалога. "
        "Верни ТОЛЬКО валидный JSON массив без пояснений:\n"
        '[{"key": "...", "value": "...", "fact_type": "observed"}]\n\n'
        f"Резюме:\n{episode.summary}"
    )
    raw = await llm_router.call(
        task_kind="memory_extract_facts",
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        facts = json.loads(m.group()) if m else []
    except Exception:
        logger.warning("memory.facts_parse_failed", user_id=user_id, episode_id=episode_id)
        return

    for fact in facts:
        await memory_service.write_fact(
            user_id=UUID(user_id),
            key=fact.get("key", "unknown"),
            value=fact.get("value", ""),
            fact_type=fact.get("fact_type", "observed"),
        )
    logger.info("memory.facts_extracted", user_id=user_id, count=len(facts))

    from mirror.workers.tasks.profile import update_psych_profile
    update_psych_profile.delay(user_id)


@celery_app.task(
    name="mirror.workers.tasks.memory.decay_fact_importance",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def decay_fact_importance(self):
    try:
        asyncio.run(_decay_importance())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _decay_importance() -> None:
    from mirror.db.session import ensure_db_pool
    from sqlalchemy import text as sa_text
    from mirror.db.session import get_session
    await ensure_db_pool()
    async with get_session() as session:
        result = await session.execute(sa_text("""
            UPDATE memory_facts
            SET importance = GREATEST(0.1, importance - 0.02)
            WHERE last_accessed < NOW() - INTERVAL '30 days'
              AND importance > 0.1
              AND deleted_at IS NULL
        """))
        await session.commit()
        logger.info("memory.importance_decayed", rows=result.rowcount)
