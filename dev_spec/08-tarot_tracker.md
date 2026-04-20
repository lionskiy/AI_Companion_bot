# Module 08: Tarot — Tracker

**Спека:** `08-tarot_spec.md` · **Зависимости:** Modules 03, 05 выполнены

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| T-01 | `FULL_DECK`, `SPREADS` константы + `DrawnCard` dataclass | `mirror/services/tarot_deck.py`, `mirror/services/tarot.py` | `python -m py_compile`; `len(FULL_DECK) == 78` |
| T-02 | `TarotService.draw_cards(spread_type)` через `secrets.choice`, без дублей | `mirror/services/tarot.py` | Тест: `len(draw_cards("celtic_cross")) == 10`, все уникальные |
| T-03 | `detect_spread_type(text)` — определение расклада из текста | `mirror/services/tarot.py` | `python -m py_compile` |
| T-04 | Создание Qdrant-коллекции `knowledge_tarot` при старте (idempotent) | `mirror/core/memory/qdrant_init.py` (дополнить) | `curl http://localhost:6333/collections` → `knowledge_tarot` |
| T-05 | RAG pipeline: embed → Qdrant search `knowledge_tarot` | `mirror/rag/tarot.py` | `python -m py_compile` |
| T-06 | `TarotService.handle()` — spread + RAG + LLM (task_kind="tarot_interpret") | `mirror/services/tarot.py` | `python -m py_compile` |
| T-07 | Тесты: draw_cards, detect_spread, handle | `tests/tarot/test_tarot.py` | `pytest tests/tarot/ -v` → PASSED |

🛑 **CHECKPOINT:** draw_cards возвращает корректную колоду без дублей, LLM интерпретирует расклад.
