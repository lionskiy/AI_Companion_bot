# Module 17: Глубокий retrieval (Rerank + Приоритеты памяти) — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §9.2, §9.3, §9.4  
**Зависимости:** 03-memory, 05-llm_router  
**Дата:** 2026-04-26

---

## Цель

Улучшить качество контекста который подаётся в LLM при каждом ответе:
1. **Reranking** — после первичного поиска по Qdrant переранжировать результаты через cross-encoder или LLM-скоринг
2. **Приоритеты по importance** — факты с высокой важностью (importance > 0.85) всегда включаются в контекст (pinned facts)
3. **Дедупликация фактов** — при извлечении новых фактов проверять similarity с существующими (порог 0.92)
4. **Context budget** — контролировать итоговый размер контекста (токены)

> **Изменение `mirror/core/memory/service.py` явно разрешено для этого модуля**, несмотря на общее правило CLAUDE.md. Причина: улучшение retrieval — ключевая задача этапа 2.

---

## Acceptance Criteria

- [ ] `MemoryService.search()` возвращает результаты отсортированные по `final_score = vector_score × rerank_score × importance`
- [ ] Pinned facts (importance ≥ 0.85) всегда включаются в контекст независимо от релевантности
- [ ] Context budget: суммарный размер facts + episodes в промпте не превышает `MAX_MEMORY_TOKENS` (default 1500)
- [ ] При сохранении нового факта: поиск top-5 ближайших → если similarity > 0.92 → обновить existing, не создавать новый
- [ ] Reranker опционален: если `reranker_type='disabled'` — используется только vector score
- [ ] Importance: +0.05 за каждое обращение к факту (access_count), −0.02 за 30 дней без обращения (Celery)
- [ ] `access_count` и `last_accessed` обновляются при каждом использовании факта в промпте
- [ ] Новые поля `access_count`, `last_accessed` добавлены в `memory_facts` (миграция 024)

---

## Архитектура

### Схема поиска с reranking

```
query_text
    ↓ embed (LLMRouter.embed)
    → Qdrant search user_facts   (top-15, filter user_id)
    → Qdrant search user_episodes (top-10, filter user_id)
    ↓ candidate list (25 items)
    → Reranker.score(query, candidates)   # cross-encoder или LLM, или disabled
    → final_score = vector_score × rerank_score × importance
    → sort by final_score DESC
    → pick top-5 facts + top-3 episodes  (из отсортированных)
    + всегда добавить pinned facts (importance ≥ 0.85, дедублировать по id)
    → trim to MAX_MEMORY_TOKENS budget
    → update access_count + last_accessed для использованных фактов (async)
    → return MemoryContext
```

### Reranker — три реализации

```python
from abc import ABC, abstractmethod

class BaseReranker(ABC):
    @abstractmethod
    async def score(self, query: str, candidates: list[str]) -> list[float]:
        """
        Возвращает list[float] той же длины что candidates.
        Значения нормализованы 0.0-1.0.
        """

class LLMReranker(BaseReranker):
    """Использует LLM для оценки релевантности. Точнее, дороже (~$0.001/запрос)."""

    async def score(self, query: str, candidates: list[str]) -> list[float]:
        # Батч-запрос: "оцени релевантность каждого факта к запросу [0-1]"
        # task_kind = 'rerank'
        # При ошибке LLM: логировать, вернуть [1.0] * len(candidates) (fallback = без reranking)
        ...

class CrossEncoderReranker(BaseReranker):
    """Использует локальную cross-encoder модель. Быстрее (~10ms), дешевле."""
    MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self) -> None:
        self._model = None  # lazy load при первом вызове

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.MODEL_NAME)  # CPU по умолчанию, GPU если доступен

    async def score(self, query: str, candidates: list[str]) -> list[float]:
        self._load_model()
        # score() синхронный — запускаем в executor чтобы не блокировать event loop
        loop = asyncio.get_event_loop()
        pairs = [(query, c) for c in candidates]
        raw_scores = await loop.run_in_executor(None, self._model.predict, pairs)
        # Нормализуем в 0-1 через sigmoid
        import math
        return [1 / (1 + math.exp(-s)) for s in raw_scores]

class DisabledReranker(BaseReranker):
    """Заглушка — возвращает [1.0] для всех. Используется при reranker_type='disabled'."""
    async def score(self, query: str, candidates: list[str]) -> list[float]:
        return [1.0] * len(candidates)


def get_reranker(reranker_type: str) -> BaseReranker:
    """Фабрика. Вызывается при инициализации MemoryService."""
    if reranker_type == "llm":
        return LLMReranker()
    if reranker_type == "cross_encoder":
        return CrossEncoderReranker()
    return DisabledReranker()
```

