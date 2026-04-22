import asyncio
import json
import re
from datetime import datetime, timezone
from uuid import UUID

import structlog

from mirror.workers.celery_app import celery_app

logger = structlog.get_logger()


def _get_llm():
    from mirror.core.llm.router import LLMRouter
    return LLMRouter()


@celery_app.task(queue="default", max_retries=3, bind=True)
def update_psych_profile(self, user_id: str) -> None:
    try:
        asyncio.run(_update_psych_profile_async(user_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=120)


async def _update_psych_profile_async(user_id: str) -> None:
    from sqlalchemy import select, update
    from mirror.db.session import ensure_db_pool, get_session
    await ensure_db_pool()
    from mirror.models.memory import MemoryFact
    from mirror.models.user import UserProfile

    async with get_session() as session:
        result = await session.execute(
            select(MemoryFact).where(MemoryFact.user_id == UUID(user_id)).order_by(MemoryFact.created_at.desc()).limit(60)
        )
        facts = result.scalars().all()

    if not facts:
        return

    facts_text = "\n".join(f"- {f.key}: {f.value}" for f in facts)
    prompt = (
        "На основе известных фактов о пользователе составь его психологический портрет.\n"
        "Верни ТОЛЬКО валидный JSON без пояснений:\n"
        "{\n"
        '  "mbti_type": "INFP",\n'
        '  "attachment_style": "тревожный",\n'
        '  "communication_style": "эмоциональный, открытый",\n'
        '  "dominant_themes": ["одиночество", "поиск смысла", "отношения"],\n'
        '  "profile_summary": "Краткое описание 2-3 предложения"\n'
        "}\n\n"
        f"Факты о пользователе:\n{facts_text}"
    )

    llm = _get_llm()
    raw = await llm.call(
        task_kind="memory_extract_facts",
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group()) if m else {}
    except Exception:
        logger.warning("profile.parse_failed", user_id=user_id)
        return

    if not data:
        return

    async with get_session() as session:
        await session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == UUID(user_id))
            .values(
                mbti_type=data.get("mbti_type"),
                attachment_style=data.get("attachment_style"),
                communication_style=data.get("communication_style"),
                dominant_themes=data.get("dominant_themes"),
                profile_summary=data.get("profile_summary"),
                profile_updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    logger.info("profile.updated", user_id=user_id, mbti=data.get("mbti_type"))
