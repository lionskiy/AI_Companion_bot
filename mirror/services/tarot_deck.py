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
FULL_DECK = MAJOR_ARCANA + MINOR_ARCANA  # 78 cards

SPREADS = {
    "single": {"count": 1, "positions": ["Ответ"]},
    "three_card": {"count": 3, "positions": ["Прошлое", "Настоящее", "Будущее"]},
    "celtic_cross": {"count": 10, "positions": [
        "Суть ситуации", "Что пересекает", "Основа", "Прошлое",
        "Возможный исход", "Ближайшее будущее", "Страхи", "Внешние влияния",
        "Надежды", "Итог",
    ]},
}

assert len(FULL_DECK) == 78, f"Deck must have 78 cards, got {len(FULL_DECK)}"
