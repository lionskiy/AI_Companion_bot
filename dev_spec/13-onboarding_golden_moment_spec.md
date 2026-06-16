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
- [ ] Текст инсайта генерирует LLM (task_kind=`golden_moment`); **без клинических ярлыков** (§3.8); задача роутируется в `main_chat` (Free-фича)
- [ ] После инсайта — мягкий bridge-текст из `app_config.golden_moment_cta`
- [ ] В кризисной ветке (`risk_level=crisis` или `risk_signal`) — golden_moment **не показывается** в этом цикле диалога
- [ ] Онбординг-вопросы запрашиваются **контекстно** (см. таблицу ниже), **не при /start**
- [ ] Если пользователь отказался ответить на онбординг-вопрос — повтор **не ранее чем через 5 сессий** (Redis key `onboarding:skip:{user_id}:{field}`, TTL = 5 × SESSION_IDLE_SECONDS)
- [ ] Новые поля в `app_config`: `golden_moment_threshold`, `golden_moment_t_max_days`, `golden_moment_cta`
- [ ] Миграция 021 добавляет поля в `user_profiles`: `golden_moment_pending BOOLEAN DEFAULT FALSE`, `golden_moment_shown_at TIMESTAMPTZ`, `preferred_name VARCHAR(100)`, `partner_birth_date DATE`, `registered_at TIMESTAMPTZ DEFAULT NOW()`

---

## Архитектура

### Алгоритм readiness_score

Формула намеренно использует прямые SQL-запросы, а не `MemoryService.search()` — чтобы не тратить эмбеддинг-токены на подсчёт метрик.

```python
async def compute_readiness_score(user_id: UUID) -> float:
    """Вычисляет readiness_score из БД напрямую. Возвращает 0.0 при ошибке."""
    try:
        async with async_session_factory() as s:
            active_days = await s.scalar(
                select(func.count(func.distinct(func.date(MemoryEpisode.created_at))))
                .where(MemoryEpisode.user_id == user_id)
            ) or 0
            episodes_count = await s.scalar(
                select(func.count()).select_from(MemoryEpisode)
                .where(MemoryEpisode.user_id == user_id)
            ) or 0
            facts_count = await s.scalar(
                select(func.count()).select_from(MemoryFact)
                .where(MemoryFact.user_id == user_id, MemoryFact.deleted_at.is_(None))
            ) or 0
    except Exception:
        logger.warning("golden_moment.score_compute_failed", user_id=str(user_id))
        return 0.0

    score = (
        min(active_days, 14) / 14 * 0.3     # до 14 активных дней
        + min(episodes_count, 10) / 10 * 0.3  # до 10 сессий
        + min(facts_count, 10) / 10 * 0.4     # до 10 фактов
    )
    # Кэшировать в Redis на 1 час чтобы не перевычислять при каждом сообщении
    await redis.setex(f"golden_moment:score:{user_id}", 3600, str(round(score, 3)))
    return round(score, 3)
```

Порог 0.6 соответствует примерно: 8+ активных дней ИЛИ 6+ сессий + 4+ факта. Значения нормализованы и не превышают 1.0.

### Компоненты GoldenMomentService

```python
class GoldenMomentService:
    def __init__(self, redis_client, llm_router) -> None: ...

    async def compute_readiness_score(self, user_id: UUID) -> float:
        """Вычисляет score из БД. При ошибке возвращает 0.0 (не бросает)."""

    async def check_and_trigger(self, user_id: UUID, state: dict) -> bool:
        """
        Проверяет условия и устанавливает golden_moment_pending=True.
        Вызывается в DialogService.handle() после graph.ainvoke().
        Возвращает True если нужно показать инсайт прямо сейчас.

        Не показывает если:
          - state.get("risk_level") in ("crisis", "risk_signal")
          - golden_moment_shown_at IS NOT NULL (уже показан)
          - is_first_message (первое сообщение — слишком рано)
        """

    async def build_insight(self, user_id: UUID) -> str:
        """
        Генерирует текст инсайта через LLM (task_kind='golden_moment').
        Собирает из БД: psych_profile + top-20 facts (importance DESC) + last 3 episode summaries.
        При ошибке LLM бросает исключение — вызывающий код должен поймать и залогировать.
        """

    async def mark_shown(self, user_id: UUID) -> bool:
        """
        Атомарно помечает золотой момент как показанный.
        UPDATE ... WHERE golden_moment_shown_at IS NULL RETURNING id
        Возвращает True если запись обновлена (False = уже был показан — дубль не нужен).
        """
```

