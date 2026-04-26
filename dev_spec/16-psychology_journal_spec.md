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

Оба блока работают с памятью mem_L2/L3 как источником и как хранилищем — записи дневника становятся эпизодами памяти, психологические практики обогащают факты о пользователе.

> Контуры §3.6 и §3.7 — повышенный риск: не подменяют клиническую помощь. Policy §3.8 обязателен.

---

## Acceptance Criteria

### Психологические режимы

- [ ] Intent Router распознаёт: `psychology`, `journal`, `reflection`
- [ ] **CBT-дневник мыслей:** пользователь описывает ситуацию → бот ведёт через 5 колонок (ситуация → автоматическая мысль → эмоция → оспаривание → альтернативная мысль)
- [ ] **Колесо жизненного баланса:** бот задаёт 8 вопросов по сферам (работа, здоровье, отношения и т.д.) → рисует текстовую «карту» → сохраняет оценки → при повторе через N дней сравнивает
- [ ] **Работа с ценностями (ACT):** серия вопросов о том, что важно → сохраняет ценности как факты (fact_type='value')
- [ ] **Нарративная практика:** бот помогает переписать историю о болезненной ситуации в ресурсную
- [ ] Каждая практика имеет чёткое начало и конец (cancel через /cancel)
- [ ] Результаты каждой практики сохраняются в memory_facts с соответствующим fact_type

### Дневник рефлексии

- [ ] **Вечерняя рефлексия:** бот инициирует в настраиваемое время (default 21:00) — 3 вопроса (что хорошего было, что тяжело, что хочу завтра); сохраняется в memory_episodes с source_mode='journal'
- [ ] **Свободная запись:** пользователь пишет «в дневник» или «запиши» → бот сохраняет → анализирует настроение и темы → сохраняет в memory_episodes с source_mode='journal'
- [ ] **Поиск по дневнику:** «что я писал про работу» → RAG поиск по user_episodes с фильтром source_mode='journal'
- [ ] **Ежемесячный синтез:** Celery task в первый день месяца — агрегирует все journal-эпизоды за месяц → LLM генерирует резюме (task_kind=journal_monthly_synthesis) → сохраняется как отдельный эпизод source_mode='journal_synthesis'
- [ ] Напоминание о вечерней рефлексии отключается командой /quiet
- [ ] Время вечерней рефлексии настраивается пользователем

---

## Архитектура

### PsychologyService

```
PsychologyService
├── handle(state) → str              # диспетчер по sub-intent
├── handle_cbt(state) → str          # CBT дневник мыслей
├── handle_wheel(state) → str        # колесо жизненного баланса
├── handle_values(state) → str       # работа с ценностями
├── handle_narrative(state) → str    # нарративная практика
└── save_practice_result(user_id, practice_type, data)
```

### JournalService

```
JournalService
├── save_entry(user_id, text, source) → episode_id
├── search_entries(user_id, query) → list[str]
├── evening_reflection_prompt(user_id) → str  # 3 вопроса
└── monthly_synthesis(user_id, month, year) → str  # LLM резюме
```

### Многошаговые практики (state machine)

CBT-дневник и другие многошаговые практики требуют сохранения промежуточного состояния между сообщениями. Используем Redis:

```python
# Ключ: practice_state:{user_id}
# TTL: 3600 (1 час — если пользователь пропал, состояние очищается)
# Значение (пример CBT шаг 2):
{
    "practice": "cbt",
    "step": 2,                          # текущий шаг (1-5)
    "data": {
        "situation": "Меня критиковал начальник",  # шаг 1
        "auto_thought": "Я некомпетентен",          # шаг 2 — заполняется
    }
}
```

**CBT шаги (5 колонок):**
1. Ситуация: "Опиши что произошло?"
2. Автоматическая мысль: "Какая мысль возникла первой?"
3. Эмоция + интенсивность: "Что почувствовал? Насколько сильно (1-10)?"
4. Оспаривание: "Какие есть доказательства ЗА и ПРОТИВ этой мысли?"
5. Альтернативная мысль: "Как ещё можно посмотреть на эту ситуацию?"

**Колесо жизненного баланса — 8 сфер:**
Работа/карьера, Финансы, Здоровье/тело, Отношения/семья, Личностный рост, Отдых/увлечения, Окружение/друзья, Духовность/смыслы

