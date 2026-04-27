# Module 17: Глубокий retrieval — Tracker

**Статус:** todo  
**Этап:** 2

---

## Задачи

### Инфраструктура
- [ ] Миграция 023: добавить `access_count`, `last_accessed` в `memory_facts`
- [ ] Seed: добавить `rerank` в `llm_routing`
- [ ] Seed: добавить конфиги `reranker_type`, `max_memory_tokens`, `pinned_importance_threshold`, `fact_dedup_threshold` в `app_config`

### Reranker
- [ ] Создать `mirror/core/memory/reranker.py`
- [ ] Реализовать `LLMReranker.score(query, candidates)` — батч LLM оценка
- [ ] Реализовать `CrossEncoderReranker.score(query, candidates)` — локальная модель
- [ ] Реализовать `DisabledReranker.score()` — заглушка, возвращает единицы
- [ ] Фабрика: выбор реализации по `app_config.reranker_type`

### ContextBudget
- [ ] Создать `mirror/core/memory/context_budget.py`
- [ ] Реализовать `fit(facts, episodes)` — pinned facts первыми, затем по score, обрезать по токенам
- [ ] Подсчёт токенов: через tiktoken или простой len(text) / 4

### MemoryService — улучшения
- [ ] `search()`: увеличить первичный Qdrant запрос (top-15 facts, top-10 episodes)
- [ ] `search()`: интегрировать Reranker после первичного поиска
- [ ] `search()`: добавить pinned facts (importance ≥ threshold)
- [ ] `search()`: применить ContextBudget в конце
- [ ] `search()`: обновлять `access_count` и `last_accessed` для использованных записей
- [ ] `write_fact()`: дедупликация — поиск по Qdrant перед записью, обновление если similarity > threshold

### Celery tasks
- [ ] `decay_fact_importance` — еженедельно снижать importance у неиспользуемых фактов

### Тесты
- [ ] Unit-тест: 10 разных фактов → запрос про работу → только факты о работе в топ
- [ ] Unit-тест: importance=0.9 → всегда в контексте
- [ ] Unit-тест: дублирующий факт → обновляет existing
- [ ] Unit-тест: 50 фактов → ContextBudget обрезает до лимита
- [ ] Unit-тест: reranker_type='disabled' → работает без ошибок
- [ ] Логи: `memory.search.reranked`, `memory.fact.deduplicated`, `memory.context.trimmed`
