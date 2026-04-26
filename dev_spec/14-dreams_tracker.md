# Module 14: Сонник — Tracker

**Статус:** todo  
**Этап:** 2

---

## Задачи

### Инфраструктура
- [ ] Создать Qdrant коллекцию `knowledge_dreams`
- [ ] Seed: добавить `dream_extract_symbols`, `dream_interpret` в `llm_routing`
- [ ] Создать папку `resourses/knowledge_dreams/` с исходными материалами
- [ ] Загрузить базу символов снов через KB ingest (минимум 200 символов)

### DreamsService
- [ ] Реализовать `extract_symbols(dream_text)` — LLM извлекает символы
- [ ] Реализовать `get_moon_context(date)` — лунный день и фаза
- [ ] Реализовать `search_dream_kb(symbols)` — RAG поиск по knowledge_dreams
- [ ] Реализовать `save_dream(user_id, text, symbols, context)` — сохранение в memory_episodes
- [ ] Реализовать `check_patterns(user_id, symbols)` — поиск повторяющихся образов
- [ ] Реализовать `handle(state)` — основной обработчик

### RAG
- [ ] Создать `mirror/rag/dreams.py` — search_dream_knowledge по аналогии с rag/psych.py

### Intent Router
- [ ] Добавить intent `dream` в IntentRouter
- [ ] Добавить routing на DreamsService в dialog_graph

### Тесты и логирование
- [ ] Smoke-тест: пользователь описывает сон → интерпретация с символами
- [ ] Smoke-тест: сон сохраняется в memory_episodes с source_mode='dream'
- [ ] Smoke-тест: 3+ повторения символа → бот замечает паттерн
- [ ] Логи: `dreams.handle`, `dreams.symbols_extracted`, `dreams.pattern_detected`
