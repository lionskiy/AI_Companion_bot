# Module 09: Daily Ritual — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §6.4, §12.5  
**Зависимости:** Module 01 (Identity — нужен timezone), Module 05 (LLM Router), Module 07 (Astrology), Module 08 (Tarot)  
**Дата:** 2026-04-20

---

## Цель

Ежедневный утренний ритуал: персонализированный микс из карты дня, астро-транзита, аффирмации. Отправляется автоматически в 07:00 по часовому поясу пользователя через Celery Beat.

---

## Acceptance Criteria

- [ ] Celery Beat задача `send_daily_rituals` запускается каждый час
- [ ] Выбор пользователей: те, у кого `local_hour == 7` по их timezone
- [ ] `DailyRitualService.build_ritual(user_id) → DailyRitual`
- [ ] `DailyRitual` содержит: карта дня, астро-транзит, аффирмация
- [ ] Карта дня: `TarotService.draw_cards("single")` — 1 карта
- [ ] Транзит дня: `AstrologyService.get_current_transits()` — самый значимый транзит
- [ ] Аффирмация генерируется через LLM (task_kind="proactive_compose") на основе карты + транзита
- [ ] Ритуал отправляется через Telegram Adapter (Module 02)
- [ ] Если `birth_date` отсутствует → астро-часть пропускается, только карта + аффирмация
- [ ] Ритуал логируется в `daily_ritual_log` (без текста сообщения)
- [ ] Пользователь может отключить ритуал командой `/quiet` (флаг в `user_profiles`)
- [ ] Тест: `build_ritual(user_id)` → объект с card и affirmation

---

## Out of Scope

- Настройка времени пользователем (всегда 07:00 по timezone) — Этап 2
- Выбор компонентов ритуала пользователем — Этап 2
- Расширенный ритуал (медитация, нумерология) — Этап 2
- Push-уведомления (только Telegram)

---

## Схема БД

```sql
CREATE TABLE daily_ritual_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(user_id),
    sent_at     timestamptz NOT NULL DEFAULT now(),
    ritual_date date NOT NULL,
    card_name   text,
    transit_info text,
    status      text NOT NULL DEFAULT 'sent'  -- 'sent', 'failed', 'skipped'
);
CREATE INDEX idx_ritual_log_user ON daily_ritual_log(user_id, ritual_date DESC);
-- Проверка дублей: нельзя слать дважды в день
CREATE UNIQUE INDEX idx_ritual_log_unique ON daily_ritual_log(user_id, ritual_date);

-- Флаг отключения ритуала (добавляется в user_profiles)
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS daily_ritual_enabled boolean NOT NULL DEFAULT true;
```

---

## Публичный контракт `DailyRitualService`

```python
# mirror/services/daily_ritual.py  ← НЕ ИЗМЕНЯТЬ без явного ТЗ

@dataclass
class DailyRitual:
    user_id:     UUID
    card:        DrawnCard           # из TarotService
    transit:     Transit | None      # из AstrologyService (None если нет birth_date)
    affirmation: str                 # сгенерированная LLM
    date:        date

class DailyRitualService:
    async def handle(self, state: "DialogState") -> str:
        """
        Вызывается из DialogService когда intent="daily_ritual" (ручной запрос пользователя).
        Всегда строит НОВЫЙ ритуал — не смотрит был ли уже отправлен сегодня Celery-задачей.
        Ритуал по запросу не записывается в daily_ritual_log (не считается "scheduled send").
        Если daily_ritual_enabled=False → вернуть сообщение об отключении.
        """

    async def build_ritual(self, user_id: UUID) -> DailyRitual:
        """
        1. draw_cards("single") через TarotService
        2. get_current_transits() через AstrologyService
        3. generate affirmation через LLMRouter (task_kind="proactive_compose")
        """

    async def format_ritual_message(self, ritual: DailyRitual) -> str:
        """Форматировать в красивый текст для Telegram (Markdown)."""
```

---

## Celery Beat задача

