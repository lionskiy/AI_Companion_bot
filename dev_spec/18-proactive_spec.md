# Module 18: Проактивность (бот пишет первым) — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §6.1–§6.6  
**Зависимости:** 03-memory, 07-astrology, 09-daily_ritual, 16-psychology_journal  
**Дата:** 2026-04-26

---

## Цель

Реализовать проактивное поведение бота — бот пишет первым без запроса пользователя. Проактивность ощущается естественной, персонализированной, не навязчивой.

На этапе 2: базовые типы проактивных сообщений (ежедневный ритуал, чекин, продолжение темы) + инфраструктура для астро-событий.

---

## Acceptance Criteria

### Инфраструктура

- [ ] Batched Celery task каждые 30 мин строит список кандидатов (batch_size=500), каждому присваивается score
- [ ] Кандидат с max score отправляется если score > `proactive_score_threshold` (default 0.5, настраивается в app_config)
- [ ] Глобальный лимит: не более `proactive_daily_limit` сообщений в сутки (default 2)
- [ ] Cooldown по типу: один тип не повторяется раньше cooldown (см. таблицу ниже)
- [ ] `/quiet` — устанавливает `proactive_mode='quiet'` + `journal_notifications_enabled=False`
- [ ] `/active` — устанавливает `proactive_mode='active'`
- [ ] Тихие часы: сообщения не отправляются между `quiet_hours_start` и `quiet_hours_end` (по timezone пользователя)
- [ ] После 3+ проигнорированных инициатив подряд — интервал увеличивается в 2 раза (floor: 1 в неделю)
- [ ] «Игнорирование» = пользователь не ответил в течение 24 часов после отправки инициативы

### Типы сообщений

- [ ] **daily_ritual** — интегрируется в ProactiveOrchestrator (не удаляет существующий task)
- [ ] **emotional_checkin** — чекин после 2+ дней молчания
- [ ] **topic_continuation** — возврат к незакрытой теме из памяти
- [ ] **astro_event** — уведомление о транзите (только если есть натальная карта)

### «Занят» (BusyBehavior)

- [ ] С вероятностью `busy_probability` (default 3%) бот «занят» — отвечает что занята и возвращается через 5-40 мин
- [ ] «Занят» не срабатывает если пользователь молчал > 24 часов
- [ ] «Занят» не срабатывает при risk_level=crisis или risk_signal
- [ ] «Занят» — только для тарифов Plus/Pro (заготовка; активируется при монетизации этапа 3)

---

## Архитектура

### ProactiveOrchestrator

```python
@celery_app.task(
    name="mirror.workers.tasks.proactive.proactive_dispatch_batch",
    bind=True,
    max_retries=2,
    soft_time_limit=300,  # 5 мин на батч
)
def proactive_dispatch_batch(self, offset: int = 0, batch_size: int = 500):
    asyncio.run(_dispatch_batch(offset, batch_size))

async def _dispatch_batch(offset: int, batch_size: int) -> None:
    await ensure_db_pool()
    async with get_session() as session:
        users = await session.execute(
            select(
                UserProfile.user_id, UserProfile.timezone, UserProfile.proactive_mode,
                UserProfile.quiet_hours_start, UserProfile.quiet_hours_end,
            )
            .where(UserProfile.proactive_mode != 'quiet')
            .where(UserProfile.user_id.in_(
                select(MemoryEpisode.user_id)
                .where(MemoryEpisode.created_at > func.now() - text("interval '30 days'"))
                .distinct()
            ))
            .offset(offset).limit(batch_size)
        )
    rows = users.all()
    orchestrator = ProactiveOrchestrator()
    for row in rows:
        try:
            await orchestrator.process_user(row)
        except Exception:
            logger.warning("proactive.process_user_failed", user_id=str(row.user_id))

    # Цепочка: если батч был полный — запустить следующий
    if len(rows) == batch_size:
        proactive_dispatch_batch.apply_async(kwargs={"offset": offset + batch_size, "batch_size": batch_size})
```

### ProactiveOrchestrator