### Context budget

```python
class ContextBudget:
    def fit(
        self,
        facts: list[dict],
        episodes: list[dict],
        max_tokens: int,
    ) -> tuple[list[dict], list[dict]]:
        """
        Обрезает списки чтобы уложиться в бюджет токенов.
        Порядок включения:
          1. Pinned facts (importance >= pinned_importance_threshold) — ВСЕГДА
          2. Остальные факты по final_score DESC
          3. Эпизоды по final_score DESC
        Токены считаются приближённо: len(text) // 4.
        Возвращает (trimmed_facts, trimmed_episodes).
        """
        pinned_threshold = float(get_app_config("pinned_importance_threshold", "0.85"))
        pinned = [f for f in facts if f.get("importance", 0) >= pinned_threshold]
        rest_facts = [f for f in facts if f.get("importance", 0) < pinned_threshold]

        result_facts, result_episodes = list(pinned), []
        used = sum(len(str(f)) // 4 for f in result_facts)

        for f in sorted(rest_facts, key=lambda x: x.get("final_score", 0), reverse=True):
            cost = len(str(f)) // 4
            if used + cost > max_tokens:
                break
            result_facts.append(f)
            used += cost

        for ep in sorted(episodes, key=lambda x: x.get("final_score", 0), reverse=True):
            cost = len(ep.get("summary", "")) // 4
            if used + cost > max_tokens:
                break
            result_episodes.append(ep)
            used += cost

        return result_facts, result_episodes
```

### Дедупликация фактов при write_fact()

В `MemoryService.write_fact()` после существующей проверки по ключу добавить семантическую дедупликацию:

```python
# После существующей проверки "existing = ... by key":
if not existing:
    # Семантический поиск дублей
    embedding = await self._embed(f"{key}: {value}")
    similar = await self._search_facts_raw(user_id, embedding, top_k=5)
    for candidate in similar:
        if candidate["score"] > float(get_app_config("fact_dedup_threshold", "0.92")):
            # Дубль найден — обновляем вместо создания
            existing_id = candidate["id"]
            # ... обновить fact_type, value, importance если нужно
            logger.info("memory.fact.deduplicated", user_id=str(user_id))
            return existing_id
```

### Обновление access_count (async)

```python
# В MemoryService.search() после получения результатов:
async def _update_access_stats(self, fact_ids: list[str]) -> None:
    """Обновляет access_count и last_accessed. Не бросает — логирует при ошибке."""
    try:
        async with async_session_factory() as s:
            await s.execute(
                text("""
                    UPDATE memory_facts
                    SET access_count = access_count + 1,
                        last_accessed = NOW()
                    WHERE id = ANY(:ids)
                """),
                {"ids": fact_ids},
            )
            await s.commit()
    except Exception:
        logger.warning("memory.access_stats_update_failed")

# Вызов после возврата результатов (не блокирует ответ):
used_fact_ids = [f["id"] for f in result_facts]
asyncio.create_task(self._update_access_stats(used_fact_ids))
```

### Importance decay (Celery)

