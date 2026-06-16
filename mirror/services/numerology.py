"""NumerologyService — Pythagorean numerology calculations and interpretations."""
import asyncio
import json
from datetime import date, datetime, timezone
from uuid import UUID

import structlog

from mirror.rag.numerology import search_numerology_knowledge
from mirror.services.dialog_state import DialogState

logger = structlog.get_logger()


class NumerologyCalculator:
    PYTHAGOREAN_RU = {
        'а': 1, 'б': 2, 'в': 3, 'г': 4, 'д': 5, 'е': 6, 'ё': 6, 'ж': 7, 'з': 8, 'и': 9,
        'й': 1, 'к': 2, 'л': 3, 'м': 4, 'н': 5, 'о': 6, 'п': 7, 'р': 8, 'с': 9,
        'т': 1, 'у': 2, 'ф': 3, 'х': 4, 'ц': 5, 'ч': 6, 'ш': 7, 'щ': 8, 'ъ': 9,
        'ы': 1, 'ь': 2, 'э': 3, 'ю': 4, 'я': 5,
    }
    PYTHAGOREAN_EN = {
        'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6, 'g': 7, 'h': 8, 'i': 9,
        'j': 1, 'k': 2, 'l': 3, 'm': 4, 'n': 5, 'o': 6, 'p': 7, 'q': 8, 'r': 9,
        's': 1, 't': 2, 'u': 3, 'v': 4, 'w': 5, 'x': 6, 'y': 7, 'z': 8,
    }
    MASTER_NUMBERS = {11, 22, 33}

    def reduce(self, n: int) -> int:
        while n > 9 and n not in self.MASTER_NUMBERS:
            n = sum(int(d) for d in str(n))
        return n

    def life_path(self, birth_date: date) -> int:
        d = self.reduce(birth_date.day)
        m = self.reduce(birth_date.month)
        y = self.reduce(sum(int(c) for c in str(birth_date.year)))
        return self.reduce(d + m + y)

    def name_number(self, name: str) -> int:
        table = {**self.PYTHAGOREAN_RU, **self.PYTHAGOREAN_EN}
        total = sum(table.get(c.lower(), 0) for c in name if c.isalpha())
        return self.reduce(total)

    def personal_year(self, birth_date: date, year: int) -> int:
        d = self.reduce(birth_date.day)
        m = self.reduce(birth_date.month)
        y = self.reduce(sum(int(c) for c in str(year)))
        return self.reduce(d + m + y)

    def personal_month(self, birth_date: date, year: int, month: int) -> int:
        return self.reduce(self.personal_year(birth_date, year) + self.reduce(month))

    def personal_day(self, birth_date: date, today: date) -> int:
        pm = self.personal_month(birth_date, today.year, today.month)
        return self.reduce(pm + self.reduce(today.day))


_calc = NumerologyCalculator()


class NumerologyService:
    def __init__(self, llm_router, memory_service) -> None:
        self._llm = llm_router
        self._memory = memory_service

    async def handle(self, state: DialogState) -> str:
        uid = UUID(state["user_id"])
        birth_date, name = await self._get_user_data(uid)

        if birth_date is None:
            return (
                "Для расчёта нумерологии мне нужна твоя дата рождения. "
                "Напиши её в формате ДД.ММ.ГГГГ (например, 15.03.1990)."
            )

        today = date.today()
        lp = _calc.life_path(birth_date)
        py = _calc.personal_year(birth_date, today.year)
        pm = _calc.personal_month(birth_date, today.year, today.month)
        pd = _calc.personal_day(birth_date, today)
        nn = _calc.name_number(name) if name else None

        numbers_to_search = list({lp, py})
        kb_results = await search_numerology_knowledge(numbers_to_search, self._llm)

        numbers_payload: dict = {
            "life_path": lp,
            "personal_year": py,
            "personal_month": pm,
            "personal_day": pd,
            "birth_date": birth_date.isoformat(),
        }
        if nn is not None:
            numbers_payload["name_number"] = nn
            numbers_payload["name"] = name

        interpretation = await self._llm.call(
            task_kind="numerology_interpret",
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "numbers": numbers_payload,
                    "kb": kb_results[:9],
                    "today": today.isoformat(),
                }, ensure_ascii=False),
            }],
        )

        asyncio.create_task(
            self._save_results(uid, lp, numbers_payload)
        )

        logger.info("numerology.handle", user_id=str(uid), life_path=lp)
        return interpretation

    async def _get_user_data(self, user_id: UUID) -> tuple[date | None, str | None]:
        try:
            from sqlalchemy import select
            import mirror.db.session as db_module
            from mirror.models.user import UserProfile

            async with db_module.async_session_factory() as session:
                row = await session.execute(
                    select(UserProfile.birth_date, UserProfile.preferred_name)
                    .where(UserProfile.user_id == user_id)
                )
                result = row.first()
            if result:
                return result.birth_date, result.preferred_name
        except Exception:
            logger.warning("numerology.get_user_data_failed", user_id=str(user_id))
        return None, None

    async def _save_results(
        self,
        user_id: UUID,
        life_path: int,
        numbers: dict,
    ) -> None:
        try:
            await self._save_life_path_number(user_id, life_path)
            await self._memory.write_fact(
                user_id=user_id,
                key=f"numerology_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                value=json.dumps(numbers, ensure_ascii=False)[:500],
                fact_type="numerology",
                importance=0.7,
            )
            logger.info("numerology.calculated", user_id=str(user_id), life_path=life_path)
        except Exception:
            logger.warning("numerology.save_failed", user_id=str(user_id))

    async def _save_life_path_number(self, user_id: UUID, life_path: int) -> None:
        try:
            from sqlalchemy import update
            import mirror.db.session as db_module
            from mirror.models.user import UserProfile

            async with db_module.async_session_factory() as session:
                await session.execute(
                    update(UserProfile)
                    .where(UserProfile.user_id == user_id)
                    .where(UserProfile.life_path_number.is_(None))
                    .values(life_path_number=life_path)
                )
                await session.commit()
        except Exception:
            logger.warning("numerology.save_life_path_failed", user_id=str(user_id))
