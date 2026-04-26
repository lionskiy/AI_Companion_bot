# Module 10: Free Billing — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §10, §13.1  
**Зависимости:** Module 01 (Identity — нужна таблица users)  
**Дата:** 2026-04-20

---

## Цель

Лимиты бесплатного использования без приёма оплаты. Контролирует дневную квоту сообщений для tier="free". Заглушка для платных тарифов (приём оплаты — Этап 3).

---

## Acceptance Criteria

- [ ] `BillingService.check_quota(user_id) → QuotaResult` (разрешить / заблокировать)
- [ ] `BillingService.get_tier(user_id) → str` — возвращает тариф из `subscriptions`
- [ ] Дневной лимит берётся из `quota_config` (не хардкодится в коде)
- [ ] При превышении → `QuotaExceededError` с friendly-сообщением
- [ ] `quota_config` seed: free=20 сообщений/день, reset в 00:00 UTC
- [ ] Rate limit в Redis: ключ `quota:{user_id}:{date}`, TTL до конца дня
- [ ] Новый пользователь автоматически получает `tier="free"` при создании (Module 01)
- [ ] `subscriptions` таблица: user_id, tier, expires_at, is_active
- [ ] Тариф "pro" = без лимита (пропуск quota check)
- [ ] Логируется: `user_id`, `tier`, `daily_count`, `quota_limit` — без текстов

---

## Out of Scope

- Приём оплаты / Stripe / YooKassa (Этап 3)
- Telegram Stars (Этап 3)
- Аддоны, дополнительные квоты (Этап 3)
- Возврат средств (Этап 3)
- Инвойсы и чеки (Этап 3)

---

## Схема БД

```sql
CREATE TABLE subscriptions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tier        text NOT NULL DEFAULT 'free'
                    CHECK (tier IN ('free','basic','plus','pro')),
    is_active   boolean NOT NULL DEFAULT true,
    expires_at  timestamptz,          -- NULL = бессрочно
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz
);
CREATE UNIQUE INDEX idx_subscriptions_active_user ON subscriptions(user_id)
    WHERE is_active = true;

CREATE TABLE quota_config (
    tier        text PRIMARY KEY,
    daily_limit int NOT NULL,         -- -1 = без лимита
    description text
);

-- Seed данные
INSERT INTO quota_config VALUES
    ('free',  20,  'Free tier: 20 messages/day'),
    ('basic', 100, 'Basic tier: 100 messages/day'),
    ('plus',  300, 'Plus tier: 300 messages/day'),
    ('pro',   -1,  'Pro tier: unlimited');
```

---

## Redis-ключи для quota

```python
# Счётчик сообщений за день
quota_key = f"quota:{user_id}:{date.today().isoformat()}"
# TTL: до конца UTC-дня (seconds_until_midnight)
# INCR → если > limit → QuotaExceededError
```

## Атомарный INCR + EXPIREAT (Lua-скрипт)

Простой `INCR` + `EXPIREAT` — два отдельных вызова, между ними возможна гонка (ключ пропадёт без TTL если процесс умрёт после INCR). Используйте Lua для атомарности:

```python
QUOTA_INCR_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIREAT', KEYS[1], ARGV[1])
end
return current
"""

async def _incr_quota(self, key: str, expire_at: int) -> int:
    """Атомарно инкрементировать счётчик и выставить TTL при первом создании."""
    result = await redis.eval(QUOTA_INCR_SCRIPT, 1, key, expire_at)
    return int(result)
```

`expire_at` = Unix timestamp полуночи следующего UTC-дня:
```python
import datetime
tomorrow = datetime.datetime.utcnow().replace(
    hour=0, minute=0, second=0, microsecond=0
) + datetime.timedelta(days=1)
expire_at = int(tomorrow.timestamp())
```

---

## Публичный контракт `BillingService`

```python
# mirror/services/billing.py  ← НЕ ИЗМЕНЯТЬ без явного ТЗ

@dataclass
class QuotaResult:
    allowed:    bool
    tier:       str
    daily_count: int
    daily_limit: int    # -1 = безлимит
    message:    str | None  # friendly сообщение если !allowed

class QuotaExceededError(Exception):
    def __init__(self, message: str):
        self.friendly_message = message

class BillingService:
    async def check_quota(self, user_id: UUID) -> QuotaResult:
        """
        1. Получить tier из subscriptions
        2. Если tier="pro" → QuotaResult(allowed=True, daily_limit=-1)
        3. Прочитать daily_limit из quota_config
        4. INCR счётчик в Redis
        5. Если count > limit → QuotaResult(allowed=False, message=...)
        """

    async def get_tier(self, user_id: UUID) -> str:
        """Тариф из активной записи subscriptions. Дефолт 'free'."""

    async def create_free_subscription(self, user_id: UUID) -> None:
        """
        Создать запись tier='free' при регистрации пользователя.
        Также синхронизирует users.subscription = 'free'.
        """

    async def sync_user_subscription_cache(self, user_id: UUID, tier: str) -> None:
        """
        Обновить денормализованный кэш users.subscription.
        Вызывать при любом изменении активной подписки (через Admin API или будущий биллинг).
        """
        await session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(subscription=tier, updated_at=func.now())
        )
```

---

## Интеграция с DialogService

```python
# В DialogService.handle() ПЕРЕД запуском LangGraph графа:
quota = await billing_service.check_quota(user_id)
if not quota.allowed:
    return UnifiedResponse(
        text=quota.message or "Вы исчерпали дневной лимит сообщений.",
        channel=msg.channel,
        chat_id=msg.chat_id,
    )
```

---

## Friendly-сообщения при превышении квоты

```python
QUOTA_EXCEEDED_MESSAGES = {
    "free": (
        "Ты использовал все {limit} сообщений на сегодня. "
        "Приходи завтра — я буду ждать 🌙"
    ),
}
```

---

## Hard Constraints

- `tier` берётся только из `subscriptions` в БД, не из тела запроса
- Redis-счётчик с TTL до конца UTC-дня — Lua-скрипт для атомарности (INCR + EXPIREAT в одной транзакции)
- `daily_limit` читается из `quota_config`, не хардкодится
- Quota check перед LangGraph — не внутри графа
- При `tier="pro"` quota check пропускается полностью

---

## DoD

- Новый пользователь получает `tier="free"` автоматически
- При 21-м сообщении (лимит 20) → `QuotaResult(allowed=False)`
- Redis-счётчик сбрасывается в 00:00 UTC (TTL)
- `pytest tests/billing/` зелёный
