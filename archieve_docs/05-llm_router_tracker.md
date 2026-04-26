# Module 05: LLM Router — Tracker

**Спека:** `05-llm_router_spec.md` · **Зависимости:** Module 01 (users.subscription)

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| L-01 | Миграция: `llm_providers` + `llm_routing` + seed данные (12 task_kinds) | `mirror/db/migrations/versions/003_llm_routing.py` | `alembic upgrade head` → `SELECT COUNT(*) FROM llm_routing` = 12 |
| L-02 | ORM-модели `LLMProvider`, `LLMRouting` | `mirror/models/llm.py` | `python -m py_compile` |
| L-03 | `AllModelsUnavailableError` кастомное исключение | `mirror/core/llm/exceptions.py` | `python -m py_compile` |
| L-04 | Реализовать `LLMRouter` (call, embed, _get_routing, _call_provider) | `mirror/core/llm/router.py` | `python -m py_compile` |
| L-05 | Startup guard: проверка всех canonical task_kinds при старте FastAPI | `mirror/core/llm/router.py` (метод `validate_routing`) | `python -m py_compile` |
| L-06 | Тесты: retry при ошибке primary, fallback chain, AllModelsUnavailableError, embed | `tests/llm/test_router.py` | `pytest tests/llm/ -v` → PASSED |

🛑 **CHECKPOINT:** fallback срабатывает при недоступности primary, приложение не стартует без полного routing.
