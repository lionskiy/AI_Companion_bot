# Module 16: Психологические режимы и Дневник — Tracker

**Статус:** todo  
**Этап:** 2

---

## Задачи

### Инфраструктура
- [ ] Миграция 022: создать таблицу `life_wheel_snapshots`
- [ ] Миграция 022: добавить `journal_evening_time`, `journal_notifications_enabled` в `user_profiles`
- [ ] Seed: добавить task_kinds `psychology_cbt`, `psychology_values`, `psychology_narrative`, `journal_analyze`, `journal_monthly_synthesis`, `life_wheel` в `llm_routing`

### PsychologyService
- [ ] Реализовать `handle(state)` — диспетчер по sub-intent
- [ ] Реализовать `handle_cbt(state)` — 5-шаговый CBT дневник мыслей
- [ ] Реализовать `handle_wheel(state)` — 8 вопросов + сохранение + сравнение с предыдущим
- [ ] Реализовать `handle_values(state)` — работа с ценностями (ACT)
- [ ] Реализовать `handle_narrative(state)` — нарративная практика
- [ ] Реализовать `save_practice_result()` — сохранение в memory_facts с нужным fact_type
- [ ] Промежуточное состояние практик в Redis: `practice_state:{user_id}`, TTL=3600
- [ ] Обработка `/cancel` на любом шаге практики

### JournalService
- [ ] Реализовать `save_entry(user_id, text, source)` — сохранение в memory_episodes с source_mode='journal'
- [ ] Реализовать `search_entries(user_id, query)` — RAG поиск по journal-эпизодам
- [ ] Реализовать `evening_reflection_prompt(user_id)` — 3 вопроса
- [ ] Реализовать `monthly_synthesis(user_id, month, year)` — LLM резюме месяца

### Celery tasks
- [ ] `send_evening_reflection` — ежедневно в настраиваемое время
- [ ] `generate_monthly_synthesis` — 1-го числа каждого месяца

### Intent Router
- [ ] Добавить intents `psychology`, `journal`, `reflection` в IntentRouter
- [ ] Добавить routing на новые сервисы в dialog_graph

### Тесты
- [ ] Smoke-тест: «хочу записать в дневник» → запись в memory_episodes
- [ ] Smoke-тест: CBT — все 5 шагов → результат в memory_facts
- [ ] Smoke-тест: колесо жизни — повторный прогон сравнивает с предыдущим
- [ ] Smoke-тест: `/cancel` на шаге 3 → корректный выход
- [ ] Smoke-тест: кризисный сигнал внутри CBT → Policy §3.8 срабатывает
- [ ] Логи: `psychology.handle`, `journal.entry_saved`, `journal.synthesis_generated`