```python
class ProactiveOrchestrator:
    def __init__(self, llm_router, memory_service) -> None:
        self._llm_router = llm_router
        self._memory_service = memory_service

    async def process_user(self, user: Row) -> None:
        if not await self._in_quiet_hours(user):
            return
        if await self._daily_limit_reached(user.user_id):
            return
        # Lazy eval — читаем из БД при каждом вызове, не при импорте
        threshold = float(get_app_config("proactive_score_threshold", "0.5"))
        candidates = await self._build_candidates(user.user_id)
        if not candidates:
            return
        best = max(candidates, key=lambda c: c.score)
        if best.score >= threshold:
            await self._send(user.user_id, best)

    async def _in_quiet_hours(self, user: Row) -> bool:
        """Возвращает True если СЕЙЧАС вне тихих часов (можно отправлять)."""
        import zoneinfo
        try:
            tz = zoneinfo.ZoneInfo(user.timezone or "Europe/Moscow")
            local_now = datetime.now(tz).time()
            start = user.quiet_hours_start or time(23, 0)
            end = user.quiet_hours_end or time(8, 0)
            # Учитываем переход через полночь (23:00 - 08:00)
            if start > end:
                return not (local_now >= start or local_now < end)
            return not (start <= local_now < end)
        except Exception:
            return True  # при ошибке — не блокируем

    async def _daily_limit_reached(self, user_id: UUID) -> bool:
        count_key = f"proactive:daily_count:{user_id}:{date.today().isoformat()}"
        count = int(await redis.get(count_key) or 0)
        limit = int(get_app_config("proactive_daily_limit", "2"))
        return count >= limit

    async def _build_candidates(self, user_id: UUID) -> list["ProactiveCandidate"]:
        candidates = []
        candidates += await self._score_emotional_checkin(user_id)
        candidates += await self._score_topic_continuation(user_id)
        candidates += await self._score_astro_event(user_id)
        return [c for c in candidates if c.score > 0]

    async def _send(self, user_id: UUID, candidate: "ProactiveCandidate") -> None:
        text = await self._compose(user_id, candidate)
        await _deliver_to_user(user_id, text)
        # Обновить Redis
        count_key = f"proactive:daily_count:{user_id}:{date.today().isoformat()}"
        await redis.incr(count_key)
        await redis.expire(count_key, 86400)
        cooldown_key = f"proactive:last_sent:{user_id}:{candidate.type}"
        await redis.setex(cooldown_key, candidate.cooldown_hours * 3600, datetime.utcnow().isoformat())
        # Логировать в proactive_log
        await _log_proactive(user_id, candidate.type, candidate.score)
        logger.info("proactive.sent", user_id=str(user_id), type=candidate.type, score=candidate.score)

    async def _compose(self, user_id: UUID, candidate: "ProactiveCandidate") -> str:
        """Генерирует текст инициативного сообщения через LLM (task_kind='proactive_compose')."""
        import json
        memory = await self._memory_service.search(user_id, query=candidate.type, top_k=3)
        facts_snippet = [f["value"] for f in memory.get("facts", [])[:3]]
        return await self._llm_router.complete(
            task_kind="proactive_compose",
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "type": candidate.type,
                    "context": candidate.context,
                    "memory_facts": facts_snippet,
                }, ensure_ascii=False),
            }],
        )
```

### ProactiveCandidate

```python
@dataclass
class ProactiveCandidate:
    type: str           # emotional_checkin | astro_event | topic_continuation | daily_ritual
    score: float        # итоговый score 0.0-1.0
    context: dict       # данные для генерации текста (разные для каждого type)
    cooldown_hours: int # минимум часов до повтора этого типа
```

### Cooldown по типу

| Тип | cooldown_hours | Описание |
|-----|----------------|---------|
| `emotional_checkin` | 72 | Не чаще раза в 3 дня |
| `topic_continuation` | 48 | Не чаще раза в 2 дня |
| `astro_event` | 24 | Не чаще раза в сутки |
| `daily_ritual` | 20 | Ежедневный ритуал — ~раз в день |

### Скоринг кандидатов

