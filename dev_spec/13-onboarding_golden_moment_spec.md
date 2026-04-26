# Module 13: Онбординг «Золотой момент» — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §8.3, §8.5, §1.8  
**Зависимости:** 03-memory (mem_L2/L3), 06-dialog_service, 10-free_billing  
**Дата:** 2026-04-26

---

## Цель

Реализовать «Золотой момент» — персонализированный инсайт, который бот показывает пользователю после накопления достаточного количества данных о нём. Момент создаёт WOW-эффект: пользователь видит что бот действительно наблюдал и понял его. Является точкой конверсии в платный тариф (будущий этап монетизации).

Параллельно — улучшить онбординговый флоу: имя, дата рождения и другие данные запрашиваются в нужный момент, а не все сразу при первом старте.

---

## Acceptance Criteria

- [ ] `readiness_score` вычисляется после каждого сообщения пользователя по формуле (см. раздел Алгоритм); порог `golden_moment_threshold` настраивается в `app_config` (default 0.6)
- [ ] При достижении порога — флаг `golden_moment_pending=True` в `user_profiles`; устанавливается **один раз** (повторно не сбрасывается)
- [ ] Золотой момент показывается **однократно** (проверка по `golden_moment_shown_at IS NULL`)
- [ ] Временной потолок T_max (default 12 дней с регистрации): если превышен и `golden_moment_shown_at IS NULL` — показывается упрощённый вариант с тем что есть (даже при score < threshold)
- [ ] Инсайт строится из: psych_profile + все факты пользователя по importance DESC LIMIT 20 + summary последних 3 эпизодов
- [ ] Текст инсайта генерирует LLM (task_kind=`golden_moment`); **без клинических ярлыков** (§3.8); задача роутируется в `main_chat` (не premium — Free-фича)
- [ ] После инсайта — мягкий bridge-текст из `app_config.golden_moment_cta`
- [ ] В кризисной ветке (`risk_level=crisis` или `risk_signal`) — golden_moment **не показывается** в этом цикле диалога
- [ ] Онбординг-вопросы запрашиваются **контекстно** (см. таблицу ниже), **не при /start**
- [ ] Если пользователь отказался ответить на онбординг-вопрос — повтор **не ранее чем через 5 сессий** (Redis key `onboarding:skip:{user_id}:{field}`, TTL = 5 сессий)
- [ ] Новые поля в `app_config`: `golden_moment_threshold`, `golden_moment_t_max_days`, `golden_moment_cta`
- [ ] Миграция 021 добавляет поля в `user_profiles`: `golden_moment_pending BOOLEAN DEFAULT FALSE`, `golden_moment_shown_at TIMESTAMPTZ`, `preferred_name VARCHAR(100)`, `partner_birth_date DATE`, `registered_at TIMESTAMPTZ DEFAULT NOW()`

---

## Архитектура

### Алгоритм readiness_score

```python
async def compute_readiness_score(user_id: UUID) -> float:
    # Считаем данные напрямую из БД — не через MemoryService.search()
    async with async_session_factory() as s:
        # Дни активности = дней с хотя бы одним эпизодом
        active_days = await s.scalar(
            select(func.count(func.distinct(func.date(MemoryEpisode.created_at))))
            .where(MemoryEpisode.user_id == user_id)
        ) or 0
        # Число эпизодов (≈ сессий)
        episodes_count = await s.scalar(
            select(func.count()).select_from(MemoryEpisode)
            .where(MemoryEpisode.user_id == user_id)
        ) or 0
        # Число фактов
        facts_count = await s.scalar(
            select(func.count()).select_from(MemoryFact)
            .where(MemoryFact.user_id == user_id, MemoryFact.deleted_at.is_(None))
        ) or 0
    score = (
        min(active_days, 14) / 14 * 0.3
        + min(episodes_count, 10) / 10 * 0.3
        + min(facts_count, 10) / 10 * 0.4
    )
    return round(score, 3)
```

