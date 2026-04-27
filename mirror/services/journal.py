"""JournalService — free-form diary entries, evening reflection, monthly synthesis."""
import json
from datetime import date, datetime, timezone
from uuid import UUID

import structlog

from mirror.services.dialog_state import DialogState

logger = structlog.get_logger()

_REFLECTION_TTL = 3600
_REFLECTION_KEY = "practice_state:{uid}:reflection"


class JournalService:
    def __init__(self, llm_router, memory_service, redis_client) -> None:
        self._llm = llm_router
        self._memory = memory_service
        self._redis = redis_client

    async def handle(self, state: DialogState) -> str:
        msg = state.get("message", "").lower()
        uid = UUID(state["user_id"])

        if any(k in msg for k in ["что я писал", "найди запись", "поищи в дневнике", "поиск по дневнику"]):
            results = await self.search_entries(uid, state["message"])
            if not results:
                return "Подходящих записей не нашла."
            return "Вот что нашла в дневнике:\n\n" + "\n---\n".join(results[:3])

        if any(k in msg for k in ["рефлексия", "итоги дня", "вечерний вопрос"]):
            return await self.evening_reflection_prompt(uid)

        # Default: save as free-form entry
        entry_id = await self.save_entry(uid, state["message"], source="journal")
        mood = await self._analyze_mood(uid, state["message"])
        mood_str = f" Настроение: {mood}." if mood else ""
        logger.info("journal.entry_saved", user_id=str(uid))
        return f"Записала в дневник ✍️{mood_str}"

    async def save_entry(
        self,
        user_id: UUID,
        text: str,
        source: str = "journal",
    ) -> UUID:
        from uuid import uuid4
        session_id = uuid4()
        return await self._memory.write_episode(
            user_id=user_id,
            session_id=session_id,
            text_=text,
            importance=0.6,
            source_mode=source,
        )

    async def search_entries(
        self,
        user_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[str]:
        result = await self._memory.search(user_id, query, top_k=limit)
        journal_episodes = [
            ep.get("summary", "")
            for ep in result.get("episodes", [])
            if ep.get("source_mode") in ("journal", "journal_reflection", "journal_synthesis")
        ]
        return journal_episodes[:limit]

    async def evening_reflection_prompt(self, user_id: UUID) -> str:
        key = f"practice_state:{user_id}:reflection"
        raw = await self._redis.get(key)
        if raw:
            data = json.loads(raw)
            step = data.get("step", 0)
        else:
            data = {"practice": "reflection", "step": 1, "data": {}}
            step = 0

        questions = [
            "Что сегодня было хорошего, даже маленького?",
            "Что было трудным или неприятным?",
            "За что ты благодарен(а) сегодня?",
        ]

        if step == 0:
            data["step"] = 1
            await self._redis.setex(key, _REFLECTION_TTL, json.dumps(data))
            return questions[0]

        return questions[min(step, len(questions) - 1)]

    async def save_reflection_answer(
        self, user_id: UUID, answer: str, step: int
    ) -> str | None:
        key = f"practice_state:{user_id}:reflection"
        raw = await self._redis.get(key)
        data = json.loads(raw) if raw else {"practice": "reflection", "step": step, "data": {}}
        step_data = data.get("data", {})
        step_data[f"q{step}"] = answer
        data["data"] = step_data

        questions = [
            "Что сегодня было хорошего, даже маленького?",
            "Что было трудным или неприятным?",
            "За что ты благодарен(а) сегодня?",
        ]

        if step >= len(questions):
            # Save as journal episode
            await self._redis.delete(key)
            text = "\n".join(f"{questions[i]}\n— {step_data.get(f'q{i+1}', '')}" for i in range(len(questions)))
            await self.save_entry(user_id, text, source="journal_reflection")
            logger.info("journal.reflection_completed", user_id=str(user_id))
            return None  # conversation complete

        data["step"] = step + 1
        await self._redis.setex(key, _REFLECTION_TTL, json.dumps(data))
        return questions[step]

    async def monthly_synthesis(self, user_id: UUID, month: int, year: int) -> str:
        from sqlalchemy import select, extract
        import mirror.db.session as db_module
        from mirror.models.memory import MemoryEpisode

        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(MemoryEpisode.summary)
                .where(MemoryEpisode.user_id == user_id)
                .where(MemoryEpisode.source_mode.in_(["journal", "journal_reflection"]))
                .where(MemoryEpisode.deleted_at.is_(None))
                .where(extract("month", MemoryEpisode.created_at) == month)
                .where(extract("year", MemoryEpisode.created_at) == year)
                .order_by(MemoryEpisode.created_at)
            )
            entries = result.scalars().all()

        if not entries:
            return ""

        combined = "\n\n---\n\n".join(entries[:50])
        synthesis = await self._llm.call(
            task_kind="journal_monthly_synthesis",
            messages=[{
                "role": "user",
                "content": f"Записи дневника за {month}/{year}:\n\n{combined[:4000]}"
            }],
        )
        from uuid import uuid4
        await self._memory.write_episode(
            user_id=user_id,
            session_id=uuid4(),
            text_=synthesis,
            importance=0.8,
            source_mode="journal_synthesis",
        )
        logger.info("journal.synthesis_generated", user_id=str(user_id), month=month, year=year)
        return synthesis

    async def _analyze_mood(self, user_id: UUID, text: str) -> str | None:
        try:
            return await self._llm.call(
                task_kind="journal_analyze",
                messages=[{"role": "user", "content": text[:500]}],
            )
        except Exception:
            logger.warning("journal.mood_analyze_failed", user_id=str(user_id))
            return None
