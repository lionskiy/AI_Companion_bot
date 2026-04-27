import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
from sqlalchemy import select, text

import mirror.db.session as db_module
from mirror.config import settings
from mirror.core.memory.context_budget import ContextBudget
from mirror.core.memory.reranker import get_reranker
from mirror.core.memory.session import add_to_session, get_session_history
from mirror.models.memory import MemoryEpisode, MemoryFact

logger = structlog.get_logger()


def _get_app_config(key: str, default: str) -> str:
    """Synchronous read of app_config — used only in lazy properties, not at import time."""
    try:
        import asyncio as _asyncio
        from sqlalchemy import text as _text
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context — caller should use async version
            return default
        async def _fetch():
            async with db_module.async_session_factory() as s:
                row = await s.execute(_text("SELECT value FROM app_config WHERE key = :k"), {"k": key})
                r = row.scalar_one_or_none()
                return r if r is not None else default
        return loop.run_until_complete(_fetch())
    except Exception:
        return default


async def _get_app_config_async(key: str, default: str) -> str:
    try:
        async with db_module.async_session_factory() as s:
            row = await s.execute(text("SELECT value FROM app_config WHERE key = :k"), {"k": key})
            r = row.scalar_one_or_none()
            return r if r is not None else default
    except Exception:
        return default


