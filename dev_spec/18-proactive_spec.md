# Module 18: Проактивность (бот пишет первым) — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §6.1–§6.6  
**Зависимости:** 03-memory, 07-astrology, 09-daily_ritual, 16-psychology_journal  
**Дата:** 2026-04-26

---

## Цель

Реализовать проактивное поведение бота — бот пишет первым без запроса пользователя. Это ключевой механизм удержания: пользователь помнит о боте, возвращается. Проактивность ощущается естественной, персонализированной, не навязчивой.

На этапе 2: базовые типы проактивных сообщений для Free-тарифа (ежедневный ритуал, чекин) + инфраструктура для платных типов.

---

## Acceptance Criteria

### Инфраструктура

- [ ] Система очереди кандидатов: периодически (каждые 30 мин) строится список кандидатов для каждого пользователя, каждому присваивается score
- [ ] Кандидат с max score отправляется если score > порога и не нарушает cooldown
- [ ] Глобальный лимит инициатив: не более N сообщений в сутки (N настраивается в app_config, default 2)
- [ ] Cooldown по типу: один тип не повторяется чаще чем раз в X часов (настраивается)
- [ ] `/quiet` — отключает все проактивные сообщения кроме daily_ritual (если явно включён)
- [ ] `/active` — максимальная проактивность
- [ ] Тихие часы: проактивные сообщения не отправляются с 23:00 до 08:00 (по часовому поясу пользователя)
- [ ] После 3+ проигнорированных инициатив подряд — частота автоматически снижается

### Типы сообщений (этап 2, все тарифы)

- [ ] **daily_ritual** — уже реализован в этапе 1, интегрировать в проактивный планировщик
- [ ] **emotional_checkin** — эмоциональный чекин после 2-3 дней молчания: «Эй, всё хорошо? Тебя не было давно»
- [ ] **astro_event** — уведомление о значимом транзите (Меркурий ретроградный, Венера в знаке и т.д.) — требует натальной карты
- [ ] **topic_continuation** — возврат к незакрытой теме из прошлого разговора (из memory_episodes)

### «Занят» + возврат (механика)

- [ ] При входящем сообщении от пользователя: с вероятностью `busy_probability` (default 3%, настраивается) бот отвечает что «занят»
- [ ] Через 5-40 мин (случайно) — бот возвращается и обрабатывает оригинальное сообщение
- [ ] «Занят» не срабатывает если пользователь молчал >24 часов
- [ ] «Занят» не срабатывает при кризисных сигналах (risk_level=crisis или risk_signal)
- [ ] «Занят» — только для тарифов Plus/Pro (в этапе 2 заготовка, активируется при монетизации)

---

## Архитектура

### ProactiveOrchestrator — масштабируемый подход

**НЕ** итерировать всех пользователей в одном task. Подход: очередь + батчи.

```python
@app.task
async def proactive_dispatch_batch(offset: int, batch_size: int = 500):
    """Обрабатывает один батч пользователей. Celery beat вызывает каждые 30 мин
    только первый батч; остальные запускаются chain'ом."""
    async with async_session_factory() as s:
        users = await s.execute(
            select(UserProfile.user_id, UserProfile.timezone,
                   UserProfile.proactive_mode, UserProfile.quiet_hours_start,
                   UserProfile.quiet_hours_end)
            .where(UserProfile.proactive_mode != 'quiet')
            # Только активные за последние 30 дней:
            .where(UserProfile.user_id.in_(
                select(MemoryEpisode.user_id)
                .where(MemoryEpisode.created_at > func.now() - text("interval '30 days'"))
                .distinct()
            ))
            .offset(offset).limit(batch_size)
        )
    orchestrator = ProactiveOrchestrator()
    for user in users.all():
        await orchestrator.process_user(user)
    # Запустить следующий батч если этот был полный
    if len(users.all()) == batch_size:
        proactive_dispatch_batch.delay(offset + batch_size, batch_size)

class ProactiveOrchestrator:
    async def process_user(self, user):
        if not await self._check_quiet_hours(user):
            return
        if await self._check_daily_limit(user.user_id):
            return
        candidates = await self._build_candidates(user.user_id)
        if not candidates:
            return
        best = max(candidates, key=lambda c: c.score)
        if best.score >= SCORE_THRESHOLD:
            await self._send(user.user_id, best)

    async def _build_candidates(self, user_id) -> list[ProactiveCandidate]:
        """Собирает кандидатов из всех типов и считает score."""
```

### ProactiveCandidate

```python
@dataclass
class ProactiveCandidate:
    type: str           # emotional_checkin | astro_event | topic_continuation | daily_ritual
    score: float        # итоговый score (0-1)
    context: dict       # данные для генерации текста
    cooldown_hours: int # минимум часов до повтора этого типа
```

### Скоринг кандидатов

```python
# emotional_checkin
days_silent = (now - last_user_message).days
if days_silent >= 2:
    score = min(0.9, 0.4 + days_silent * 0.1)
else:
    score = 0.0
# штраф если уже был недавно → но не ниже нуля
if recent_checkin_sent:
    score = max(0.0, score - 0.4)

# astro_event
score = event.significance * 0.8  # significance из AstrologyService
if not user_has_natal_chart:
    score = 0  # без натала не отправляем

# topic_continuation
last_episode = await memory.get_recent_episodes(user_id, limit=1)
if last_episode and not last_episode.resolved:
    score = last_episode.importance * 0.7
```

