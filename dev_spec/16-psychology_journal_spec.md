# Module 16: Психологические режимы и Дневник — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §3.6, §3.7  
**Зависимости:** 03-memory, 06-dialog_service, 04-policy_safety  
**Дата:** 2026-04-26

---

## Цель

Добавить два связанных блока:
1. **Психологические режимы** — структурированные практики: CBT-дневник мыслей, работа с ценностями (ACT), колесо жизненного баланса, нарративные практики
2. **Дневник рефлексии** — вечерняя рефлексия, свободные записи, ежемесячный синтез

Оба блока работают с памятью mem_L2/L3 как источником и как хранилищем.

> Контуры §3.6 и §3.7 — повышенный риск: не подменяют клиническую помощь. Policy §3.8 обязателен.

---

## Acceptance Criteria

### Психологические режимы

- [ ] Intent Router распознаёт: `psychology`, `journal`, `reflection`
- [ ] **CBT-дневник мыслей:** пользователь описывает ситуацию → бот ведёт через 5 колонок (см. шаги ниже)
- [ ] **Колесо жизненного баланса:** бот задаёт 8 вопросов по сферам → рисует ASCII-карту → сохраняет оценки → при повторе через N дней сравнивает
- [ ] **Работа с ценностями (ACT):** серия вопросов о том, что важно → сохраняет ценности как факты (fact_type='value')
- [ ] **Нарративная практика:** бот помогает переписать историю о болезненной ситуации в ресурсную
- [ ] Каждая практика имеет чёткое начало и конец (отмена через /cancel — очищает Redis-состояние)
- [ ] Результаты каждой практики сохраняются в memory_facts с соответствующим fact_type
- [ ] Policy §3.8 проверяется в каждом шаге многошаговой практики — при кризисе практика прерывается

### Дневник рефлексии

- [ ] **Вечерняя рефлексия:** Celery polling task каждые 15 мин проверяет кому пора напомнить (с учётом timezone); 3 вопроса; сохраняется в memory_episodes с source_mode='journal'
- [ ] **Свободная запись:** пользователь пишет «запиши в дневник» или «я хочу записать» → бот сохраняет → анализирует настроение → сохраняет в memory_episodes с source_mode='journal'
- [ ] **Поиск по дневнику:** «что я писал про работу» → RAG поиск по user_episodes с фильтром source_mode='journal'
- [ ] **Ежемесячный синтез:** Celery task 1-го числа — агрегирует journal-эпизоды за месяц → LLM резюме → source_mode='journal_synthesis'
- [ ] Вечерняя рефлексия отключается через `journal_notifications_enabled=False` (команда /quiet устанавливает это поле, независимо от proactive_mode из модуля 18)
- [ ] Время вечерней рефлексии настраивается пользователем (поле `journal_evening_time`, default 21:00)

---

## Архитектура

### PsychologyService

```python
class PsychologyService:
    def __init__(self, llm_router, memory_service, redis_client) -> None: ...

    async def handle(self, state: DialogState) -> str:
        """
        Диспетчер: определяет практику из текущего Redis-состояния или нового запроса.
        Всегда проверяет policy перед продолжением практики.
        """
        import json
        uid = UUID(state["user_id"])

        # 1. Policy-check — кризис прерывает любую практику
        policy_result = await policy_engine.check(uid, state["message"])
        if policy_result.blocked or policy_result.risk_level == "crisis":
            await self.cancel(uid)
            logger.info("psychology.crisis_interrupted", user_id=str(uid))
            return policy_result.crisis_response

        # 2. Продолжить текущую практику из Redis
        existing = await self._redis.get(f"practice_state:{uid}")
        if existing:
            data = json.loads(existing)
            practice = data.get("practice")
            if practice == "cbt":
                return await self.handle_cbt(state)
            elif practice == "wheel":
                return await self.handle_wheel(state)
            elif practice == "values":
                return await self.handle_values(state)
            elif practice == "narrative":
                return await self.handle_narrative(state)

        # 3. Определить новую практику из текста сообщения
        msg = state.get("message", "").lower()
        if any(kw in msg for kw in ["колесо", "баланс", "сферы жизни"]):
            return await self.handle_wheel(state)
        elif any(kw in msg for kw in ["ценности", "важно для меня", " act "]):
            return await self.handle_values(state)
        elif any(kw in msg for kw in ["нарратив", "переписать историю", "переосмыслить"]):
            return await self.handle_narrative(state)
        else:
            return await self.handle_cbt(state)  # default: CBT дневник мыслей

    async def handle_cbt(self, state: DialogState) -> str:
        """CBT-дневник. Использует Redis practice_state:{user_id} для хранения шага."""

    async def handle_wheel(self, state: DialogState) -> str:
        """Колесо жизненного баланса. 8 вопросов последовательно, потом ASCII-карта."""

    async def handle_values(self, state: DialogState) -> str:
        """Работа с ценностями (ACT). Серия вопросов, результат — факты fact_type='value'."""

    async def handle_narrative(self, state: DialogState) -> str:
        """Нарративная практика. Помогает переосмыслить историю."""

    async def cancel(self, user_id: UUID) -> None:
        """Очищает Redis-состояние. Вызывается при /cancel."""

    async def save_practice_result(
        self,
        user_id: UUID,
        practice_type: str,  # 'cbt' | 'wheel' | 'values' | 'narrative'
        data: dict,
    ) -> None:
        """Сохраняет результат в memory_facts."""
```