class MemoryService:
    def __init__(self, redis_client, llm_router=None) -> None:
        self._redis = redis_client
        self._llm_router = llm_router
        self._budget = ContextBudget()
        # Reranker initialised lazily on first search call to avoid DB access at import
        self._reranker = None

    async def _get_reranker(self):
        if self._reranker is None:
            reranker_type = await _get_app_config_async("reranker_type", "disabled")
            self._reranker = get_reranker(reranker_type, self._llm_router)
        return self._reranker

    def _qdrant(self) -> AsyncQdrantClient:
        return AsyncQdrantClient(url=settings.qdrant_url)

    def _user_filter(self, user_id: UUID) -> Filter:
        return Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))])

    async def write_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        text_: str,
        importance: float = 0.5,
        source_mode: str = "chat",
    ) -> UUID:
        point_id = uuid4()
        embedding = await self._embed(text_)

        qdrant = self._qdrant()
        try:
            await qdrant.upsert(
                collection_name="user_episodes",
                points=[PointStruct(
                    id=str(point_id),
                    vector=embedding,
                    payload={
                        "user_id": str(user_id),
                        "session_id": str(session_id),
                        "importance": importance,
                        "source_mode": source_mode,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )],
            )
        finally:
            await qdrant.close()

        async with db_module.async_session_factory() as session:
            await _set_rls(session, user_id)
            episode = MemoryEpisode(
                user_id=user_id,
                session_id=session_id,
                summary=text_,
                qdrant_point_id=point_id,
                importance=importance,
                source_mode=source_mode,
            )
            session.add(episode)
            await session.commit()
            logger.info("memory.episode_written", user_id=str(user_id), importance=importance, source_mode=source_mode)
            return episode.id

    async def write_fact(
        self,
        user_id: UUID,
        key: str,
        value: str,
        fact_type: str = "observed",
        importance: float = 0.5,
        consent_scope: str | None = None,
    ) -> UUID:
        async with db_module.async_session_factory() as session:
            await _set_rls(session, user_id)
            result = await session.execute(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.key == key,
                    MemoryFact.deleted_at.is_(None),
                )
            )
            existing = result.scalar_one_or_none()

            point_id = uuid4()
            embedding = await self._embed(f"{key}: {value}")

            # Semantic deduplication — only when no exact key match
            if not existing:
                dedup_threshold = float(await _get_app_config_async("fact_dedup_threshold", "0.92"))
                similar = await self._search_facts_raw(user_id, embedding, top_k=5)
                for candidate in similar:
                    if candidate["score"] > dedup_threshold:
                        existing_id = candidate["id"]
                        async with db_module.async_session_factory() as s2:
                            await s2.execute(
                                text("""
                                    UPDATE memory_facts
                                    SET value = :value,
                                        importance = GREATEST(importance, :importance),
                                        updated_at = NOW()
                                    WHERE id = :id
                                """),
                                {"value": value, "importance": importance, "id": existing_id},
                            )
                            await s2.commit()
                        logger.info("memory.fact.deduplicated", user_id=str(user_id))
                        return UUID(existing_id)

            qdrant = self._qdrant()
            try:
                if existing and existing.qdrant_point_id:
                    await qdrant.delete(
                        collection_name="user_facts",
                        points_selector=[str(existing.qdrant_point_id)],
                    )
                await qdrant.upsert(
                    collection_name="user_facts",
                    points=[PointStruct(
                        id=str(point_id),
                        vector=embedding,
                        payload={
                            "user_id": str(user_id),
                            "fact_type": fact_type,
                            "key": key,
                            "value": value,
                            "importance": importance,
                            "consent_scope": consent_scope,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )],
                )
            finally:
                await qdrant.close()

            if existing:
                existing.value = value
                existing.importance = importance
                existing.version += 1
                existing.qdrant_point_id = point_id
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("memory.fact_updated", user_id=str(user_id), fact_type=fact_type)
                return existing.id
            else:
                fact = MemoryFact(
                    user_id=user_id,
                    key=key,
                    value=value,
                    fact_type=fact_type,
                    importance=importance,
                    consent_scope=consent_scope,
                    qdrant_point_id=point_id,
                )
                session.add(fact)
                await session.commit()
                logger.info("memory.fact_written", user_id=str(user_id), fact_type=fact_type)
                return fact.id

    async def search(self, user_id: UUID, query: str, top_k: int = 5) -> dict:
        embedding = await self._embed(query)

        raw_facts, raw_episodes = await asyncio.gather(
            self._search_facts_raw(user_id, embedding, top_k=15),
            self._search_episodes_raw(user_id, embedding, top_k=10),
        )

        reranker = await self._get_reranker()

        # Compute rerank scores and final_score for facts
        if raw_facts:
            fact_texts = [f"{f.get('key', '')}: {f.get('value', '')}" for f in raw_facts]
            fact_rerank = await reranker.score(query, fact_texts)
            for fact, rs in zip(raw_facts, fact_rerank):
                fact["final_score"] = fact["score"] * rs * fact.get("importance", 0.5)

        # Compute rerank scores and final_score for episodes
        if raw_episodes:
            ep_texts = [ep.get("summary", ep.get("text_", "")) for ep in raw_episodes]
            ep_rerank = await reranker.score(query, ep_texts)
            for ep, rs in zip(raw_episodes, ep_rerank):
                ep["final_score"] = ep["score"] * rs * ep.get("importance", 0.5)

        logger.info("memory.search.reranked", user_id=str(user_id), facts=len(raw_facts), episodes=len(raw_episodes))

        max_tokens = int(await _get_app_config_async("max_memory_tokens", "1500"))
        pinned_threshold = float(await _get_app_config_async("pinned_importance_threshold", "0.85"))
        result_facts, result_episodes = self._budget.fit(
            raw_facts, raw_episodes, max_tokens, pinned_threshold
        )

        if result_facts:
            logger.info("memory.context.trimmed", user_id=str(user_id), facts=len(result_facts), episodes=len(result_episodes))

        # Async update access stats — does not block response
        used_ids = [str(f["id"]) for f in result_facts if "id" in f]
        if used_ids:
            asyncio.create_task(self._update_access_stats(used_ids))

        return {"episodes": result_episodes, "facts": result_facts}

    async def get_session_history(self, user_id: UUID, max_messages: int = 20) -> list[dict]:
        return await get_session_history(self._redis, user_id, max_messages)

    async def add_to_session(self, user_id: UUID, role: str, text_: str) -> None:
        await add_to_session(self._redis, user_id, role, text_)

    async def forget(self, user_id: UUID, scope: str = "all") -> None:
        now = datetime.now(timezone.utc)
        async with db_module.async_session_factory() as session:
            await _set_rls(session, user_id)
            episodes_result = await session.execute(
                select(MemoryEpisode).where(
                    MemoryEpisode.user_id == user_id,
                    MemoryEpisode.deleted_at.is_(None),
                )
            )
            episodes = episodes_result.scalars().all()
            facts_result = await session.execute(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.deleted_at.is_(None),
                )
            )
            facts = facts_result.scalars().all()

            episode_qdrant_ids = [str(e.qdrant_point_id) for e in episodes if e.qdrant_point_id]
            fact_qdrant_ids = [str(f.qdrant_point_id) for f in facts if f.qdrant_point_id]

            qdrant = self._qdrant()
            try:
                if episode_qdrant_ids:
                    await qdrant.delete(collection_name="user_episodes", points_selector=episode_qdrant_ids)
                if fact_qdrant_ids:
                    await qdrant.delete(collection_name="user_facts", points_selector=fact_qdrant_ids)
            finally:
                await qdrant.close()

            for ep in episodes:
                ep.deleted_at = now
            for f in facts:
                f.deleted_at = now
            await session.commit()
            logger.info("memory.forgotten", user_id=str(user_id), episodes=len(episodes), facts=len(facts))

    async def _search_facts_raw(self, user_id: UUID, embedding: list[float], top_k: int = 5) -> list[dict]:
        qdrant = self._qdrant()
        try:
            response = await qdrant.query_points(
                collection_name="user_facts",
                query=embedding,
                query_filter=self._user_filter(user_id),
                limit=top_k,
                with_payload=True,
            )
        finally:
            await qdrant.close()
        return [{"id": str(r.id), "score": r.score, **r.payload} for r in response.points]

    async def _search_episodes_raw(self, user_id: UUID, embedding: list[float], top_k: int = 10) -> list[dict]:
        qdrant = self._qdrant()
        try:
            response = await qdrant.query_points(
                collection_name="user_episodes",
                query=embedding,
                query_filter=self._user_filter(user_id),
                limit=top_k,
                with_payload=True,
            )
        finally:
            await qdrant.close()
        return [{"id": str(r.id), "score": r.score, **r.payload} for r in response.points]

    async def _update_access_stats(self, fact_ids: list[str]) -> None:
        try:
            async with db_module.async_session_factory() as s:
                await s.execute(
                    text("""
                        UPDATE memory_facts
                        SET access_count = access_count + 1,
                            last_accessed = NOW(),
                            importance = LEAST(1.0, importance + 0.05)
                        WHERE id::text = ANY(:ids)
                          AND deleted_at IS NULL
                    """),
                    {"ids": fact_ids},
                )
                await s.commit()
        except Exception:
            logger.warning("memory.access_stats_update_failed")

    async def _embed(self, text_: str) -> list[float]:
        if self._llm_router is None:
            return [0.0] * 3072
        return await self._llm_router.embed(text_)


async def _set_rls(session, user_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id)},
    )
