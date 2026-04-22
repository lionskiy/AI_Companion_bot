import random
from dataclasses import dataclass, field
from uuid import UUID

import structlog

from mirror.core.llm.router import sanitize_input
from mirror.services.tarot_deck import FULL_DECK, SPREADS

logger = structlog.get_logger()


@dataclass
class DrawnCard:
    name: str
    position: str
    is_reversed: bool
    meaning_chunks: list[str] = field(default_factory=list)


class TarotService:
    def __init__(self, llm_router) -> None:
        self._llm = llm_router

    async def handle(self, state) -> str:
        from mirror.rag.tarot import search_tarot_knowledge

        spread_type = detect_spread_type(state["message"])
        cards = self.draw_cards(spread_type)

        for card in cards:
            card.meaning_chunks = await search_tarot_knowledge(
                card_name=card.name,
                user_question=state["message"],
                llm_router=self._llm,
            )

        facts = state.get("memory_context", {}).get("facts", [])
        messages = build_tarot_prompt(
            drawn_cards=cards,
            user_question=state["message"],
            facts=facts,
            sales_allowed=state.get("sales_allowed", True),
        )
        return await self._llm.call(
            task_kind="tarot_interpret",
            messages=messages,
            tier=state.get("tier", "free"),
        )

    def draw_cards(self, spread_type: str) -> list[DrawnCard]:
        spread = SPREADS[spread_type]
        count = spread["count"]
        rng = random.SystemRandom()
        selected = rng.sample(FULL_DECK, count)
        return [
            DrawnCard(
                name=name,
                position=spread["positions"][i],
                is_reversed=rng.choice([True, False]),
                meaning_chunks=[],
            )
            for i, name in enumerate(selected)
        ]

    async def search_card_knowledge(self, card_name: str, query: str) -> list[str]:
        from mirror.rag.tarot import search_tarot_knowledge
        return await search_tarot_knowledge(card_name, query, self._llm)


def detect_spread_type(text: str) -> str:
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["три карты", "прошлое настоящее", "three"]):
        return "three_card"
    if any(kw in text_lower for kw in ["кельтский", "полный", "celtic"]):
        return "celtic_cross"
    return "single"


def format_facts(facts: list[dict]) -> str:
    return "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:10])


def build_tarot_prompt(
    drawn_cards: list[DrawnCard],
    user_question: str,
    facts: list[dict],
    sales_allowed: bool,
) -> list[dict]:
    cards_text = "\n".join(
        f"{c.position}: {c.name} ({'перевёрнутая' if c.is_reversed else 'прямая'})"
        + (f"\nКонтекст: {chr(10).join(c.meaning_chunks)}" if c.meaning_chunks else "")
        for c in drawn_cards
    )
    system = f"Ты таролог-интерпретатор. Давай глубокие, тёплые и личные интерпретации.\nРасклад:\n{cards_text}"
    if facts:
        system += f"\n\nИзвестно о пользователе:\n{format_facts(facts)}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": sanitize_input(user_question)},
    ]
