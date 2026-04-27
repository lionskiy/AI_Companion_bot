# Этап 2 — Tracker

**Статус:** todo  
**Дата:** 2026-04-26

---

## Модули (по порядку реализации)

| № | Модуль | Статус | Файл |
|---|--------|--------|------|
| 17 | Глубокий retrieval | todo | 17-deep_retrieval_tracker.md |
| 16 | Психологические режимы и дневник | todo | 16-psychology_journal_tracker.md |
| 14 | Сонник | todo | 14-dreams_tracker.md |
| 15 | Нумерология | todo | 15-numerology_tracker.md |
| 13 | Золотой момент | todo | 13-onboarding_golden_moment_tracker.md |
| 18 | Проактивность | todo | 18-proactive_tracker.md |

---

## Общие задачи этапа

### Миграции (создать и применить строго по порядку)
- [ ] 020 — **ПЕРВАЯ**: расширение `fact_type` CHECK constraint + `source_mode` в `memory_episodes` + новые intents seed
- [ ] 021 — golden_moment поля + `preferred_name` + `registered_at` в `user_profiles`
- [ ] 022 — `life_path_number` в `user_profiles`
- [ ] 023 — `life_wheel_snapshots` + `journal_evening_time` + `journal_notifications_enabled`
- [ ] 024 — `access_count` + `last_accessed` в `memory_facts`
- [ ] 025 — `proactive_log` + `proactive_mode` + `quiet_hours_*` + `busy_probability` в `user_profiles`

### Seeds / Конфиги
- [ ] Новые task_kinds в `llm_routing` для всех 6 модулей
- [ ] Новые ключи в `app_config` для золотого момента, retrieval, проактивности

### Qdrant коллекции
- [ ] Создать `knowledge_dreams`
- [ ] Создать `knowledge_numerology`

### KB материалы
- [ ] Подготовить базу символов снов (resourses/knowledge_dreams/)
- [ ] Подготовить толкования чисел (resourses/knowledge_numerology/)
- [ ] Загрузить через KB ingest (module 12)

### Intent Router
- [ ] Добавить intents: `dream`, `numerology`, `psychology`, `journal`, `reflection`

### Приёмка этапа
- [ ] Все 6 модулей: smoke-тесты пройдены
- [ ] Policy §3.8 работает во всех новых режимах
- [ ] Все миграции применены в проде
- [ ] Документация обновлена в `docs/`
