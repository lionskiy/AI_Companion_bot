# Module 13: Онбординг «Золотой момент» — Tracker

**Статус:** todo  
**Этап:** 2

---

## Задачи

### Инфраструктура
- [ ] Миграция 020: добавить поля `golden_moment_pending`, `golden_moment_shown_at`, `preferred_name`, `partner_birth_date` в `user_profiles`
- [ ] Seed: добавить `golden_moment`, `onboarding_question` в таблицу `llm_routing`
- [ ] Seed: добавить конфиги `golden_moment_threshold`, `golden_moment_t_max_days`, `golden_moment_cta` в `app_config`

### GoldenMomentService
- [ ] Реализовать `compute_readiness_score(user_id)`
- [ ] Реализовать `check_and_trigger(user_id, state)` — проверка условий и установка флага
- [ ] Реализовать `build_insight(user_id, facts, profile)` — LLM-генерация инсайта
- [ ] Реализовать `mark_shown(user_id)` — сброс флага, запись `golden_moment_shown_at`
- [ ] Обработка временного потолка T_max

### OnboardingManager
- [ ] Реализовать проверку: нужен ли следующий онбординг-вопрос
- [ ] Вопрос об имени после 3-й сессии / 20 сообщений
- [ ] Вопрос о дате рождения при первом запросе астрологии/нумерологии
- [ ] Вопрос о партнёре при упоминании синастрии
- [ ] Идемпотентность: не переспрашивать уже заполненные поля

### Интеграция в диалог
- [ ] Вызов `check_and_trigger` в `DialogService.handle()` после получения ответа
- [ ] Вставка golden_moment как отдельного сообщения (не прерывает основной ответ)
- [ ] Блокировка в кризисной ветке (risk_level=crisis)

### Тесты и логирование
- [ ] Smoke-тест: readiness_score растёт с каждым сообщением
- [ ] Smoke-тест: golden_moment показывается 1 раз
- [ ] Smoke-тест: в кризисной ветке не показывается
- [ ] Логи: `golden_moment.triggered`, `golden_moment.shown`, `onboarding.question_sent`
