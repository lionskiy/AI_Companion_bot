from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import select

import mirror.db.session as db_module
from mirror.models.user import UserProfile
from mirror.services.astrology import Transit
from mirror.services.tarot import DrawnCard

logger = structlog.get_logger()

RITUAL_DISABLED_MSG = (
    "Ежедневный ритуал отключён. Чтобы включить снова, напиши /active 🌅"
)


@dataclass
class DailyRitual:
    user_id: UUID
    card: DrawnCard
    transit: Transit | None
    affirmation: str
    date: date


class DailyRitualService:
    def __init__(self, tarot_service, astrology_service, llm_router) -> None:
        self._tarot = tarot_service
        self._astrology = astrology_service
        self._llm = llm_router

    async def handle(self, state) -> str:
        uid = UUID(state["user_id"])
        profile = await self._get_profile(uid)
        if profile and not getattr(profile, "daily_ritual_enabled", True):
            return RITUAL_DISABLED_MSG
        ritual = await self.build_ritual(uid, state)
        return self.format_ritual_message(ritual)

    async def build_ritual(self, user_id: UUID, state: dict | None = None) -> DailyRitual:
        cards = self._tarot.draw_cards("single")
        card = cards[0]

        # Transit only if user has birth data
        transit: Transit | None = None
        try:
            profile = await self._astrology._get_profile(user_id)
            if profile and profile.birth_date:
                transits = await self._astrology.get_current_transits()
                transit = transits[0] if transits else None
        except Exception:
            transit = None

        facts = []
        if state:
            facts = state.get("memory_context", {}).get("facts", [])

        affirmation = await self._generate_affirmation(card, transit, facts)

        return DailyRitual(
            user_id=user_id,
            card=card,
            transit=transit,
            affirmation=affirmation,
            date=datetime.now(timezone.utc).date(),
        )

    def format_ritual_message(self, ritual: DailyRitual) -> str:
        text = "🌅 *Доброе утро! Твой ритуал на сегодня*\n\n"
        text += f"🃏 *Карта дня:* {ritual.card.name}"
        if ritual.card.is_reversed:
            text += " _(перевёрнутая)_"
        text += "\n\n"
        if ritual.transit:
            text += f"✨ *Транзит дня:* {ritual.transit.planet} в {ritual.transit.sign}\n\n"
        text += f"💫 *Аффирмация:*\n_{ritual.affirmation}_"
        return text

    async def _generate_affirmation(
        self, card: DrawnCard, transit: Transit | None, facts: list[dict]
    ) -> str:
        messages = _build_affirmation_prompt(card, transit, facts)
        try:
            return await self._llm.call(
                task_kind="proactive_compose",
                messages=messages,
            )
        except Exception:
            return "Сегодня — хороший день для новых начинаний ✨"

    async def _get_profile(self, user_id: UUID) -> UserProfile | None:
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            return result.scalar_one_or_none()


def _build_affirmation_prompt(
    card: DrawnCard, transit: Transit | None, facts: list[dict]
) -> list[dict]:
    context = f"Карта дня: {card.name} ({'перевёрнутая' if card.is_reversed else 'прямая'})"
    if transit:
        context += f"\nТранзит: {transit.planet} в {transit.sign}"
    system = (
        "Создай короткую (1-2 предложения) персональную аффирмацию для утреннего ритуала.\n"
        f"{context}\nТон: тёплый, вдохновляющий, конкретный."
    )
    if facts:
        from mirror.services.tarot import format_facts
        system += f"\nИзвестно о пользователе:\n{format_facts(facts)}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "Создай аффирмацию"},
    ]