```python
# mirror/workers/tasks/daily_ritual.py

@celery_app.task(queue="scheduled")
def send_daily_rituals() -> None:
    """
    Запускается каждый час. Выбирает пользователей у которых сейчас local_hour == 7.
    """
    asyncio.run(_send_daily_rituals_async())

async def _send_daily_rituals_async() -> None:
    async with async_session_factory() as session:
        # Эффективный SQL-запрос с timezone-конверсией в PostgreSQL:
        result = await session.execute(text("""
            SELECT u.user_id
            FROM users u
            JOIN user_profiles up ON up.user_id = u.user_id
            WHERE up.daily_ritual_enabled = true
              AND EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow')) = 7
              AND NOT EXISTS (
                  SELECT 1 FROM daily_ritual_log drl
                  WHERE drl.user_id = u.user_id
                    AND drl.ritual_date = (NOW() AT TIME ZONE COALESCE(u.timezone, 'Europe/Moscow'))::date
              )
        """))
        user_ids = [str(row.user_id) for row in result]
    for user_id in user_ids:
        send_ritual_to_user.delay(user_id)

@celery_app.task(queue="scheduled", max_retries=2, bind=True)
def send_ritual_to_user(self, user_id: str) -> None:
    """Собрать ритуал и отправить пользователю."""
    try:
        asyncio.run(_send_ritual_async(user_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=120)

async def _send_ritual_async(user_id: str) -> None:
    from mirror.dependencies import daily_ritual_service, telegram_adapter
    ritual = await daily_ritual_service.build_ritual(UUID(user_id))
    text = daily_ritual_service.format_ritual_message(ritual)
    # Получить chat_id из channel_identities для отправки
    async with async_session_factory() as session:
        result = await session.execute(
            select(ChannelIdentity.channel_user_id)
            .where(ChannelIdentity.global_user_id == UUID(user_id))
            .where(ChannelIdentity.channel == "telegram")
        )
        row = result.first()
    if row:
        response = UnifiedResponse(text=text, chat_id=row.channel_user_id, channel="telegram", parse_mode="Markdown")
        await telegram_adapter.send(response)
```

---

## Celery Beat расписание

```python
# mirror/workers/celery_app.py

CELERYBEAT_SCHEDULE = {
    "send-daily-rituals": {
        "task": "mirror.workers.tasks.daily_ritual.send_daily_rituals",
        "schedule": crontab(minute=0),  # каждый час в 00 минут
    },
}
```

---

## Промпт для аффирмации

```python
def build_affirmation_prompt(
    card: DrawnCard,
    transit: Transit | None,
    facts: list[dict],
) -> list[dict]:
    context = f"Карта дня: {card.name} ({'перевёрнутая' if card.is_reversed else 'прямая'})"
    if transit:
        context += f"\nТранзит: {transit.planet} в {transit.sign}"
    system = f"""Создай короткую (1-2 предложения) персональную аффирмацию для утреннего ритуала.
{context}
Тон: тёплый, вдохновляющий, конкретный."""
    if facts:
        system += f"\nИзвестно о пользователе:\n{format_facts(facts)}"
    return [{"role": "system", "content": system}, {"role": "user", "content": "Создай аффирмацию"}]
```

---

## Формат сообщения пользователю

```python
def format_ritual_message(ritual: DailyRitual) -> str:
    text = f"🌅 *Доброе утро! Твой ритуал на сегодня*\n\n"
    text += f"🃏 *Карта дня:* {ritual.card.name}"
    if ritual.card.is_reversed:
        text += " _(перевёрнутая)_"
    text += "\n\n"
    if ritual.transit:
        text += f"✨ *Транзит дня:* {ritual.transit.planet} в {ritual.transit.sign}\n\n"
    text += f"💫 *Аффирмация:*\n_{ritual.affirmation}_"
    return text
```

---

## Hard Constraints

- Защита от дублей: `UNIQUE INDEX idx_ritual_log_unique(user_id, ritual_date)`
- Проверка `daily_ritual_enabled=True` перед отправкой
- `task_kind="proactive_compose"` для генерации аффирмации
- `send_ritual_to_user` — идемпотентна (повторный запуск не дублирует)
- Часовой пояс из `user_profiles.timezone`, fallback: `Europe/Moscow`

---

## DoD

- Celery Beat задача регистрируется в расписании
- Дубль не отправляется при повторном запуске задачи
- `build_ritual()` работает без `birth_date` (только карта + аффирмация)
- `/quiet` отключает ритуал (флаг в БД)
- `pytest tests/daily_ritual/` зелёный