### JournalService

```python
class JournalService:
    def __init__(self, llm_router, memory_service, redis_client) -> None: ...

    async def save_entry(
        self,
        user_id: UUID,
        text: str,
        source: str = 'journal',  # 'journal' | 'journal_reflection'
    ) -> UUID:
        """Сохраняет в memory_episodes (source_mode=source). Возвращает episode_id."""

    async def search_entries(
        self,
        user_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[str]:
        """RAG поиск по user_episodes с фильтром source_mode IN ('journal','journal_reflection')."""

    async def evening_reflection_prompt(self, user_id: UUID) -> str:
        """
        Возвращает текст первого вопроса вечерней рефлексии.
        Три вопроса задаются последовательно через practice_state в Redis.
        """

    async def monthly_synthesis(self, user_id: UUID, month: int, year: int) -> str:
        """
        LLM (task_kind='journal_monthly_synthesis') агрегирует journal-эпизоды за месяц.
        Сохраняет результат как эпизод source_mode='journal_synthesis'.
        """

    async def handle(self, state: DialogState) -> str:
        """
        Диспетчер для intent='journal' и 'reflection'.
        Определяет действие из текста сообщения.
        """
        msg = state.get("message", "").lower()
        uid = UUID(state["user_id"])

        if any(kw in msg for kw in ["что я писал", "найди запись", "поищи в дневнике"]):
            results = await self.search_entries(uid, state["message"])
            if not results:
                return "Подходящих записей не нашла."
            return "Вот что нашла в твоём дневнике:\n\n" + "\n---\n".join(results[:3])

        if any(kw in msg for kw in ["рефлексия", "итоги дня", "вечерний вопрос"]):
            return await self.evening_reflection_prompt(uid)

        # Default: сохранить как свободную запись и проанализировать настроение
        await self.save_entry(uid, state["message"], source="journal")
        mood = await self._analyze_mood(uid, state["message"])
        mood_str = f" Настроение: {mood}." if mood else ""
        return f"Записала в дневник ✍️{mood_str}"

    async def _analyze_mood(self, user_id: UUID, text: str) -> str | None:
        """LLM (task_kind='journal_analyze') — одно слово настроения. None при ошибке."""
        try:
            return await self._llm_router.complete(
                task_kind="journal_analyze",
                messages=[{"role": "user", "content": text}],
            )
        except Exception:
            logger.warning("journal.mood_analyze_failed", user_id=str(user_id))
            return None
```

### Интеграция в dialog_graph.py

```python
# В build_dialog_graph() — добавить параметры:
def build_dialog_graph(..., psychology_service=None, journal_service=None):

# В generate_response_node:
elif intent == "psychology" and psychology_service is not None:
    response = await psychology_service.handle(state)
elif intent in ("journal", "reflection") and journal_service is not None:
    response = await journal_service.handle(state)  # JournalService.handle() — диспетчер
```

### Многошаговые практики — Redis state machine

Ключ: `practice_state:{user_id}`, тип: STRING (JSON), TTL: 3600 (1 час)

```python
# Пример состояния CBT шаг 2:
{
    "practice": "cbt",
    "step": 2,
    "data": {
        "situation": "Меня критиковал начальник",  # шаг 1 уже заполнен
        # "auto_thought": ...                       # шаг 2 — заполняется
    }
}
```

**CBT шаги (5 колонок):**
1. **Ситуация:** «Опиши что произошло — факты, без оценок»
2. **Автоматическая мысль:** «Какая мысль возникла первой?»
3. **Эмоция + интенсивность:** «Что почувствовал? Насколько сильно (1-10)?»
4. **Оспаривание:** «Какие есть доказательства ЗА и ПРОТИВ этой мысли?»
5. **Альтернативная мысль:** «Как ещё можно посмотреть на эту ситуацию?»

По завершении шага 5 — вызов `save_practice_result(user_id, 'cbt', data)`, очистка Redis.

**Колесо жизненного баланса — 8 сфер (оценка 1-10):**

