# Module 03: Memory — Tracker

**Спека:** `03-memory_spec.md` · **Зависимости:** I-05 выполнен

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| M-01 | Миграция: `memory_episodes` + `memory_facts` + RLS | `mirror/db/migrations/versions/002_memory.py` | `alembic upgrade head` |
| M-02 | ORM-модели `MemoryEpisode`, `MemoryFact` | `mirror/models/memory.py` | `python -m py_compile` |
| M-03 | Создание Qdrant-коллекций при старте (idempotent) | `mirror/core/memory/qdrant_init.py` | `curl http://localhost:6333/collections` → видны коллекции |
| M-04 | Реализовать Redis mem_L1: `get_session_history`, `add_to_session` | `mirror/core/memory/session.py` | `python -m py_compile` |
| M-05 | Реализовать `MemoryService` (write_episode, write_fact, search, forget) | `mirror/core/memory/service.py` | `python -m py_compile` |
| M-06 | Celery-задачи: `summarize_episode`, `extract_facts` | `mirror/workers/tasks/memory.py` | `python -m py_compile` |
| M-07 | NATS consumer: `mirror.dialog.session.closed` → запуск summarize_episode | `mirror/events/consumers/memory.py` | `python -m py_compile` |
| M-07b | Зарегистрировать `start_memory_consumer()` в lifespan FastAPI после `nats_client.connect()` | `mirror/main.py` | запуск приложения — consumer подписывается без ошибок |
| M-08 | Тесты: write/search/forget, идемпотентность задач | `tests/memory/test_memory.py` | `pytest tests/memory/ -v` → PASSED |

🛑 **CHECKPOINT:** поиск находит записанные данные, RLS изолирует пользователей.
