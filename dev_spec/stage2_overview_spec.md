# Этап 2 — Обзор и состав

**Статус:** Ready for development  
**Этап:** 2  
**Ссылка на POD:** §3.4, §3.5, §3.6, §3.7, §6, §8.3, §8.5, §9  
**Дата:** 2026-04-26

---

## Цель этапа

Расширить продукт новыми режимами диалога, улучшить качество персонализации и добавить проактивное поведение бота. После этапа 2 Mirror превращается из реактивного ассистента в живого компаньона, который помнит, замечает паттерны и сам выходит на связь.

Монетизация (Basic/Plus/Pro, приём оплаты) и новые каналы (VK/MAX) — **не входят** в этот этап, перенесены на этап 2.1 / этап 3.

---

## Состав этапа 2

| № ТЗ | Модуль | Файл спеки |
|-------|--------|-----------|
| 13 | Онбординг «Золотой момент» | 13-onboarding_golden_moment_spec.md |
| 14 | Сонник | 14-dreams_spec.md |
| 15 | Нумерология | 15-numerology_spec.md |
| 16 | Психологические режимы и дневник | 16-psychology_journal_spec.md |
| 17 | Глубокий retrieval (rerank + приоритеты памяти) | 17-deep_retrieval_spec.md |
| 18 | Проактивность (бот пишет первым) | 18-proactive_spec.md |

---

## Порядок реализации (рекомендованный)

1. **17 — Глубокий retrieval** — фундамент для всего остального; улучшает качество ответов во всех режимах
2. **16 — Дневник** — добавляет новый source_mode для памяти, нужен для сонника
3. **14 — Сонник** — использует дневник как хранилище снов
4. **15 — Нумерология** — независимый режим, можно параллельно с 14
5. **13 — Золотой момент** — требует накопленной памяти (L2/L3) и psych_profile
6. **18 — Проактивность** — требует всей инфраструктуры выше

---

## Что остаётся неизменным

- Архитектура каналов (только Telegram)
- Биллинг (только Free тариф, лимит N/день)
- Policy и кризисный протокол §3.8 — обязателен во всех новых режимах
- LLM Router — расширяется новыми task_kinds, не переписывается
- Memory Service API — расширяется (module 17 явно разрешает изменение `mirror/core/memory/service.py`)

---

## Сквозные технические решения (обязательны для всех модулей)

### Расширение fact_type (миграция 020)

`memory_facts` имеет CHECK constraint: `'declared','observed','inferred','user_verified','external'`.  
Миграция 020 (первая в этапе 2) **расширяет constraint**, добавляя новые типы:

```sql
ALTER TABLE memory_facts DROP CONSTRAINT memory_facts_fact_type_check;
ALTER TABLE memory_facts ADD CONSTRAINT memory_facts_fact_type_check
  CHECK (fact_type IN (
    'declared','observed','inferred','user_verified','external',
    'dream_pattern','value','life_wheel_score','cbt_pattern','narrative_reframe','numerology'
  ));
```

Канонический список в Python — `mirror/core/memory/fact_types.py` (создать):
```python
VALID_FACT_TYPES = frozenset({
    'declared', 'observed', 'inferred', 'user_verified', 'external',
    'dream_pattern', 'value', 'life_wheel_score', 'cbt_pattern',
    'narrative_reframe', 'numerology',
})
```

### source_mode в memory_episodes (миграция 020)

Таблица `memory_episodes` не имеет поля `source_mode`. Миграция 020 добавляет его:

```sql
ALTER TABLE memory_episodes
  ADD COLUMN source_mode VARCHAR(30) DEFAULT 'chat'
    CHECK (source_mode IN ('chat', 'dream', 'journal', 'journal_synthesis', 'ritual'));
```

### Обновление IntentRouter (миграция 020 / seed)

Новые intents: `dream`, `numerology`, `psychology`, `journal`, `reflection`.  
Добавить в `classify_intent`-промпт примеры фраз для каждого нового intent (в `mirror/services/intent_router.py`).

### Новые llm_routing записи (seed в миграции 020)

Все новые task_kinds регистрируются через seed в миграции 020. Шаблон INSERT:

```sql
INSERT INTO llm_routing (task_kind, provider, model, max_tokens, temperature, fallback_chain)
VALUES
  ('dream_extract_symbols', 'openai', 'gpt-4o-mini', 500,  0.0, '["gpt-4o-mini"]'),
  ('dream_interpret',       'openai', 'gpt-4o',      1500, 0.8, '["gpt-4o","gpt-4o-mini"]'),
  ('numerology_interpret',  'openai', 'gpt-4o-mini', 1000, 0.7, '["gpt-4o-mini"]'),
  ('psychology_cbt',        'openai', 'gpt-4o',      1500, 0.7, '["gpt-4o","gpt-4o-mini"]'),
  ('psychology_values',     'openai', 'gpt-4o-mini', 1000, 0.7, '["gpt-4o-mini"]'),
  ('psychology_narrative',  'openai', 'gpt-4o',      1500, 0.8, '["gpt-4o","gpt-4o-mini"]'),
  ('journal_analyze',       'openai', 'gpt-4o-mini', 800,  0.5, '["gpt-4o-mini"]'),
  ('journal_monthly_synthesis', 'openai', 'gpt-4o', 2000, 0.7, '["gpt-4o","gpt-4o-mini"]'),
  ('life_wheel',            'openai', 'gpt-4o-mini', 1000, 0.6, '["gpt-4o-mini"]'),
  ('golden_moment',         'openai', 'gpt-4o',      1500, 0.9, '["gpt-4o","gpt-4o-mini"]'),
  ('onboarding_question',   'openai', 'gpt-4o-mini', 300,  0.7, '["gpt-4o-mini"]'),
  ('rerank',                'openai', 'gpt-4o-mini', 500,  0.0, '["gpt-4o-mini"]'),
  ('proactive_compose',     'openai', 'gpt-4o-mini', 500,  0.8, '["gpt-4o-mini"]'),
  ('proactive_return',      'openai', 'gpt-4o-mini', 500,  0.8, '["gpt-4o-mini"]')
ON CONFLICT (task_kind) DO NOTHING;
```

Файл: `mirror/db/seeds/llm_routing_stage2.py` — вызывается из миграции 020 через `op.execute()`.

### Celery Beat — динамические расписания

Для задач с индивидуальным временем пользователей (вечерняя рефлексия, проактивность) **НЕ** использовать статический Celery Beat schedule на конкретное время.  
Подход: единый polling task каждые N минут → выбирает нужных пользователей.

Все новые задачи регистрируются в `mirror/workers/celery_app.py` в секции `beat_schedule`:

```python
# Добавить в celery_app.conf.beat_schedule:
"check-evening-reflections": {
    "task": "mirror.workers.tasks.journal.check_evening_reflections",
    "schedule": crontab(minute="*/15"),   # каждые 15 минут
},
"proactive-dispatch": {
    "task": "mirror.workers.tasks.proactive.proactive_dispatch_batch",
    "schedule": crontab(minute="*/30"),   # каждые 30 минут
    "kwargs": {"offset": 0, "batch_size": 500},
},
"decay-fact-importance": {
    "task": "mirror.workers.tasks.memory.decay_fact_importance",
    "schedule": crontab(hour=4, minute=0, day_of_week=1),  # еженедельно, пн 04:00 UTC
},
"generate-monthly-synthesis": {
    "task": "mirror.workers.tasks.journal.generate_monthly_synthesis",
    "schedule": crontab(hour=5, minute=0, day_of_month=1),  # 1-го числа, 05:00 UTC
},
```

Добавить в `include` в `celery_app.py`:
```python
include=[
    ...,
    "mirror.workers.tasks.journal",
    "mirror.workers.tasks.proactive",
]
```

### Отправка сообщений из Celery worker

Celery worker не имеет прямого доступа к aiogram Bot. Для отправки сообщений использовать `_deliver()` паттерн (аналог `daily_ritual.py:_deliver()`):

```python
async def _deliver_to_user(user_id: UUID, text: str) -> None:
    from mirror.config import settings
    import httpx
    tg_id = await _get_telegram_id(user_id)  # из channel_identities
    if tg_id is None:
        return
    # Получить активный bot_token для этого пользователя из tg_bots таблицы
    bot_token = await _get_bot_token_for_user(user_id)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(url, json={"chat_id": tg_id, "text": text, "parse_mode": "Markdown"})
```

### Redis key namespace (единый для всего этапа 2)

Все ключи используют JSON-сериализацию, если не указано иное.

| Ключ | Тип Redis | TTL | Формат значения | Пример значения |
|------|-----------|-----|----------------|-----------------|
| `practice_state:{user_id}` | STRING | 3600 (1ч) | JSON object | `{"practice":"cbt","step":2,"data":{"situation":"..."}}` |
| `proactive:last_sent:{user_id}:{type}` | STRING | per-type (см. таблицу cooldown в spec 18) | ISO timestamp | `"2026-04-26T14:30:00Z"` |
| `proactive:daily_count:{user_id}:{date}` | STRING | 86400 | integer string | `"2"` |
| `proactive:ignored_streak:{user_id}` | STRING | 604800 (7д) | integer string | `"3"` |
| `busy_pending:{user_id}` | STRING | 2400 | plain text | `"Как дела?"` |
| `golden_moment:score:{user_id}` | STRING | 3600 (1ч) | float string | `"0.650"` |
| `onboarding:skip:{user_id}:{field}` | STRING | TTL = 5 сессий (см. spec 13) | `"1"` | `"1"` |