```python
@celery_app.task(
    name="mirror.workers.tasks.memory.decay_fact_importance",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def decay_fact_importance(self):
    asyncio.run(_decay_importance())

async def _decay_importance():
    await ensure_db_pool()
    async with get_session() as session:
        result = await session.execute(text("""
            UPDATE memory_facts
            SET importance = GREATEST(0.1, importance - 0.02)
            WHERE last_accessed < NOW() - INTERVAL '30 days'
              AND importance > 0.1
              AND deleted_at IS NULL
        """))
        await session.commit()
        logger.info("memory.importance_decayed", rows=result.rowcount)
```

Beat schedule: `crontab(hour=4, minute=0, day_of_week=1)` — еженедельно, понедельник 04:00 UTC.  
При ошибке: `max_retries=3`, retry через 5 мин. Partial failure (часть строк обновилась) — не проблема, следующий запуск исправит.

---

## Схема БД (миграция 024)

```sql
-- Добавить в memory_facts:
ALTER TABLE memory_facts
  ADD COLUMN access_count   INTEGER DEFAULT 0 NOT NULL,
  ADD COLUMN last_accessed  TIMESTAMPTZ;

-- Индекс для pinned facts (быстрый доступ к важным фактам):
CREATE INDEX idx_memory_facts_pinned
  ON memory_facts (user_id, importance DESC)
  WHERE archived = FALSE AND deleted_at IS NULL;

-- Индекс для decay task (факты не обращались к которым):
CREATE INDEX idx_memory_facts_stale
  ON memory_facts (last_accessed)
  WHERE deleted_at IS NULL AND importance > 0.1;
```

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `rerank` | main_chat | Оценка релевантности кандидатов (если reranker_type='llm') |

---

## Новые конфиги (app_config, seed в миграции 020)

| Ключ | Default | Описание |
|------|---------|---------|
| `reranker_type` | `disabled` | Тип rerankera: disabled / llm / cross_encoder |
| `max_memory_tokens` | `1500` | Бюджет токенов на память в промпте |
| `pinned_importance_threshold` | `0.85` | Порог для всегда-включаемых фактов |
| `fact_dedup_threshold` | `0.92` | Порог similarity для дедупликации фактов |

```sql
-- Добавить в seed (migration 020):
INSERT INTO app_config (key, value) VALUES
  ('reranker_type', 'disabled'),
  ('max_memory_tokens', '1500'),
  ('pinned_importance_threshold', '0.85'),
  ('fact_dedup_threshold', '0.92')
ON CONFLICT (key) DO NOTHING;
```

---

## Файлы к созданию / изменению

| Файл | Действие |
|------|---------|
| `mirror/core/memory/reranker.py` | Создать — BaseReranker, LLMReranker, CrossEncoderReranker, DisabledReranker, get_reranker() |
| `mirror/core/memory/context_budget.py` | Создать — ContextBudget |
| `mirror/core/memory/service.py` | **Изменить** — интеграция reranker + budget в search(); дедупликация в write_fact(); _update_access_stats() |
| `mirror/workers/tasks/memory.py` | Изменить — добавить decay_fact_importance task |
| `mirror/db/migrations/versions/024_memory_facts_access.py` | Создать — миграция |
| `mirror/db/seeds/llm_routing_stage2.py` | Дополнить — task_kind 'rerank' + app_config keys |

---

## Definition of Done

- [ ] Smoke-тест: 10 фактов о пользователе → запрос про работу → в топ-5 попадают только факты о работе
- [ ] Smoke-тест: факт с importance=0.9 всегда в контексте даже при нерелевантном запросе
- [ ] Smoke-тест: создание дублирующего факта (similarity > 0.92) → обновляет existing, не создаёт новый
- [ ] Context budget: 50 фактов → промпт не превышает MAX_MEMORY_TOKENS
- [ ] reranker_type='disabled' работает корректно (без reranking, без ошибок)
- [ ] decay_fact_importance запускается по расписанию и обновляет importance
- [ ] Логирование: `memory.search.reranked`, `memory.fact.deduplicated`, `memory.context.trimmed`
