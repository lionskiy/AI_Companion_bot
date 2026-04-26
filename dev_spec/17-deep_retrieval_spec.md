# Module 17: Глубокий retrieval (Rerank + Приоритеты памяти) — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §9.2, §9.3, §9.4  
**Зависимости:** 03-memory, 05-llm_router  
**Дата:** 2026-04-26

---

## Цель

Улучшить качество контекста который подаётся в LLM при каждом ответе:
1. **Reranking** — после первичного поиска по Qdrant переранжировать результаты через cross-encoder или LLM-скоринг, чтобы в промпт попадали реально релевантные факты/эпизоды, а не просто ближайшие по вектору
2. **Приоритеты по importance** — факты с высокой важностью (importance > 0.85) всегда включаются в контекст (pinned facts), остальные — по релевантности
3. **Дедупликация фактов** — при извлечении новых фактов проверять similarity с существующими (порог 0.92), обновлять вместо создания дубликатов
4. **Context budget** — контролировать итоговый размер контекста (токены), чтобы не превышать лимит промпта

---

## Acceptance Criteria

- [ ] `MemoryService.search()` возвращает результаты отсортированные по `final_score = vector_score × rerank_score × importance`
- [ ] Pinned facts (importance ≥ 0.85) всегда включаются в контекст независимо от релевантности запросу
- [ ] Context budget: суммарный размер facts + episodes в промпте не превышает `MAX_MEMORY_TOKENS` (настраивается в app_config, default 1500)
- [ ] При сохранении нового факта: поиск по Qdrant (top-5 ближайших для user_id) → если similarity > 0.92 → обновить existing, не создавать новый
- [ ] Reranker работает как опциональный компонент: если отключён (конфиг) — используется только vector score
- [ ] Importance обновляется автоматически: +0.05 за каждое обращение к факту (access_count), −0.02 за 30 дней без обращения (Celery task)
- [ ] `access_count` и `last_accessed` обновляются при каждом использовании факта/эпизода в промпте
- [ ] Новые поля `access_count`, `last_accessed` добавлены в `memory_facts` (в `memory_episodes` уже есть по POD §9.5)
- [ ] Smoke-тест показывает что reranking улучшает порядок результатов на тестовом наборе

---

## Архитектура

### Схема поиска с rerankingом

```
query_text
    ↓ embed (LLMRouter.embed)
    → Qdrant search user_facts (top-15, filter user_id)
    → Qdrant search user_episodes (top-10, filter user_id)
    ↓ candidate list (25 items)
    → Reranker.score(query, candidates)   # cross-encoder или LLM
    → sort by final_score
    → pick top-5 facts + top-3 episodes
    + always add pinned facts (importance ≥ 0.85)
    → deduplicate by id
    → trim to MAX_MEMORY_TOKENS budget
    → return MemoryContext
```

### Reranker (две реализации)

```python
class LLMReranker:
    """Использует LLM для оценки релевантности. Точнее, дороже."""
    async def score(self, query: str, candidates: list[str]) -> list[float]:
        # Батч-запрос: "оцени релевантность каждого факта к запросу, от 0 до 1"
        # task_kind = 'rerank'

class CrossEncoderReranker:
    """Использует локальную cross-encoder модель. Быстрее, дешевле."""
    # sentence-transformers/ms-marco-MiniLM-L-6-v2 или аналог
    def score(self, query: str, candidates: list[str]) -> list[float]: ...
```

Конфигурация через `app_config.reranker_type`: `'llm'` | `'cross_encoder'` | `'disabled'`

### Context budget

```python
class ContextBudget:
    MAX_TOKENS: int = 1500  # из app_config

    def fit(self, facts: list[dict], episodes: list[dict]) -> tuple[list, list]:
        """Обрезает списки чтобы уложиться в бюджет токенов."""
        total = 0
        result_facts, result_episodes = [], []
        # Pinned facts первыми (importance ≥ 0.85)
        # Затем по final_score пока бюджет не исчерпан
```

### Importance decay (Celery)

```python
@app.task
# Запускается еженедельно
async def decay_fact_importance():
    # UPDATE memory_facts
    # SET importance = GREATEST(0.1, importance - 0.02)
    # WHERE last_accessed < NOW() - INTERVAL '30 days'
    # AND importance > 0.1
```

---

## Схема БД

```sql
-- Добавить в memory_facts:
ALTER TABLE memory_facts
  ADD COLUMN access_count   INTEGER DEFAULT 0,
  ADD COLUMN last_accessed  TIMESTAMPTZ;

-- Индекс для pinned facts:
CREATE INDEX ON memory_facts (user_id, importance DESC)
  WHERE archived = FALSE;
```

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `rerank` | main_chat | Оценка релевантности кандидатов (если reranker_type='llm') |

---

## Новые конфиги (app_config)

| Ключ | Default | Описание |
|------|---------|---------|
| `reranker_type` | `disabled` | Тип rerankera: disabled/llm/cross_encoder |
| `max_memory_tokens` | `1500` | Бюджет токенов на память в промпте |
| `pinned_importance_threshold` | `0.85` | Порог для всегда-включаемых фактов |
| `fact_dedup_threshold` | `0.92` | Порог similarity для дедупликации фактов |

---

## Файлы к созданию / изменению

- `mirror/core/memory/reranker.py` — Reranker классы (новый)
- `mirror/core/memory/context_budget.py` — ContextBudget (новый)
- `mirror/core/memory/service.py` — интеграция reranker + budget в search()
- `mirror/core/memory/service.py` — дедупликация в write_fact()
- `mirror/workers/tasks/memory.py` — decay_fact_importance Celery task
- `mirror/db/migrations/versions/023_memory_facts_access.py` — миграция
- `mirror/db/seeds/llm_routing_stage2.py` — task_kind rerank

---

## Definition of Done

- [ ] Smoke-тест: 10 фактов о пользователе → запрос про работу → в топ попадают только факты о работе
- [ ] Smoke-тест: fact с importance=0.9 всегда в контексте даже при нерелевантном запросе
- [ ] Smoke-тест: создание дублирующего факта → обновляет existing, не создаёт новый
- [ ] Context budget: промпт с 50 фактами не превышает MAX_MEMORY_TOKENS
- [ ] reranker_type='disabled' работает корректно (без reranking)
- [ ] Логирование: `memory.search.reranked`, `memory.fact.deduplicated`, `memory.context.trimmed`
