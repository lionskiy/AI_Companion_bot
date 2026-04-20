# Module 03: Memory (L0–L3) — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §9, §1.5, §1.6, §12.1  
**Зависимости:** Module 01 (Identity)  
**Дата:** 2026-04-20

---

## Цель

Иерархическая система памяти: от контекста текущего промпта до долгосрочных фактов о пользователе. Единственный публичный контракт — `MemoryService` API. Никакой другой модуль не обращается к Qdrant или таблицам памяти напрямую.

---

## Уровни памяти (нейминг обязателен в коде/БД/событиях)

| Код | Название | Хранилище | TTL | Содержимое |
|-----|---------|-----------|-----|-----------|
| `mem_L0` | Context Window | RAM (промпт) | 1 запрос | Текущий диалог, собранный контекст |
| `mem_L1` | Session Cache | Redis | 48 ч | История сообщений текущей сессии (до 20 сообщений) |
| `mem_L2` | Episode Memory | PostgreSQL + Qdrant `user_episodes` | Долгосрочно | Суммаризации завершённых сессий |
| `mem_L3` | Semantic Memory | PostgreSQL + Qdrant `user_facts` | Долгосрочно | Извлечённые факты о пользователе |

---

## Acceptance Criteria

- [ ] `MemoryService.write_episode(user_id, text)` → сохраняет в PG + Qdrant `user_episodes`
- [ ] `MemoryService.write_fact(user_id, key, value, fact_type, importance)` → PG + Qdrant `user_facts`
- [ ] `MemoryService.search(user_id, query, top_k=5)` → параллельный поиск KB + user memory
- [ ] `MemoryService.forget(user_id, scope)` → удаляет из Qdrant и помечает в PG (`deleted_at`)
- [ ] Поиск всегда с фильтром `user_id` в Qdrant (никакой утечки между пользователями)
- [ ] `qdrant_point_id` сохраняется в PG при каждой записи в Qdrant
- [ ] RLS включён на `memory_episodes`, `memory_facts`
- [ ] mem_L1 (Redis): `get_session_history(user_id) → list[dict]`, `add_to_session(user_id, role, text)`
- [ ] Celery-задача `summarize_episode` запускается при закрытии сессии
- [ ] Celery-задача `extract_facts` запускается после суммаризации
- [ ] Qdrant-коллекции `user_episodes` и `user_facts` создаются при старте если не существуют

---

## Out of Scope

- mem_L2/L3 для Knowledge Base (KB) — создаётся в модулях Tarot и Astrology
- Mem0 интеграция (опционально, §9.6 — можно добавить позже)
- Provenance API (Этап 2)
- `/delete_me` полное удаление (Этап 2, 152-ФЗ)

---

## Схема БД

```sql
CREATE TABLE memory_episodes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id      uuid NOT NULL,
    summary         text NOT NULL,
    qdrant_point_id uuid,
    importance      numeric(4,3) DEFAULT 0.5,
    created_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);
CREATE INDEX idx_memory_episodes_user ON memory_episodes(user_id, created_at DESC)
    WHERE deleted_at IS NULL;
ALTER TABLE memory_episodes ENABLE ROW LEVEL SECURITY;
-- RLS policy: приложение устанавливает app.current_user_id перед каждым запросом
CREATE POLICY memory_episodes_user_isolation ON memory_episodes
    USING (user_id = current_setting('app.current_user_id', true)::uuid);
GRANT ALL ON memory_episodes TO mirror_app;  -- роль приложения

CREATE TABLE memory_facts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    fact_type       text NOT NULL
        CHECK (fact_type IN ('declared','observed','inferred','user_verified','external')),
    key             text NOT NULL,
    value           text NOT NULL,
    importance      numeric(4,3) DEFAULT 0.5,
    confidence      numeric(4,3) DEFAULT 1.0,
    consent_scope   text,
    qdrant_point_id uuid,
    source          text,
    version         int NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz,
    deleted_at      timestamptz
);
CREATE INDEX idx_memory_facts_user ON memory_facts(user_id, importance DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_memory_facts_type ON memory_facts(user_id, fact_type)
    WHERE deleted_at IS NULL;
ALTER TABLE memory_facts ENABLE ROW LEVEL SECURITY;
CREATE POLICY memory_facts_user_isolation ON memory_facts
    USING (user_id = current_setting('app.current_user_id', true)::uuid);
GRANT ALL ON memory_facts TO mirror_app;
```

> Перед каждым запросом к таблицам памяти выполнять:
> `SET LOCAL app.current_user_id = '<uuid>';`
> Это делается в `MemoryService` через session-level SET в async session.
> В тестах: `SET app.current_user_id = 'test-uuid'` в фикстуре.

---

## Qdrant коллекции

```python
# Создаются при старте (idempotent)
QDRANT_COLLECTIONS = {
    "user_episodes": {
        "size": 3072,           # text-embedding-3-large
        "distance": "Cosine",
        # payload: user_id, session_id, importance, created_at
    },
    "user_facts": {
        "size": 3072,
        "distance": "Cosine",
        # payload: user_id, fact_type, key, importance, consent_scope, created_at
    },
}
```

Embedding model: `text-embedding-3-large` (task_kind=`"embedding"`).

---

## Публичный контракт `MemoryService`

