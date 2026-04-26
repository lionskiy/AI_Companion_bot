# Module 08: Tarot — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §6.3, §12.4  
**Зависимости:** Module 05 (LLM Router), Module 03 (Memory)  
**Дата:** 2026-04-20

---

## Цель

Таро-модуль: расклады из 78 карт, интерпретации через RAG + LLM. Персонализированный ответ с учётом контекста пользователя.

---

## Acceptance Criteria

- [ ] `TarotService.handle(state: DialogState) → str`
- [ ] Поддерживаемые расклады: `single` (1 карта), `three_card` (3 карты: прошлое/настоящее/будущее), `celtic_cross` (10 карт)
- [ ] Карты тасуются криптостойко без повторений (random.SystemRandom().sample)
- [ ] Карта может быть прямой (upright) или перевёрнутой (reversed)
- [ ] Полная колода: 22 старших аркана + 56 младших аркана = 78 карт
- [ ] RAG: поиск в `knowledge_tarot` по имени карты и вопросу (Haystack)
- [ ] Интерпретация через LLM (task_kind="tarot_interpret") с контекстом RAG + профиля
- [ ] Qdrant коллекция `knowledge_tarot` создаётся при старте (idempotent)
- [ ] История раскладов НЕ сохраняется в отдельную таблицу (Stage 1) — только в mem_L1
- [ ] `spread_type` определяется из сообщения пользователя или дефолт `single`
- [ ] Тест: `draw_cards("single")` → 1 карта с именем и позицией

---

## Out of Scope

- История раскладов в отдельной таблице (Этап 2)
- Расклады на отношения, карьеру (специфические) — Этап 2
- Изображения карт — Этап 2
- Ежедневная карта (Daily Ritual Module 09 решает это)

---

## Колода (seed данные)

```python
# mirror/services/tarot_deck.py

MAJOR_ARCANA = [
    "The Fool", "The Magician", "The High Priestess", "The Empress", "The Emperor",
    "The Hierophant", "The Lovers", "The Chariot", "Strength", "The Hermit",
    "Wheel of Fortune", "Justice", "The Hanged Man", "Death", "Temperance",
    "The Devil", "The Tower", "The Star", "The Moon", "The Sun",
    "Judgement", "The World",
]

SUITS = ["Wands", "Cups", "Swords", "Pentacles"]
RANKS = ["Ace", "2", "3", "4", "5", "6", "7", "8", "9", "10",
         "Page", "Knight", "Queen", "King"]

MINOR_ARCANA = [f"{rank} of {suit}" for suit in SUITS for rank in RANKS]
FULL_DECK = MAJOR_ARCANA + MINOR_ARCANA  # 78 карт

SPREADS = {
    "single":      {"count": 1,  "positions": ["Ответ"]},
    "three_card":  {"count": 3,  "positions": ["Прошлое", "Настоящее", "Будущее"]},
    "celtic_cross": {"count": 10, "positions": [
        "Суть ситуации", "Что пересекает", "Основа", "Прошлое",
        "Возможный исход", "Ближайшее будущее", "Страхи", "Внешние влияния",
        "Надежды", "Итог",
    ]},
}
```

---

## Qdrant коллекции

```python
QDRANT_COLLECTIONS = {
    "knowledge_tarot": {
        "size": 3072,            # text-embedding-3-large
        "distance": "Cosine",
        # payload: card_name, arcana_type, suit, position, source, language
    }
}
```

---

## Публичный контракт `TarotService`

```python
# mirror/services/tarot.py  ← НЕ ИЗМЕНЯТЬ без явного ТЗ

@dataclass
class DrawnCard:
    name:       str
    position:   str   # "Прошлое", "Суть ситуации" и т.д.
    is_reversed: bool
    meaning_chunks: list[str]  # из RAG

class TarotService:
    async def handle(self, state: "DialogState") -> str:
        """
        1. Определить spread_type из сообщения
        2. draw_cards(spread_type)
        3. RAG поиск по каждой карте
        4. LLM интерпретация (task_kind="tarot_interpret")
        """

    def draw_cards(self, spread_type: str) -> list[DrawnCard]:
        """Вытянуть карты из FULL_DECK без повторений. random.SystemRandom (os.urandom)."""

    async def search_card_knowledge(self, card_name: str, query: str) -> list[str]:
        """RAG поиск в knowledge_tarot. Без фильтра user_id."""
```

---

## RAG pipeline

```python
# mirror/rag/tarot.py

async def search_tarot_knowledge(card_name: str, user_question: str, top_k: int = 3) -> list[str]:
    """
    1. Embed f"{card_name}: {user_question}" через LLMRouter.embed()
    2. Поиск в knowledge_tarot с фильтром payload.card_name == card_name (мягкий)
    3. Вернуть текстовые чанки
    """
```

---

## Промпт для tarot_interpret

```python
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
    system = f"""Ты таролог-интерпретатор. Давай глубокие, тёплые и личные интерпретации.
Расклад:
{cards_text}
"""
    if facts:
        system += f"\nИзвестно о пользователе:\n{format_facts(facts)}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": sanitize_input(user_question)},
    ]
```

---

## draw_cards — реализация без повторений

```python
import random

def draw_cards(self, spread_type: str) -> list[DrawnCard]:
    spread = SPREADS[spread_type]
    count = spread["count"]
    # SystemRandom использует os.urandom — криптостойко, поддерживает sample
    rng = random.SystemRandom()
    selected = rng.sample(FULL_DECK, count)
    return [
        DrawnCard(
            name=name,
            position=spread["positions"][i],
            is_reversed=rng.choice([True, False]),
            meaning_chunks=[],  # заполняется после RAG поиска
        )
        for i, name in enumerate(selected)
    ]
```

---

## Определение типа расклада

```python
def detect_spread_type(text: str) -> str:
    """Из текста пользователя → spread_type. Дефолт 'single'."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["три карты", "прошлое настоящее", "three"]):
        return "three_card"
    if any(kw in text_lower for kw in ["кельтский", "полный", "celtic"]):
        return "celtic_cross"
    return "single"
```

---

## Hard Constraints

- `random.SystemRandom().sample()` для случайного выбора карт без повторений (os.urandom, криптостойко)
- RAG поиск в `knowledge_tarot` без фильтра `user_id`
- `task_kind="tarot_interpret"` для всех LLM-вызовов модуля
- История раскладов в Stage 1 только в mem_L1 (не отдельная таблица)
- Колода полная: 78 карт без дублей в одном раскладе

---

## DoD

- `draw_cards("three_card")` → 3 уникальные карты с позициями и is_reversed
- RAG поиск находит чанки по имени карты
- Интерпретация содержит имена вытянутых карт
- `pytest tests/tarot/` зелёный