```python
async def _score_emotional_checkin(self, user_id: UUID) -> list[ProactiveCandidate]:
    last_msg = await _get_last_user_message_time(user_id)
    if last_msg is None:
        return []
    days_silent = (datetime.utcnow() - last_msg).days
    if days_silent < 2:
        return []
    score = min(0.9, 0.4 + days_silent * 0.1)
    # Штраф если недавно уже отправляли checkin
    if await redis.exists(f"proactive:last_sent:{user_id}:emotional_checkin"):
        score = max(0.0, score - 0.4)
    if score <= 0:
        return []
    return [ProactiveCandidate(
        type="emotional_checkin",
        score=score,
        context={"days_silent": days_silent},
        cooldown_hours=72,
    )]

async def _score_topic_continuation(self, user_id: UUID) -> list[ProactiveCandidate]:
    # Берём последний эпизод из памяти (не journal, не dream)
    last_ep = await _get_last_episode(user_id, exclude_source_modes=["journal", "dream"])
    if not last_ep:
        return []
    days_since = (datetime.utcnow() - last_ep.created_at).days
    if days_since < 1 or days_since > 7:
        return []
    score = last_ep.importance * 0.7
    if await redis.exists(f"proactive:last_sent:{user_id}:topic_continuation"):
        score = max(0.0, score - 0.3)
    if score <= 0:
        return []
    return [ProactiveCandidate(
        type="topic_continuation",
        score=score,
        context={"episode_summary": last_ep.summary[:200]},
        cooldown_hours=48,
    )]

async def _score_astro_event(self, user_id: UUID) -> list[ProactiveCandidate]:
    # Требует натальной карты — без неё score=0
    has_natal = await _user_has_natal_chart(user_id)
    if not has_natal:
        return []
    event = await astrology_service.get_significant_transit(user_id)
    if not event:
        return []
    score = event.significance * 0.8  # significance 0-1 из AstrologyService
    return [ProactiveCandidate(
        type="astro_event",
        score=score,
        context={"event": event.description, "planet": event.planet},
        cooldown_hours=24,
    )]
```

### Игнорирование и снижение частоты

```python
# Вызывается при получении любого сообщения от пользователя в telegram/handlers.py:
async def _update_ignored_streak(user_id: UUID) -> None:
    """
    Если у пользователя было pending proactive сообщение (sent < 24h назад, нет reply) — 
    он ответил сейчас, сбрасываем streak.
    Если streak >= 3 — удваиваем все cooldown'ы через временный Redis-модификатор.
    """
    streak_key = f"proactive:ignored_streak:{user_id}"
    # При получении ответа — сбрасываем streak
    await redis.delete(streak_key)

# Вызывается в proactive_dispatch_batch перед отправкой:
async def _check_ignored_streak(user_id: UUID) -> int:
    streak = int(await redis.get(f"proactive:ignored_streak:{user_id}") or 0)
    return streak

# После отправки и отсутствия ответа в течение 24 часов — проверяем:
# Вызывается в начале _dispatch_batch перед process_user для каждого пользователя.
async def _maybe_increment_ignored_streak(user_id: UUID, candidate_type: str) -> None:
    last_sent = await redis.get(f"proactive:last_sent:{user_id}:{candidate_type}")
    if not last_sent:
        return
    sent_at = datetime.fromisoformat(last_sent)
    # Игнорирование = прошло > 24h с отправки И пользователь не ответил после отправки
    if (datetime.utcnow() - sent_at).total_seconds() < 86400:
        return  # менее 24ч — ещё рано судить
    # Проверяем: написал ли пользователь что-либо ПОСЛЕ отправки
    last_reply = await redis.get(f"user:last_message_time:{user_id}")
    if last_reply:
        reply_at = datetime.fromisoformat(last_reply)
        if reply_at > sent_at:
            return  # пользователь ответил — не игнор
    # Пользователь не ответил за 24ч — это игнорирование
    streak_key = f"proactive:ignored_streak:{user_id}"
    await redis.incr(streak_key)
    await redis.expire(streak_key, 604800)
    logger.info("proactive.ignored", user_id=str(user_id), type=candidate_type)

# ВАЖНО: user:last_message_time обновляется в telegram/handlers.py
# при каждом входящем сообщении от пользователя:
# await redis.setex(f"user:last_message_time:{uid}", 2592000, datetime.utcnow().isoformat())
# (TTL 30 дней)
```

При `ignored_streak >= 3`: умножить cooldown_hours кандидата на 2. При `ignored_streak >= 6`: умножить на 4. Floor — кандидат с cooldown 72ч при streak=3 не отправляется чаще 1 раза в неделю.

### Вспомогательные функции (mirror/services/proactive/helpers.py)