```python
# mirror/core/memory/service.py

class MemoryService:
    async def write_episode(
        self, user_id: UUID, session_id: UUID, text: str, importance: float = 0.5
    ) -> UUID:
        """Записать суммаризацию сессии в PG + Qdrant. Возвращает episode_id."""

    async def write_fact(
        self, user_id: UUID, key: str, value: str,
        fact_type: str = "observed", importance: float = 0.5,
        consent_scope: str | None = None,
    ) -> UUID:
        """
        Записать факт о пользователе в PG + Qdrant. Возвращает fact_id.
        UPSERT-логика: если запись с (user_id, key) уже существует и не удалена →
          обновить value, importance, version+=1, updated_at.
          Удалить старый Qdrant-вектор, записать новый.
        Если не существует → INSERT.
        Это обеспечивает идемпотентность Celery retry.
        """

    async def search(
        self, user_id: UUID, query: str, top_k: int = 5
    ) -> dict:
        """Параллельный поиск в user_episodes + user_facts.
        Возвращает {"episodes": [...], "facts": [...]}"""

    async def get_session_history(
        self, user_id: UUID, max_messages: int = 20
    ) -> list[dict]:
        """
        Получить историю сессии из Redis (mem_L1).
        Redis key: `mem_l1:{user_id}`
        Value: JSON-список [{"role": "user"|"assistant", "content": "..."}]
        Возвращает последние max_messages сообщений.
        """

    async def add_to_session(
        self, user_id: UUID, role: str, text: str
    ) -> None:
        """
        Добавить сообщение в сессию Redis (mem_L1). TTL сбрасывается до 48ч.
        Redis key: `mem_l1:{user_id}`
        Операция: RPUSH + LTRIM (держать не более 20 элементов) + EXPIRE 172800
        """

    async def forget(
        self, user_id: UUID, scope: str = "all"
    ) -> None:
        """Пометить как удалённые в PG, удалить из Qdrant."""
```

---

## Celery задачи

Celery worker синхронный. Для вызова async-кода (LLMRouter, MemoryService) использовать `asyncio.run()`:

```python
# mirror/workers/tasks/memory.py

@celery_app.task(queue="default", max_retries=3, bind=True)
def summarize_episode(self, user_id: str, session_id: str) -> None:
    """Суммаризировать сессию → mem_L2. task_kind="memory_summarize"."""
    try:
        asyncio.run(_summarize_episode_async(user_id, session_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)

@celery_app.task(queue="default", max_retries=3, bind=True)
def extract_facts(self, user_id: str, episode_id: str) -> None:
    """Извлечь факты из эпизода → mem_L3. task_kind="memory_extract_facts"."""
    try:
        asyncio.run(_extract_facts_async(user_id, episode_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)

async def _summarize_episode_async(user_id: str, session_id: str) -> None:
    """Async реализация суммаризации."""
    from mirror.dependencies import memory_service, llm_router
    # ... реализация

async def _extract_facts_async(user_id: str, episode_id: str) -> None:
    """Async реализация извлечения фактов."""
    from mirror.dependencies import memory_service, llm_router
    # ... реализация
```

> `asyncio.run()` создаёт новый event loop на каждый вызов — нормально для Celery worker.
> Не использовать глобальный loop из main FastAPI process.

Триггер: NATS event `mirror.dialog.session.closed` → consumer запускает `summarize_episode`.

## NATS Consumer

```python
# mirror/events/consumers/memory.py

async def start_memory_consumer() -> None:
    """Запускается в lifespan FastAPI. Подписывается на session.closed."""
    await nats_client.subscribe(
        subject="mirror.dialog.session.closed",
        handler=_on_session_closed,
    )

async def _on_session_closed(msg: dict) -> None:
    """Получить событие и поставить Celery-задачу."""
    from mirror.workers.tasks.memory import summarize_episode
    user_id = msg["user_id"]
    session_id = msg["session_id"]
    summarize_episode.delay(user_id, session_id)
```

> `start_memory_consumer()` вызывается в `lifespan` в `main.py` после `nats_client.connect()`.
> Celery-задача ставится в очередь через `.delay()` — выполняется в Celery worker, не в FastAPI process.

---

## Параллельный поиск (обязателен)

```python
async def search(self, user_id, query, top_k=5):
    query_embedding = await llm_router.embed(query)  # task_kind="embedding"
    episodes_task = asyncio.create_task(self._search_episodes(user_id, query_embedding, top_k))
    facts_task = asyncio.create_task(self._search_facts(user_id, query_embedding, top_k))
    episodes, facts = await asyncio.gather(episodes_task, facts_task)
    return {"episodes": episodes, "facts": facts}
```

---

## Hard Constraints

- pgvector ЗАПРЕЩЁН — только Qdrant для эмбеддингов (§1.5)
- Фильтр `user_id` ОБЯЗАТЕЛЕН при любом поиске в `user_*` коллекциях
- `qdrant_point_id` сохраняется в PG при каждой записи
- Двойная запись: сначала Qdrant, потом PG (или в транзакции с компенсацией)
- Логировать только `user_id`, `fact_type`, `importance` — не текст фактов/эпизодов

---

## DoD

- Миграция применена, RLS включён
- `MemoryService.search` использует параллельные задачи
- Celery-задачи идемпотентны (повторный запуск не дублирует данные)
- `pytest tests/memory/` зелёный