| № | Сфера | Вопрос боту |
|---|-------|-------------|
| 1 | Работа/карьера | «Насколько ты доволен своей работой?» |
| 2 | Финансы | «Насколько ты удовлетворён финансовой ситуацией?» |
| 3 | Здоровье/тело | «Как ты оцениваешь своё физическое состояние?» |
| 4 | Отношения/семья | «Насколько наполнены твои близкие отношения?» |
| 5 | Личностный рост | «Чувствуешь ли развитие и движение вперёд?» |
| 6 | Отдых/увлечения | «Есть ли время на то что ты любишь?» |
| 7 | Окружение/друзья | «Как ты себя чувствуешь в своём окружении?» |
| 8 | Духовность/смыслы | «Насколько есть ощущение смысла и цели?» |

ASCII-карта после 8 оценок:
```
         Работа: 7  ████████░░
        Финансы: 5  ██████░░░░
  Здоровье/тело: 8  █████████░
Отношения/семья: 6  ███████░░░
  Личн. развитие: 4  █████░░░░░
           Отдых: 9  ██████████
      Окружение: 7  ████████░░
   Духовность: 3  ████░░░░░░
```

Сравнение с предыдущим снапшотом показывает дельту (↑/↓ по каждой сфере).

### Прерывание практики при кризисе

```python
# В КАЖДОМ handle_* перед ответом:
policy_result = await policy_engine.check(uid, user_message)
if policy_result.blocked or policy_result.risk_level == "crisis":
    await redis.delete(f"practice_state:{uid}")  # очищаем состояние
    logger.info("psychology.crisis_interrupted", user_id=str(uid), practice=current_practice)
    return policy_result.crisis_response
```

### Celery — вечерняя рефлексия (polling)

```python
# Каждые 15 минут проверяет кому пора
@celery_app.task(name="mirror.workers.tasks.journal.check_evening_reflections")
def check_evening_reflections():
    asyncio.run(_dispatch_evening_reflections())

async def _dispatch_evening_reflections():
    await ensure_db_pool()
    now_utc = datetime.now(timezone.utc)

    async with get_session() as session:
        users = await session.execute(
            select(UserProfile.user_id, UserProfile.timezone, UserProfile.journal_evening_time)
            .where(UserProfile.journal_notifications_enabled == True)
        )

    for user_id, tz_name, evening_time in users.all():
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tz_name or "Europe/Moscow")
            local_now = datetime.now(tz)
            # journal_evening_time — TIME без timezone; интерпретируется в timezone пользователя
            target = evening_time or time(21, 0)
            local_time = local_now.time().replace(second=0, microsecond=0)
            # Окно ±7 минут (половина интервала polling'а)
            delta_minutes = abs(
                (local_time.hour * 60 + local_time.minute) -
                (target.hour * 60 + target.minute)
            )
            if delta_minutes <= 7:
                send_evening_reflection.delay(str(user_id))
        except Exception:
            logger.warning("journal.reflection_dispatch_failed", user_id=str(user_id))
```

Поле `journal_evening_time` — тип `TIME` (без TZ), хранит время по часовому поясу пользователя. При сравнении используется `user.timezone` для конвертации текущего UTC в локальное время.

### Celery task send_evening_reflection

```python
@celery_app.task(name="mirror.workers.tasks.journal.send_evening_reflection")
def send_evening_reflection(user_id_str: str):
    asyncio.run(_do_evening_reflection(user_id_str))

async def _do_evening_reflection(user_id_str: str) -> None:
    await ensure_db_pool()
    user_id = UUID(user_id_str)

    # Идемпотентность: не отправлять дважды в один день
    sent_key = f"journal:evening_sent:{user_id}:{date.today().isoformat()}"
    if await redis.exists(sent_key):
        return

    from mirror.services.journal import JournalService
    journal_svc = JournalService(
        llm_router=_get_llm_router(),
        memory_service=_get_memory_service(),
        redis_client=redis,
    )
    question = await journal_svc.evening_reflection_prompt(user_id)

    # Отправить через Telegram HTTP API
    bot_token = await _get_bot_token_for_user(user_id)
    if not bot_token:
        return
    async with get_session() as session:
        row = await session.execute(
            select(ChannelIdentity.channel_user_id)
            .where(ChannelIdentity.user_id == user_id)
            .where(ChannelIdentity.channel == "telegram")
        )
        identity = row.first()
    if not identity:
        return
    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={"chat_id": int(identity.channel_user_id), "text": question})

    await redis.setex(sent_key, 86400, "1")
    logger.info("journal.evening_reflection_sent", user_id=user_id_str)
```

### Команда /cancel (telegram/handlers.py)

```python
@router.message(Command("cancel"))
async def handle_cancel(message: Message) -> None:
    uid = await _get_user_id(message)
    # Очищаем Redis-состояние практики (PsychologyService и JournalService рефлексия)
    await redis.delete(f"practice_state:{uid}")
    await message.answer("Практика отменена. Чем ещё могу помочь?")
```