```python
async def _get_last_user_message_time(user_id: UUID) -> datetime | None:
    """Время последнего сообщения от пользователя. Redis-first, DB-fallback."""
    cached = await redis.get(f"user:last_message_time:{user_id}")
    if cached:
        return datetime.fromisoformat(cached)
    async with get_session() as session:
        row = await session.execute(
            select(func.max(MemoryEpisode.created_at)).where(MemoryEpisode.user_id == user_id)
        )
        return row.scalar()

async def _get_last_episode(
    user_id: UUID, exclude_source_modes: list[str]
) -> "MemoryEpisode | None":
    async with get_session() as session:
        row = await session.execute(
            select(MemoryEpisode)
            .where(MemoryEpisode.user_id == user_id)
            .where(MemoryEpisode.source_mode.notin_(exclude_source_modes))
            .order_by(MemoryEpisode.created_at.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()

async def _user_has_natal_chart(user_id: UUID) -> bool:
    async with get_session() as session:
        row = await session.execute(
            select(UserProfile.natal_data).where(UserProfile.user_id == user_id)
        )
        return bool(row.scalar_one_or_none())

async def _get_profile(user_id: UUID) -> "UserProfile":
    async with get_session() as session:
        return await session.get(UserProfile, user_id)

async def _get_bot_token_for_user(user_id: UUID) -> str | None:
    """Возвращает telegram bot token для пользователя (из таблицы tg_bots)."""
    async with get_session() as session:
        row = await session.execute(
            select(TgBot.token)
            .join(ChannelIdentity, ChannelIdentity.tg_bot_id == TgBot.id)
            .where(ChannelIdentity.user_id == user_id)
            .where(ChannelIdentity.channel == "telegram")
        )
        result = row.first()
    return result.token if result else None

async def _deliver_to_user(user_id: UUID, text: str) -> None:
    """Отправляет сообщение пользователю через его Telegram bot (HTTP API напрямую)."""
    async with get_session() as session:
        row = await session.execute(
            select(ChannelIdentity.channel_user_id)
            .where(ChannelIdentity.user_id == user_id)
            .where(ChannelIdentity.channel == "telegram")
        )
        identity = row.first()
    if not identity:
        return
    bot_token = await _get_bot_token_for_user(user_id)
    if not bot_token:
        return
    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={"chat_id": int(identity.channel_user_id), "text": text})

async def _log_proactive(user_id: UUID, proactive_type: str, score: float) -> None:
    async with get_session() as session:
        await session.execute(
            insert(ProactiveLog).values(user_id=user_id, type=proactive_type, score=score)
        )
        await session.commit()

async def _get_session_id(user_id: UUID) -> str:
    """Возвращает session_id для Celery-контекста (нет активной сессии)."""
    return f"{user_id}:proactive"
```

### Механика «занят»

```python
class BusyBehavior:
    # Тексты localizable — хранить в app_config или enum
    BUSY_ACTIVITIES = [
        "была на прогулке", "читала кое-что интересное",
        "занималась медитацией", "помогала подруге",
        "смотрела закат", "немного задремала",
    ]

    async def maybe_intercept(self, user_id: UUID, message_text: str, bot: Bot, chat_id: int) -> bool:
        """
        Вызывается ДО обработки входящего сообщения, в telegram/handlers.py:
            if await busy_behavior.maybe_intercept(uid, unified.text, bot, message.chat.id):
                return  # сообщение обработано позже

        Возвращает True если сообщение перехвачено (пользователю ответили "занята").
        """
        profile = await _get_profile(user_id)
        if profile.tier not in ('plus', 'pro'):  # Только Plus/Pro (этап 3)
            return False
        last_msg_time = await _get_last_user_message_time(user_id)
        if last_msg_time and (datetime.utcnow() - last_msg_time).total_seconds() > 86400:
            return False  # молчал > 24ч — не перехватываем
        # Проверка policy — при кризисе не перехватываем
        policy = await policy_engine.check(user_id, message_text)
        if policy.risk_level in ("crisis", "risk_signal"):
            return False
        busy_prob = profile.busy_probability or 0.03
        if random.random() >= busy_prob:  # 97% случаев — НЕ занята
            return False

        activity = random.choice(self.BUSY_ACTIVITIES)
        await bot.send_message(chat_id, f"Сори, {activity}! Скоро вернусь 😊")
        # Сохранить оригинальное сообщение в Redis
        await redis.setex(f"busy_pending:{user_id}", 2400, message_text)
        # Запланировать возврат через 5-40 мин
        delay = random.randint(300, 2400)
        schedule_return.apply_async(
            args=[str(user_id), str(chat_id), message_text, activity],
            countdown=delay,
        )
        return True
```