**Прерывание практики при кризисе:**
```python
# В каждом handle_* перед ответом:
policy_result = await policy_engine.check(user_id, user_message)
if policy_result.blocked or policy_result.risk_level == "crisis":
    await redis.delete(f"practice_state:{user_id}")
    return policy_result.crisis_response
```

### Celery Beat — динамические расписания

**НЕ** использовать статические schedules. Подход: единый polling task каждые 15 минут:

```python
@app.task
async def check_evening_reflections():
    """Каждые 15 минут проверяет кому пора напомнить о рефлексии."""
    now_utc = datetime.utcnow()
    async with async_session_factory() as s:
        users = await s.execute(
            select(UserProfile)
            .where(UserProfile.journal_notifications_enabled == True)
            .where(UserProfile.golden_moment_shown_at != None)  # только активные
        )
    for user in users.scalars():
        tz = pytz.timezone(user.timezone or "Europe/Moscow")
        local_time = now_utc.astimezone(tz).time()
        target = user.journal_evening_time  # TIME field
        delta = abs((datetime.combine(date.today(), local_time) -
                     datetime.combine(date.today(), target)).total_seconds())
        if delta < 450:  # ±7.5 мин
            await send_reflection_prompt(user.user_id)
```

---

## Схема БД

```sql
-- Настройки дневника пользователя
ALTER TABLE user_profiles
  ADD COLUMN journal_evening_time TIME DEFAULT '21:00',
  ADD COLUMN journal_notifications_enabled BOOLEAN DEFAULT TRUE;

-- Колесо жизненного баланса (история оценок для сравнения)
CREATE TABLE life_wheel_snapshots (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID REFERENCES users(id),
    scores     JSONB NOT NULL,  -- {"work": 7, "health": 5, ...}
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON life_wheel_snapshots (user_id, created_at DESC);
```

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `psychology_cbt` | main_chat | Ведение CBT-практики |
| `psychology_values` | main_chat | Работа с ценностями (ACT) |
| `psychology_narrative` | main_chat | Нарративная практика |
| `journal_analyze` | main_chat | Анализ записи дневника (настроение, темы) |
| `journal_monthly_synthesis` | main_chat_premium | Ежемесячный синтез дневника |
| `life_wheel` | main_chat | Колесо жизненного баланса |

---

## Новые fact_type значения

| fact_type | Описание |
|-----------|---------|
| `value` | Жизненная ценность пользователя (из ACT) |
| `life_wheel_score` | Оценка сферы жизни |
| `cbt_pattern` | Паттерн автоматических мыслей |
| `narrative_reframe` | Ресурсная интерпретация ситуации |

---

## Celery tasks

```python
# Ежедневно в настраиваемое время — вечерняя рефлексия
@app.task
async def send_evening_reflection():
    # Выбрать пользователей у которых journal_notifications_enabled=True
    # И journal_evening_time попадает в текущее окно ±15 мин
    # Отправить первый вопрос рефлексии через бота

# 1-го числа каждого месяца
@app.task
async def generate_monthly_synthesis():
    # Для каждого пользователя с journal-эпизодами за прошлый месяц
    # Генерировать резюме и сохранять
```

---

## Файлы к созданию / изменению

- `mirror/services/psychology.py` — PsychologyService (новый)
- `mirror/services/journal.py` — JournalService (новый)
- `mirror/services/intent_router.py` — добавить intents `psychology`, `journal`, `reflection`
- `mirror/services/dialog_graph.py` — routing на новые сервисы
- `mirror/workers/tasks/journal.py` — Celery tasks (новый)
- `mirror/db/migrations/versions/022_psychology_journal.py` — миграция
- `mirror/db/seeds/llm_routing_stage2.py` — новые task_kinds

---

## Definition of Done

- [ ] Smoke-тест: пользователь пишет «хочу записать в дневник» → запись сохраняется в memory_episodes
- [ ] Smoke-тест: CBT практика проходит все 5 шагов, результат сохраняется в memory_facts
- [ ] Smoke-тест: колесо жизненного баланса — повторный прогон сравнивает с предыдущим
- [ ] Smoke-тест: /cancel прерывает практику на любом шаге без ошибки
- [ ] Вечерняя рефлексия отправляется Celery task в заданное время
- [ ] Policy §3.8 перехватывает кризисные сигналы внутри CBT-практики
- [ ] Логирование: `psychology.handle`, `journal.entry_saved`, `journal.synthesis_generated`