---

## Схема БД (миграция 023)

```sql
-- Настройки дневника пользователя
ALTER TABLE user_profiles
  ADD COLUMN journal_evening_time TIME DEFAULT '21:00:00',
  ADD COLUMN journal_notifications_enabled BOOLEAN DEFAULT TRUE;

-- Колесо жизненного баланса (история оценок для сравнения динамики)
CREATE TABLE life_wheel_snapshots (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID REFERENCES users(user_id) ON DELETE CASCADE,
    scores     JSONB NOT NULL
                 CHECK (
                   jsonb_typeof(scores) = 'object'
                   AND scores ?& ARRAY['work','finances','health','relationships',
                                       'growth','leisure','social','spirituality']
                 ),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_life_wheel_user_time ON life_wheel_snapshots (user_id, created_at DESC);
```

Ключи JSONB-объекта `scores`: `work`, `finances`, `health`, `relationships`, `growth`, `leisure`, `social`, `spirituality` — значения INTEGER 1-10.

---

## Связь /quiet и journal

- `/quiet` устанавливает `user_profiles.journal_notifications_enabled = FALSE` и `proactive_mode = 'quiet'`
- `/active` устанавливает оба поля в активные значения
- Вечерняя рефлексия проверяет только `journal_notifications_enabled`, проактивность (модуль 18) — только `proactive_mode`
- Пользователь может отключить их независимо через API admin или ручной UPDATE

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `psychology_cbt` | main_chat | Ведение CBT-практики |
| `psychology_values` | main_chat | Работа с ценностями (ACT) |
| `psychology_narrative` | main_chat | Нарративная практика |
| `journal_analyze` | main_chat | Анализ записи дневника (настроение, темы) |
| `journal_monthly_synthesis` | main_chat | Ежемесячный синтез дневника |
| `life_wheel` | main_chat | Колесо жизненного баланса |

---

## Новые fact_type значения

| fact_type | Описание |
|-----------|---------|
| `value` | Жизненная ценность пользователя (из ACT). key=название ценности, value=описание |
| `life_wheel_score` | Оценка сферы жизни (устарелый — хранение в life_wheel_snapshots предпочтительнее) |
| `cbt_pattern` | Паттерн автоматических мыслей. key=паттерн, value=частота и контекст |
| `narrative_reframe` | Ресурсная интерпретация ситуации. key=тема, value=новый нарратив |

---

## Celery tasks (добавить в beat_schedule)

```python
# beat_schedule добавляется в celery_app.py:
"check-evening-reflections": {
    "task": "mirror.workers.tasks.journal.check_evening_reflections",
    "schedule": crontab(minute="*/15"),
},
"generate-monthly-synthesis": {
    "task": "mirror.workers.tasks.journal.generate_monthly_synthesis",
    "schedule": crontab(hour=5, minute=0, day_of_month=1),
},
```

---

## Файлы к созданию / изменению

| Файл | Действие |
|------|---------|
| `mirror/services/psychology.py` | Создать — PsychologyService |
| `mirror/services/journal.py` | Создать — JournalService |
| `mirror/services/intent_router.py` | Изменить — добавить intents `psychology`, `journal`, `reflection` |
| `mirror/services/dialog_graph.py` | Изменить — routing на новые сервисы |
| `mirror/channels/telegram/handlers.py` | Изменить — `/cancel` command handler; `/quiet`-связь с journal_notifications_enabled |
| `mirror/models/user.py` | Изменить — добавить поля UserProfile: `journal_evening_time`, `journal_notifications_enabled` (соответствуют миграции 023) |
| `mirror/workers/tasks/journal.py` | Создать — Celery tasks (check_evening_reflections, send_evening_reflection, generate_monthly_synthesis) |
| `mirror/db/migrations/versions/023_psychology_journal.py` | Создать — миграция |
| `mirror/db/seeds/llm_routing_stage2.py` | Дополнить |

---

## Definition of Done

- [ ] Smoke-тест: пользователь пишет «хочу записать в дневник» → запись в memory_episodes (source_mode='journal')
- [ ] Smoke-тест: CBT практика проходит все 5 шагов → результат в memory_facts (fact_type='cbt_pattern')
- [ ] Smoke-тест: колесо жизненного баланса — повторный прогон показывает сравнение с предыдущим
- [ ] Smoke-тест: /cancel прерывает практику на любом шаге, Redis-состояние очищено
- [ ] Smoke-тест: кризисный сигнал внутри CBT → практика прерывается, crisis_response возвращается
- [ ] Вечерняя рефлексия отправляется Celery task в заданное время с учётом timezone
- [ ] /quiet устанавливает journal_notifications_enabled=False
- [ ] Логирование: `psychology.handle`, `journal.entry_saved`, `journal.synthesis_generated`