**Интеграция в telegram/handlers.py:**
```python
# В handle_message (обычный текстовый handler) — ПЕРЕД dialog_service.handle():
uid = UUID(unified.global_user_id)

# Обновляем Redis timestamp — нужен для _maybe_increment_ignored_streak
await redis.setex(f"user:last_message_time:{uid}", 2592000, datetime.utcnow().isoformat())

# Сбросить ignored_streak — пользователь отвечает, значит видит сообщения
await _update_ignored_streak(uid)

if await busy_behavior.maybe_intercept(uid, unified.text, bot, message.chat.id):
    return  # сообщение будет обработано позже через schedule_return

# Команды /quiet и /active
@router.message(Command("quiet"))
async def handle_quiet(message: Message) -> None:
    uid = await _get_user_id(message)
    async with get_session() as session:
        await session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == uid)
            .values(proactive_mode='quiet', journal_notifications_enabled=False)
        )
        await session.commit()
    await message.answer("Понял, буду тише. Напиши /active чтобы включить снова.")

@router.message(Command("active"))
async def handle_active(message: Message) -> None:
    uid = await _get_user_id(message)
    async with get_session() as session:
        await session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == uid)
            .values(proactive_mode='active', journal_notifications_enabled=True)
        )
        await session.commit()
    await message.answer("Отлично! Буду на связи активнее 😊")
```

**Примечание:** `opened=True` в `proactive_log` — устанавливается при ответе пользователя на инициативное сообщение (future feature). На этапе 2 `opened` всегда FALSE; UPDATE будет добавлен в этапе 3 при наличии reply tracking.

### Celery task schedule_return

```python
@celery_app.task(
    name="mirror.workers.tasks.proactive.schedule_return",
    bind=True,
    max_retries=2,
)
def schedule_return(self, user_id_str: str, chat_id_str: str, original_message: str, activity: str):
    asyncio.run(_do_return(user_id_str, chat_id_str, original_message, activity))

async def _do_return(user_id_str: str, chat_id_str: str, original_message: str, activity: str) -> None:
    await ensure_db_pool()
    user_id = UUID(user_id_str)

    # Проверить что сообщение всё ещё pending (пользователь не написал сам)
    pending = await redis.get(f"busy_pending:{user_id}")
    if not pending:
        return  # пользователь успел написать снова — не нужно возвращаться

    bot_token = await _get_bot_token_for_user(user_id)
    if not bot_token:
        return

    # Отправить "вернулась"
    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={"chat_id": int(chat_id_str), "text": f"Вернулась! Была {activity} 😊"})

    # Обработать оригинальное сообщение через DialogService
    from mirror.channels.base import UnifiedMessage
    from mirror.services.dialog import build_dialog_service_for_celery
    unified = UnifiedMessage(
        global_user_id=user_id_str,
        text=original_message,
        channel="telegram",
        chat_id=chat_id_str,
        session_id=await _get_session_id(user_id),
        metadata={"after_busy": True},
    )
    # build_dialog_service_for_celery() — фабрика, создаёт полностью собранный
    # экземпляр DialogService со всеми зависимостями (аналог dependency injection
    # из FastAPI/dependencies.py, но для Celery-контекста).
    # Определяется в mirror/services/dialog.py рядом с build_dialog_graph().
    dialog_svc = await build_dialog_service_for_celery()
    response = await dialog_svc.handle(unified)
    await http.post(url, json={"chat_id": int(chat_id_str), "text": response.text})

    await redis.delete(f"busy_pending:{user_id}")
```

---

## Схема БД (миграция 025)

```sql
-- История отправленных инициатив
CREATE TABLE proactive_log (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID REFERENCES users(user_id) ON DELETE CASCADE,
    type         VARCHAR(50) NOT NULL,
    score        FLOAT CHECK (score >= 0.0 AND score <= 1.0),
    delivered    BOOLEAN DEFAULT FALSE NOT NULL,
    opened       BOOLEAN DEFAULT FALSE NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_proactive_log_user ON proactive_log (user_id, created_at DESC);
CREATE INDEX idx_proactive_log_type ON proactive_log (type, created_at DESC);

-- Настройки проактивности пользователя
ALTER TABLE user_profiles
  ADD COLUMN proactive_mode       VARCHAR(20) DEFAULT 'normal'
                                    CHECK (proactive_mode IN ('quiet', 'normal', 'active')),
  ADD COLUMN quiet_hours_start    TIME DEFAULT '23:00:00',
  ADD COLUMN quiet_hours_end      TIME DEFAULT '08:00:00',
  ADD COLUMN busy_probability     FLOAT DEFAULT 0.03
                                    CHECK (busy_probability >= 0.0 AND busy_probability <= 1.0);
```