### Механика «занят»

```python
class BusyBehavior:
    BUSY_ACTIVITIES = [
        "была на прогулке", "читала кое-что интересное",
        "занималась медитацией", "помогала подруге",
        "смотрела закат", "немного задремала",
    ]

    async def maybe_intercept(self, user_id, message_text, bot) -> bool:
        """Вызывается ДО обработки входящего сообщения. Если True — сообщение не обрабатывается сейчас."""
        profile = await get_profile(user_id)
        if profile.tier not in ('plus', 'pro'):
            return False
        last_msg_time = await get_last_user_message_time(user_id)
        if (now - last_msg_time).total_seconds() > 86400:  # >24 часов
            return False
        # busy_probability = 0.03 по умолчанию (3% шанс "занята")
        if random.random() >= profile.busy_probability:   # >= означает: 97% случаев НЕ занята
            return False
        activity = random.choice(self.BUSY_ACTIVITIES)
        await bot.send_message(user_id, f"Сори, {activity}! Скоро вернусь 😊")
        # Сохранить в Redis: busy_pending:{user_id} = message_text, TTL=2400
        delay = random.randint(300, 2400)
        await schedule_return.apply_async(
            args=[user_id, message_text, activity],
            countdown=delay
        )
        return True
```

### Redis ключи

```
proactive:last_sent:{user_id}:{type}  → timestamp  TTL=cooldown_hours
proactive:daily_count:{user_id}:{date} → int        TTL=86400
proactive:ignored_streak:{user_id}    → int         TTL=7days
busy_pending:{user_id}                → message_text  TTL=2400
```

---

## Схема БД

```sql
-- История отправленных инициатив (аналитика + дедупликация)
CREATE TABLE proactive_log (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID REFERENCES users(id),
    type         VARCHAR(50) NOT NULL,
    score        FLOAT,
    delivered    BOOLEAN DEFAULT FALSE,
    opened       BOOLEAN DEFAULT FALSE,  -- пользователь ответил
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON proactive_log (user_id, created_at DESC);
CREATE INDEX ON proactive_log (type, created_at DESC);

-- Настройки проактивности пользователя
ALTER TABLE user_profiles
  ADD COLUMN proactive_mode       VARCHAR(20) DEFAULT 'normal',  -- quiet|normal|active
  ADD COLUMN quiet_hours_start    TIME DEFAULT '23:00',
  ADD COLUMN quiet_hours_end      TIME DEFAULT '08:00',
  ADD COLUMN busy_probability     FLOAT DEFAULT 0.03;
```

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `proactive_compose` | main_chat | Генерация текста инициативного сообщения |
| `proactive_return` | main_chat | Ответ после «занятости» |

---

## Celery tasks

```python
# Каждые 30 минут
@app.task
async def run_proactive_orchestrator():
    await ProactiveOrchestrator().run()

# По расписанию (delayed task через apply_async countdown)
@app.task
async def schedule_return(user_id: str, original_message: str, activity: str):
    """Отправляет возврат после «занятости» и обрабатывает оригинальное сообщение."""
    # 1. Найти bot и chat_id пользователя через channel_identities
    bot, chat_id = await _get_bot_and_chat(user_id)
    if not bot:
        return  # пользователь удалён
    # 2. Отправить "вернулась"
    await bot.send_message(chat_id, f"Вернулась! Была {activity} 😊")
    # 3. Обработать оригинальное сообщение через DialogService как обычное
    unified = UnifiedMessage(
        global_user_id=user_id, text=original_message,
        channel="telegram", chat_id=str(chat_id),
        session_id=await _get_session_id(user_id),
        metadata={"after_busy": True},
    )
    response = await dialog_service.handle(unified)
    await adapter.send(response, bot)
    # 4. Убрать pending ключ
    await redis.delete(f"busy_pending:{user_id}")
```

---

## Файлы к созданию / изменению

- `mirror/services/proactive/orchestrator.py` — ProactiveOrchestrator (новый)
- `mirror/services/proactive/candidates.py` — скоринг кандидатов (новый)
- `mirror/services/proactive/busy.py` — BusyBehavior (новый)
- `mirror/channels/telegram/handlers.py` — вызов BusyBehavior.maybe_intercept перед handle_message
- `mirror/workers/tasks/proactive.py` — Celery tasks (новый)
- `mirror/db/migrations/versions/024_proactive.py` — миграция
- `mirror/db/seeds/llm_routing_stage2.py` — новые task_kinds

---

## Definition of Done

- [ ] Smoke-тест: пользователь молчит 3 дня → emotional_checkin отправляется
- [ ] Smoke-тест: `/quiet` → инициативные сообщения прекращаются
- [ ] Smoke-тест: 3 игнорирования подряд → частота снижается
- [ ] Smoke-тест: тихие часы (23:00-08:00) — сообщения не отправляются
- [ ] Smoke-тест: busy=True → через 5-40 мин приходит возврат
- [ ] Глобальный лимит 2 сообщения в сутки соблюдается
- [ ] Policy §3.8: в кризисной ветке busy не срабатывает
- [ ] Логирование: `proactive.sent`, `proactive.ignored`, `proactive.busy_triggered`, `proactive.returned`
