import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
from sqlalchemy import select, text

import mirror.db.session as db_module
from mirror.config import settings
from mirror.core.memory.session import add_to_session, get_session_history
from mirror.models.memory import MemoryEpisode, MemoryFact

logger = structlog.get_logger()


class MemoryService:
    def __init__(self, redis_client, llm_router=None) -> None:
        self._redis = redis_client
        self._llm_router = llm_router

    def _qdrant(self) -> AsyncQdrantClient:
        return AsyncQdrantClient(url=settings.qdrant_url)

    def _user_filter(self, user_id: UUID) -> Filter:
        return Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))])

    async def write_episode(
        self, user_id: UUID, session_id: UUID, text_: str, importance: float = 0.5
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
            )
            session.add(episode)
            await session.commit()
            logger.info("memory.episode_written", user_id=str(user_id), importance=importance)
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
                logger.info("memory.fact_updated", user_id=str(user_id), fact_type=fact_type, importance=importance)
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
                logger.info("memory.fact_written", user_id=str(user_id), fact_type=fact_type, importance=importance)
                return fact.id

    async def search(self, user_id: UUID, query: str, top_k: int = 5) -> dict:
        embedding = await self._embed(query)
        episodes_task = asyncio.create_task(self._search_episodes(user_id, embedding, top_k))
        facts_task = asyncio.create_task(self._search_facts(user_id, embedding, top_k))
        episodes, facts = await asyncio.gather(episodes_task, facts_task)
        return {"episodes": episodes, "facts": facts}

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

    async def _search_episodes(self, user_id: UUID, embedding: list[float], top_k: int) -> list[dict]:
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
        return [{"id": r.id, "score": r.score, **r.payload} for r in response.points]

    async def _search_facts(self, user_id: UUID, embedding: list[float], top_k: int) -> list[dict]:
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
        return [{"id": r.id, "score": r.score, **r.payload} for r in response.points]

    async def _embed(self, text_: str) -> list[float]:
        if self._llm_router is None:
            # stub: zero vector for testing without real LLM
            return [0.0] * 3072
        return await self._llm_router.embed(text_)


async def _set_rls(session, user_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id)},
    )
