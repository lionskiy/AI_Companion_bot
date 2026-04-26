# Module 15: Нумерология — Tracker

**Статус:** todo  
**Этап:** 2

---

## Задачи

### Инфраструктура
- [ ] Миграция 021: добавить `life_path_number` в `user_profiles`
- [ ] Создать Qdrant коллекцию `knowledge_numerology`
- [ ] Seed: добавить `numerology_interpret` в `llm_routing`
- [ ] Создать папку `resourses/knowledge_numerology/` с исходными материалами
- [ ] Загрузить толкования чисел 1-9, 11, 22, 33 через KB ingest

### NumerologyCalculator
- [ ] Реализовать `reduce(n)` — сведение к 1-9 с учётом мастер-чисел 11/22/33
- [ ] Реализовать `life_path(birth_date)`
- [ ] Реализовать `name_number(name)` — таблица Пифагора, русский + латинский
- [ ] Реализовать `personal_year(birth_date, year)`
- [ ] Реализовать `personal_month(birth_date, year, month)`
- [ ] Реализовать `personal_day(birth_date, today)`
- [ ] Покрыть единичными тестами: проверить несколько конкретных дат

### NumerologyService
- [ ] Реализовать `handle(state)` — основной обработчик
- [ ] Интеграция с OnboardingManager: запросить дату рождения если нет
- [ ] Сохранение life_path_number в user_profiles
- [ ] Сохранение как fact в memory_facts (fact_type='numerology')

### RAG
- [ ] Создать `mirror/rag/numerology.py` — search_numerology_knowledge

### Intent Router
- [ ] Добавить intent `numerology` в IntentRouter
- [ ] Добавить routing на NumerologyService в dialog_graph

### Тесты
- [ ] Unit-тест: 15.03.1990 → life_path = 1
- [ ] Unit-тест: мастер-числа 11, 22, 33 не сводятся дальше
- [ ] Smoke-тест: пользователь запрашивает нумерологию → полный расчёт
- [ ] Smoke-тест: без даты рождения → запрос через OnboardingManager
- [ ] Логи: `numerology.handle`, `numerology.calculated`