### Место в диалоговом графе

Вызов происходит в `DialogService.handle()` (`mirror/services/dialog.py`) **после** `graph.ainvoke()`, но **до** возврата ответа. Если triggered — инсайт отправляется **вторым отдельным сообщением** через adapter.

```python
# В DialogService.handle() — после final_state = await self._graph.ainvoke(initial_state):
triggered = False
if not msg.is_first_message and state.get("risk_level") not in ("crisis", "risk_signal"):
    try:
        triggered = await self._golden_moment.check_and_trigger(uid, final_state)
    except Exception:
        logger.warning("golden_moment.check_failed", user_id=msg.global_user_id)

# Вернуть основной ответ — Golden Moment вставляется во второй вызов adapter.send()
# DialogService.handle() возвращает основной UnifiedResponse как обычно.
# Adapter при наличии golden_moment отправляет второе сообщение.
```

Так как `DialogService.handle()` возвращает один `UnifiedResponse`, а golden_moment — второе сообщение, реализация через:  
1. `GoldenMomentService.check_and_trigger()` сохраняет `triggered=True` в БД (флаг `golden_moment_pending`)  
2. Handler в `telegram/handlers.py` после `adapter.send(response, bot)` проверяет:

```python
# В telegram/handlers.py, после основного adapter.send():
if dialog_service.golden_moment_pending(unified):
    insight = await golden_moment_service.build_insight(uid)
    cta = get_app_config("golden_moment_cta", "Хочешь, буду лучше тебя понимать?")
    await bot.send_message(chat_id, f"{insight}\n\n{cta}")
    await golden_moment_service.mark_shown(uid)
    logger.info("golden_moment.shown", user_id=str(uid))
```

`DialogService.golden_moment_pending(msg)` — метод который проверяет флаг `golden_moment_pending=True AND golden_moment_shown_at IS NULL` для пользователя.

**Защита от race condition:** `mark_shown` использует:
```sql
UPDATE user_profiles
SET golden_moment_shown_at = NOW()
WHERE user_id = :uid AND golden_moment_shown_at IS NULL
RETURNING id
```
Если RETURNING пуст — момент уже был показан другим worker'ом, ничего не делаем.

### OnboardingManager

```python
class OnboardingManager:
    """Progressive disclosure онбординговых вопросов."""

    def __init__(self, redis_client) -> None: ...

    async def get_pending_question(
        self,
        user_id: UUID,
        profile: UserProfile,
        intent: str,
        sessions_count: int,
        messages_count: int,
    ) -> str | None:
        """
        Возвращает текст вопроса если нужно задать онбординговый вопрос,
        или None если ничего не нужно. Не задаёт вопрос повторно если:
          - данные уже заполнены в profile
          - пользователь пропустил вопрос < 5 сессий назад (Redis TTL)
        """

    async def save_skip(self, user_id: UUID, field: str) -> None:
        """
        Сохраняет в Redis что пользователь пропустил вопрос про field.
        TTL = 5 × SESSION_IDLE_SECONDS (из mirror/core/memory/session.py).
        """
```

Таблица триггеров:

| Триггер | Поле профиля | Вопрос |
|---------|-------------|--------|
| 3-я сессия ИЛИ 20+ сообщений | `preferred_name IS NULL` | «Кстати, как тебя называть?» |
| Первый intent=`astrology` или `numerology` | `birth_date IS NULL` | «Для точного расчёта мне нужна твоя дата рождения (день.месяц.год)» |
| Первый intent=`astrology` и нет места рождения | `birth_place IS NULL` | «И ещё: город или страна рождения» |
| Упоминание партнёра в тексте (regex: партнёр|муж|жена|парень|девушка) | `partner_birth_date IS NULL` | «Хочешь разберём синастрию? Пришли дату рождения партнёра» |

Определение "упоминание партнёра" — простой regex в `OnboardingManager.get_pending_question()`, не через LLM.

Вопросы добавляются к ответу бота как постфикс, формулируются через LLM (task_kind=`onboarding_question`) — коротко, органично.

Вызывается в `generate_response_node` в `dialog_graph.py` после генерации основного ответа:
```python
# В generate_response_node, после получения response:
onboarding_q = await onboarding_manager.get_pending_question(uid, profile, intent, ...)
if onboarding_q:
    response += f"\n\n{onboarding_q}"
```

---

## Схема БД (миграция 021)

```sql
-- Добавить в user_profiles:
ALTER TABLE user_profiles
  ADD COLUMN golden_moment_pending    BOOLEAN DEFAULT FALSE NOT NULL,
  ADD COLUMN golden_moment_shown_at   TIMESTAMPTZ,
  ADD COLUMN preferred_name           VARCHAR(100),
  ADD COLUMN partner_birth_date       DATE,
  ADD COLUMN registered_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL;

-- Индекс для быстрой выборки пользователей с pending golden moment:
CREATE INDEX idx_user_profiles_golden_moment_pending
  ON user_profiles (user_id)
  WHERE golden_moment_pending = TRUE AND golden_moment_shown_at IS NULL;
```

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `golden_moment` | main_chat | Генерация персонального инсайта (Free-фича, не premium) |
| `onboarding_question` | main_chat | Формулировка онбординг-вопроса |

Seed: добавить в `mirror/db/seeds/llm_routing_stage2.py` и вызвать из миграции 020.

---

## Новые app_config ключи (seed в миграции 020)

```sql
INSERT INTO app_config (key, value) VALUES
  ('golden_moment_threshold', '0.6'),
  ('golden_moment_t_max_days', '12'),
  ('golden_moment_cta', 'Ты удивительный человек. Хочешь, я буду лучше тебя понимать — расскажи немного о себе?')
ON CONFLICT (key) DO NOTHING;
```

---

## Файлы к созданию / изменению

| Файл | Действие |
|------|---------|
| `mirror/services/golden_moment.py` | Создать — GoldenMomentService |
| `mirror/services/onboarding.py` | Создать — OnboardingManager |
| `mirror/services/dialog.py` | Изменить — вызов check_and_trigger после ainvoke, метод golden_moment_pending |
| `mirror/channels/telegram/handlers.py` | Изменить — отправка second message если pending |
| `mirror/services/dialog_graph.py` | Изменить — вызов OnboardingManager в generate_response_node |
| `mirror/db/migrations/versions/021_golden_moment.py` | Создать — миграция |
| `mirror/db/seeds/llm_routing_stage2.py` | Создать/дополнить — новые task_kinds и app_config |

---

## Definition of Done

- [ ] Smoke-тест: новый пользователь → 15 сообщений → readiness_score растёт → golden_moment_pending = True
- [ ] Smoke-тест: золотой момент показывается ровно 1 раз (второй вызов — mark_shown возвращает False)
- [ ] Smoke-тест: в кризисной ветке (risk_level=crisis) не показывается
- [ ] Smoke-тест: skip онбординг-вопроса → не повторяется 5 сессий
- [ ] Логирование: `golden_moment.triggered`, `golden_moment.shown`, `onboarding.question_sent`