Дата в ключе `proactive:daily_count` — формат `YYYY-MM-DD` (UTC).

### Policy §3.8 в многошаговых практиках

Если в ходе CBT/дневника/нарративной практики PolicyEngine возвращает `risk_level=crisis`:

1. Практика прерывается немедленно
2. Промежуточное Redis-состояние удаляется: `await redis.delete(f"practice_state:{user_id}")`
3. Бот переключается на кризисный ответ (§3.8): телефон доверия 8-800-2000-122
4. Запись в `safety_log` (через существующий publisher)
5. `sales_allowed = False` на эту сессию

### Qdrant — новые коллекции (создать при деплое)

Коллекции создаются скриптом `mirror/core/memory/qdrant_init.py` (расширить существующий):

```python
# Добавить в qdrant_init.py:
COLLECTIONS = {
    ...,
    "knowledge_dreams": {
        "size": 3072,
        "distance": "Cosine",
    },
    "knowledge_numerology": {
        "size": 3072,
        "distance": "Cosine",
    },
}
```

### Зависимости миграций

```
019_tg_bots  (этап 1, последняя)
    └─► 020_stage2_infrastructure  (fact_type + source_mode + llm_routing seed) ◄── ПЕРВАЯ
            ├─► 021_golden_moment   (user_profiles: golden_moment_*, preferred_name, registered_at)
            ├─► 022_numerology      (user_profiles: life_path_number)
            ├─► 023_psychology_journal  (life_wheel_snapshots + journal_evening_time)
            ├─► 024_memory_facts_access (memory_facts: access_count, last_accessed)
            └─► 025_proactive       (proactive_log + user_profiles: proactive_mode, quiet_hours_*)
```

021–025 не зависят друг от друга и могут применяться в любом порядке после 020.

---

## Обязательное изменение mirror/models/user.py

> **КРИТИЧНО:** Этот файл НИКОГДА не перечислен в таблицах "Файлы к созданию/изменению" каждого ТЗ, но без его обновления любой код, обращающийся к полям UserProfile, упадёт с `AttributeError` при старте SQLAlchemy. Обновить **один раз** в начале этапа 2 (после миграции 020, до реализации модулей).

### Новые поля UserProfile (сводная таблица по миграциям)

```python
# mirror/models/user.py — в класс UserProfile добавить:

# Миграция 021 (module 13 — golden moment / onboarding)
golden_moment_pending  = Column(Boolean, default=False, nullable=False)
golden_moment_shown_at = Column(TIMESTAMPTZ, nullable=True)
preferred_name         = Column(String(100), nullable=True)
partner_birth_date     = Column(Date, nullable=True)
registered_at          = Column(TIMESTAMPTZ, nullable=True)  # заполнить NOW() для существующих

# Миграция 022 (module 15 — numerology)
life_path_number = Column(SmallInteger, nullable=True)
# CHECK constraint задан в миграции; в модели контролируется через validate_life_path_number

# Миграция 023 (module 16 — psychology / journal)
journal_evening_time          = Column(Time, default=time(21, 0), nullable=True)
journal_notifications_enabled = Column(Boolean, default=True, nullable=False)

# Миграция 025 (module 18 — proactive)
proactive_mode      = Column(String(20), default='normal', nullable=False)
                      # CHECK: IN ('quiet','normal','active') — задан в миграции
quiet_hours_start   = Column(Time, default=time(23, 0), nullable=True)
quiet_hours_end     = Column(Time, default=time(8, 0), nullable=True)
busy_probability    = Column(Float, default=0.03, nullable=True)
```

Импорты, которые нужно добавить в `user.py`:
```python
from datetime import time
from sqlalchemy import Boolean, Date, Float, SmallInteger, String, Time
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
```

---

## Acceptance Criteria этапа 2 (DoD)

- [ ] Все 6 модулей реализованы и покрыты smoke-тестами
- [ ] Каждый новый режим обрабатывает кризисные сигналы через Policy §3.8
- [ ] Новые task_kinds добавлены в таблицу `llm_routing` через seed в миграции 020
- [ ] Все Alembic-миграции (020-025) созданы и применены
- [ ] Проактивность управляется командами /quiet и /active
- [ ] KB-коллекции knowledge_dreams и knowledge_numerology созданы в Qdrant и заполнены
- [ ] Золотой момент срабатывает не более 1 раза на пользователя
- [ ] memory_episodes.source_mode заполняется корректно во всех новых режимах
- [ ] fact_type CHECK constraint расширен и не блокирует запись новых типов фактов
- [ ] Все новые Celery-задачи зарегистрированы в `celery_app.py` beat_schedule