### Компоненты

```
GoldenMomentService
├── compute_readiness_score(user_id) → float     # прямой запрос в БД
├── check_and_trigger(user_id, state) → bool     # вызывается в DialogService после сохранения пары в Redis
├── build_insight(user_id) → str                 # LLM генерация, отдельный DB запрос за фактами
└── mark_shown(user_id)                          # UPDATE user_profiles SET golden_moment_shown_at=now()
```

### Место в диалоговом графе

Вызов происходит в `DialogService.handle()` **после** сохранения пары сообщений в Redis (mem_L1), но **до** возврата ответа пользователю. Если `check_and_trigger()` возвращает `True` — инсайт добавляется **к тому же ответу** вторым сообщением через `adapter.send()`.

```python
# В DialogService.handle() — после await adapter.send(response, bot):
if not msg.is_first_message:
    triggered = await self._golden_moment.check_and_trigger(uid, state)
    if triggered:
        insight = await self._golden_moment.build_insight(uid)
        await adapter.send(UnifiedResponse(text=insight, ...), bot)
        await self._golden_moment.mark_shown(uid)
```

**Защита от race condition:** `mark_shown` использует `UPDATE ... WHERE golden_moment_shown_at IS NULL RETURNING id` — атомарная операция, дубль невозможен.

### Онбординг-вопросы (progressive disclosure)

Логика хранится в `OnboardingManager`:

| Триггер | Вопрос | Что сохраняем |
|---------|--------|---------------|
| Первый запрос астрологии | Дата + время + место рождения | `user_profiles.birth_*` |
| 3-я сессия или 20+ сообщений | Как тебя зовут? | `user_profiles.preferred_name` |
| Упоминание партнёра | Дата рождения партнёра | `user_profiles.partner_birth_date` |

Вопросы не повторяются если данные уже есть.

---

## Схема БД (миграция 021)

```sql
-- Добавить в user_profiles:
ALTER TABLE user_profiles
  ADD COLUMN golden_moment_pending    BOOLEAN DEFAULT FALSE,
  ADD COLUMN golden_moment_shown_at   TIMESTAMPTZ,
  ADD COLUMN preferred_name           VARCHAR(100),
  ADD COLUMN partner_birth_date       DATE,
  ADD COLUMN registered_at            TIMESTAMPTZ DEFAULT NOW();

-- Индекс для быстрого поиска пользователей с pending golden moment:
CREATE INDEX ON user_profiles (id)
  WHERE golden_moment_pending = TRUE AND golden_moment_shown_at IS NULL;

-- Добавить в app_config (seed):
-- golden_moment_threshold = 0.6
-- golden_moment_t_max_days = 12
-- golden_moment_cta = "Хочешь, я буду лучше тебя понимать? ..."
```

**Зависимость:** миграция 020 (расширение fact_type + source_mode) должна быть применена **до** 021.

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `golden_moment` | main_chat | Генерация персонального инсайта (Free-фича, не premium) |
| `onboarding_question` | main_chat | Формулировка онбординг-вопроса |

---

## Файлы к созданию / изменению

- `mirror/services/golden_moment.py` — GoldenMomentService (новый)
- `mirror/services/onboarding.py` — OnboardingManager (новый)
- `mirror/services/dialog_graph.py` — вызов check_and_trigger после generate_response
- `mirror/db/migrations/versions/020_user_profiles_golden_moment.py` — миграция
- `mirror/db/seeds/llm_routing_stage2.py` — новые task_kinds

---

## Definition of Done

- [ ] Smoke-тест: новый пользователь → 15 сообщений → проверить что readiness_score растёт → golden_moment_pending = True
- [ ] Smoke-тест: золотой момент показывается ровно 1 раз
- [ ] Smoke-тест: в кризисной ветке не показывается
- [ ] Логирование: `golden_moment.triggered`, `golden_moment.shown` в structlog
- [ ] Документация обновлена в `docs/`
