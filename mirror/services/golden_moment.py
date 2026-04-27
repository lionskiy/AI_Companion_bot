"""GoldenMomentService — personalized insight shown once after sufficient data accumulates."""
import json
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select, update

import mirror.db.session as db_module
from mirror.models.memory import MemoryEpisode, MemoryFact
from mirror.models.user import UserProfile

logger = structlog.get_logger()


class GoldenMomentService:
    def __init__(self, redis_client, llm_router) -> None:
        self._redis = redis_client
        self._llm = llm_router

    async def compute_readiness_score(self, user_id: UUID) -> float:
        cache_key = f"golden_moment:score:{user_id}"
        cached = await self._redis.get(cache_key)
        if cached:
            return float(cached)

        try:
            async with db_module.async_session_factory() as s:
                active_days = await s.scalar(
                    select(func.count(func.distinct(func.date(MemoryEpisode.created_at))))
                    .where(MemoryEpisode.user_id == user_id)
                ) or 0
                episodes_count = await s.scalar(
                    select(func.count()).select_from(MemoryEpisode)
                    .where(MemoryEpisode.user_id == user_id)
                ) or 0
                facts_count = await s.scalar(
                    select(func.count()).select_from(MemoryFact)
                    .where(MemoryFact.user_id == user_id, MemoryFact.deleted_at.is_(None))
                ) or 0
        except Exception:
            logger.warning("golden_moment.score_compute_failed", user_id=str(user_id))
            return 0.0

        score = (
            min(active_days, 14) / 14 * 0.3
            + min(episodes_count, 10) / 10 * 0.3
            + min(facts_count, 10) / 10 * 0.4
        )
        score = round(score, 3)
        await self._redis.setex(cache_key, 3600, str(score))
        return score

    async def check_and_trigger(self, user_id: UUID, state: dict) -> bool:
        if state.get("is_first_message"):
            return False
        if state.get("risk_level") in ("crisis", "risk_signal"):
            return False

        try:
            async with db_module.async_session_factory() as session:
                row = await session.execute(
                    select(
                        UserProfile.golden_moment_pending,
                        UserProfile.golden_moment_shown_at,
                        UserProfile.registered_at,
                    ).where(UserProfile.user_id == user_id)
                )
                profile = row.first()
        except Exception:
            logger.warning("golden_moment.profile_load_failed", user_id=str(user_id))
            return False

        if profile is None:
            return False
        if profile.golden_moment_shown_at is not None:
            return False
        if profile.golden_moment_pending:
            return True

        from mirror.services.dialog import get_app_config
        threshold = float(get_app_config("golden_moment_threshold", "0.6"))
        t_max_days = int(get_app_config("golden_moment_t_max_days", "12"))

        score = await self.compute_readiness_score(user_id)
        now = datetime.now(timezone.utc)
        registered_at = profile.registered_at or now
        days_since_registration = (now - registered_at).days

        should_trigger = score >= threshold or days_since_registration >= t_max_days

        if should_trigger:
            try:
                async with db_module.async_session_factory() as session:
                    await session.execute(
                        update(UserProfile)
                        .where(UserProfile.user_id == user_id)
                        .where(UserProfile.golden_moment_pending.is_(False))
                        .values(golden_moment_pending=True)
                    )
                    await session.commit()
                logger.info(
                    "golden_moment.triggered",
                    user_id=str(user_id),
                    score=score,
                    days=days_since_registration,
                )
                return True
            except Exception:
                logger.warning("golden_moment.trigger_failed", user_id=str(user_id))

        return False

    async def build_insight(self, user_id: UUID) -> str:
        async with db_module.async_session_factory() as session:
            psych_row = await session.execute(
                select(
                    UserProfile.profile_summary,
                    UserProfile.mbti_type,
                    UserProfile.attachment_style,
                    UserProfile.dominant_themes,
                ).where(UserProfile.user_id == user_id)
            )
            psych = psych_row.first()

            facts_rows = await session.execute(
                select(MemoryFact.key, MemoryFact.value)
                .where(MemoryFact.user_id == user_id, MemoryFact.deleted_at.is_(None))
                .order_by(MemoryFact.importance.desc())
                .limit(20)
            )
            facts = [{"key": r.key, "value": r.value} for r in facts_rows.all()]

            episodes_rows = await session.execute(
                select(MemoryEpisode.summary)
                .where(MemoryEpisode.user_id == user_id)
                .order_by(MemoryEpisode.created_at.desc())
                .limit(3)
            )
            episodes = [r.summary for r in episodes_rows.all() if r.summary]

        psych_data = {}
        if psych:
            psych_data = {
                "profile_summary": psych.profile_summary,
                "mbti_type": psych.mbti_type,
                "attachment_style": psych.attachment_style,
                "dominant_themes": psych.dominant_themes or [],
            }

        return await self._llm.call(
            task_kind="golden_moment",
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "psych_profile": psych_data,
                    "facts": facts,
                    "recent_episodes": episodes,
                }, ensure_ascii=False),
            }],
        )

    async def mark_shown(self, user_id: UUID) -> bool:
        try:
            async with db_module.async_session_factory() as session:
                result = await session.execute(
                    update(UserProfile)
                    .where(UserProfile.user_id == user_id)
                    .where(UserProfile.golden_moment_shown_at.is_(None))
                    .values(golden_moment_shown_at=datetime.now(timezone.utc))
                    .returning(UserProfile.user_id)
                )
                await session.commit()
                updated = result.fetchone()
            if updated:
                logger.info("golden_moment.shown", user_id=str(user_id))
                return True
        except Exception:
            logger.warning("golden_moment.mark_shown_failed", user_id=str(user_id))
        return False

    async def is_pending(self, user_id: UUID) -> bool:
        try:
            async with db_module.async_session_factory() as session:
                result = await session.execute(
                    select(UserProfile.golden_moment_pending, UserProfile.golden_moment_shown_at)
                    .where(UserProfile.user_id == user_id)
                )
                row = result.first()
            return bool(row and row.golden_moment_pending and row.golden_moment_shown_at is None)
        except Exception:
            return False
