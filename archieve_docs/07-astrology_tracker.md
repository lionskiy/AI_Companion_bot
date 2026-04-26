# Module 07: Astrology — Tracker

**Спека:** `07-astrology_spec.md` · **Зависимости:** Modules 01, 03, 05 выполнены

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| A-01 | Миграция: добавить колонки `birth_*`, `zodiac_sign`, `natal_data` в `user_profiles` | `mirror/db/migrations/versions/005_astrology.py` | `alembic upgrade head` |
| A-02 | `NatalChart`, `Transit` dataclass-ы | `mirror/services/astrology.py` | `python -m py_compile` |
| A-03 | Создание Qdrant-коллекции `knowledge_astro` при старте (idempotent) | `mirror/core/memory/qdrant_init.py` (дополнить) | `curl http://localhost:6333/collections` → `knowledge_astro` |
| A-04 | `AstrologyService.get_natal_chart()` через kerykeion + кэш в `natal_data` | `mirror/services/astrology.py` | `python -m py_compile` |
| A-05 | `AstrologyService.get_current_transits()` через kerykeion | `mirror/services/astrology.py` | `python -m py_compile` |
| A-06 | `AstrologyService.collect_birth_data()` — диалог сбора данных рождения | `mirror/services/astrology.py` | `python -m py_compile` |
| A-07 | Геокодирование города через geopy → lat/lon → `user_profiles` | `mirror/services/astrology.py` | `python -m py_compile` |
| A-08 | RAG pipeline: embed → Qdrant search `knowledge_astro` | `mirror/rag/astrology.py` | `python -m py_compile` |
| A-09 | `AstrologyService.handle()` — сборка контекста + LLM вызов (task_kind="astro_interpret") | `mirror/services/astrology.py` | `python -m py_compile` |
| A-10 | Тесты: natal chart, transit list, RAG search, handle без birth_date | `tests/astrology/test_astrology.py` | `pytest tests/astrology/ -v` → PASSED |

🛑 **CHECKPOINT:** natal chart вычисляется, birth_data собирается через диалог, RAG поиск работает.
