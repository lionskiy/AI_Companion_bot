# Module 18: Проактивность — Tracker

**Статус:** todo  
**Этап:** 2

---

## Задачи

### Инфраструктура
- [ ] Миграция 024: создать таблицу `proactive_log`
- [ ] Миграция 024: добавить `proactive_mode`, `quiet_hours_start`, `quiet_hours_end`, `busy_probability` в `user_profiles`
- [ ] Seed: добавить `proactive_compose`, `proactive_return` в `llm_routing`
- [ ] Seed: добавить конфиги `proactive_daily_limit`, `proactive_score_threshold` в `app_config`

### ProactiveOrchestrator
- [ ] Создать `mirror/services/proactive/orchestrator.py`
- [ ] Реализовать `run()` — основной цикл по пользователям
- [ ] Реализовать `_build_candidates(user_id)` — список кандидатов
- [ ] Реализовать `_check_limits(user_id, type)` — cooldown + daily limit + тихие часы
- [ ] Реализовать `_send(user_id, candidate)` — отправка через bot

### Кандидаты (скоринг)
- [ ] Создать `mirror/services/proactive/candidates.py`
- [ ] `EmotionalCheckinCandidate` — скоринг по дням молчания
- [ ] `AstroEventCandidate` — скоринг по значимости транзита (интеграция с AstrologyService)
- [ ] `TopicContinuationCandidate` — скоринг по незакрытым темам из memory_episodes
- [ ] `DailyRitualCandidate` — перенести из daily_ritual в единую систему

### BusyBehavior
- [ ] Создать `mirror/services/proactive/busy.py`
- [ ] Реализовать `maybe_intercept(user_id, message_text, bot)` → bool
- [ ] Celery task `schedule_return(user_id, original_message, activity)`
- [ ] Redis ключ `busy_pending:{user_id}`, TTL=2400
- [ ] Блокировка при кризисной ветке

### Команды /quiet и /active
- [ ] `handle_quiet` — уже реализован, расширить: сохранять `proactive_mode='quiet'` в `user_profiles`
- [ ] `handle_active` — аналогично: `proactive_mode='active'`
- [ ] Учитывать `proactive_mode` в ProactiveOrchestrator

### Игнорирование — автоснижение частоты
- [ ] Redis ключ `proactive:ignored_streak:{user_id}`, TTL=7days
- [ ] При получении ответа на инициативное сообщение — сбросить счётчик
- [ ] При 3+ игнорированиях — снизить `busy_probability` и cooldown × 1.5

### Celery tasks
- [ ] `run_proactive_orchestrator` — каждые 30 минут (Celery beat)
- [ ] `schedule_return` — отложенная задача

### Интеграция
- [ ] `mirror/channels/telegram/handlers.py` — вызов `BusyBehavior.maybe_intercept` перед обработкой сообщения

### Тесты
- [ ] Smoke-тест: молчание 3 дня → emotional_checkin отправляется
- [ ] Smoke-тест: `/quiet` → инициативы прекращаются
- [ ] Smoke-тест: 23:30 → сообщение не отправляется (тихие часы)
- [ ] Smoke-тест: daily_limit=2 → третье сообщение не отправляется
- [ ] Smoke-тест: busy mock → через N секунд возврат
- [ ] Smoke-тест: кризисная ветка → busy не срабатывает
- [ ] Логи: `proactive.sent`, `proactive.ignored`, `proactive.busy_triggered`, `proactive.returned`