### daily_ritual и ProactiveOrchestrator

Существующий `send_daily_rituals` Celery task (в `mirror/workers/tasks/daily_ritual.py`) **остаётся без изменений**.  
ProactiveOrchestrator добавляет тип `daily_ritual` как отдельный candidate, но **не дублирует** логику отправки — вместо этого делегирует в `DailyRitualService`. Если daily_ritual уже был отправлен сегодня (проверка по `daily_ritual_log`) — candidate не создаётся.

---

## Новые конфиги (app_config, seed в миграции 020)

| Ключ | Default | Описание |
|------|---------|---------|
| `proactive_score_threshold` | `0.5` | Порог score для отправки |
| `proactive_daily_limit` | `2` | Лимит инициатив в сутки |

```sql
INSERT INTO app_config (key, value) VALUES
  ('proactive_score_threshold', '0.5'),
  ('proactive_daily_limit', '2')
ON CONFLICT (key) DO NOTHING;
```

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `proactive_compose` | main_chat | Генерация текста инициативного сообщения |
| `proactive_return` | main_chat | Ответ после «занятости» |

---

## Redis ключи

| Ключ | Тип | TTL | Значение |
|------|-----|-----|---------|
| `proactive:last_sent:{user_id}:{type}` | STRING | cooldown_hours × 3600 | ISO timestamp UTC |
| `proactive:daily_count:{user_id}:{YYYY-MM-DD}` | STRING | 86400 | integer (count) |
| `proactive:ignored_streak:{user_id}` | STRING | 604800 (7д) | integer (streak count) |
| `busy_pending:{user_id}` | STRING | 2400 | original message text |

---

## Файлы к созданию / изменению

| Файл | Действие |
|------|---------|
| `mirror/services/proactive/orchestrator.py` | Создать — ProactiveOrchestrator |
| `mirror/services/proactive/candidates.py` | Создать — скоринг кандидатов |
| `mirror/services/proactive/busy.py` | Создать — BusyBehavior |
| `mirror/services/proactive/helpers.py` | Создать — вспомогательные функции (_deliver_to_user, _get_last_user_message_time, _get_last_episode, _user_has_natal_chart, _get_profile, _get_bot_token_for_user, _log_proactive, _get_session_id) |
| `mirror/services/dialog.py` | Изменить — добавить `build_dialog_service_for_celery()` фабрику |
| `mirror/models/user.py` | Изменить — добавить поля UserProfile: proactive_mode, quiet_hours_start, quiet_hours_end, busy_probability (соответствуют миграции 025) |
| `mirror/channels/telegram/handlers.py` | Изменить — вызов BusyBehavior.maybe_intercept перед handle_message; /quiet, /active handlers; обновление user:last_message_time в Redis |
| `mirror/workers/tasks/proactive.py` | Создать — Celery tasks |
| `mirror/workers/celery_app.py` | Изменить — добавить beat schedule |
| `mirror/db/migrations/versions/025_proactive.py` | Создать — миграция |
| `mirror/db/seeds/llm_routing_stage2.py` | Дополнить |

---

## Definition of Done

- [ ] Smoke-тест: пользователь молчит 3 дня → emotional_checkin отправляется (score > 0.5)
- [ ] Smoke-тест: `/quiet` → proactive_mode='quiet', journal_notifications_enabled=False
- [ ] Smoke-тест: 3 игнорирования подряд → cooldown удваивается
- [ ] Smoke-тест: тихие часы 23:00-08:00 — сообщения не отправляются
- [ ] Smoke-тест: busy_probability=1.0 → каждое сообщение перехватывается → через 5-40 мин приходит возврат
- [ ] Глобальный лимит 2 сообщения в сутки соблюдается
- [ ] risk_level=crisis → BusyBehavior не срабатывает
- [ ] daily_ritual через ProactiveOrchestrator не дублируется с существующим task
- [ ] Логирование: `proactive.sent`, `proactive.ignored`, `proactive.busy_triggered`, `proactive.returned`
