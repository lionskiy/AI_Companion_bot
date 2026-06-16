# Module 01: Identity — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §12.1, §12.8, §13.1  
**Зависимости:** Foundation (F-16 выполнен)  
**Дата:** 2026-04-20

---

## Цель

Единая точка идентификации пользователей. Каждый пользователь получает `global_user_id` (UUID) — внутренний идентификатор независимо от канала. Telegram-пользователь с `user_id=123` и тот же пользователь в будущем через Web — один `global_user_id`.

---

## Acceptance Criteria

- [ ] `POST /webhook/telegram` с новым пользователем создаёт запись в `users`, `channel_identities`, `user_profiles`, `subscriptions`
- [ ] Повторный запрос с тем же `channel_user_id` возвращает существующий `global_user_id` (идемпотентно)
- [ ] `IdentityService.get_or_create("telegram", "123")` → `UUID`
- [ ] JWT-токен генерируется с `sub=global_user_id`, подписан `SECRET_KEY`
- [ ] `verify_token(token)` → `global_user_id` или `HTTPException(401)`
- [ ] `user_id` никогда не берётся из тела запроса — только из токена
- [ ] Поле `is_tester` = `False` по умолчанию
- [ ] Поле `subscription` = `"free"` по умолчанию
- [ ] При создании пользователя: `subscriptions` запись tier='free' создаётся в той же транзакции
- [ ] Миграция Alembic создаёт таблицы `users`, `channel_identities`, `user_profiles`

---

## Out of Scope

- Keycloak, OAuth, социальные логины (Этап 2)
- Верификация возраста `age_L*` (Этап 3)
- Merge/unmerge аккаунтов (Этап 2)
- Refresh tokens (для Telegram не нужны — идентификация через webhook secret)

---

## Схема БД

```sql
CREATE TABLE users (
    user_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription    text NOT NULL DEFAULT 'free'
        CHECK (subscription IN ('free', 'basic', 'plus', 'pro')),
    -- subscription = денормализованный кэш для быстрого чтения.
    -- Источник истины: таблица subscriptions (Module 10).
    -- Обновляется синхронно при изменении активной подписки.
    is_tester       boolean NOT NULL DEFAULT false,
    timezone        text NOT NULL DEFAULT 'Europe/Moscow',
    language_code   text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz
);

CREATE TABLE channel_identities (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    channel         text NOT NULL CHECK (channel IN ('telegram', 'vk', 'whatsapp', 'web', 'mobile')),
    channel_user_id text NOT NULL,
    global_user_id  uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    linked_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (channel, channel_user_id)
);
CREATE INDEX idx_channel_identities_global ON channel_identities(global_user_id);

-- user_profiles: расширяемый профиль пользователя.
-- Создаётся здесь (Module 01); колонки добавляются миграциями Module 07 и 09.
CREATE TABLE user_profiles (
    user_id         uuid PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    display_name    text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz
);
-- Module 07 добавит: birth_date, birth_time, birth_city, birth_lat, birth_lon, zodiac_sign, natal_data
-- Module 09 добавит: daily_ritual_enabled
```

---

## Публичный контракт `IdentityService`

```python
# mirror/core/identity/service.py
class IdentityService:
    async def get_or_create(
        self,
        channel: str,
        channel_user_id: str,
        timezone: str = "Europe/Moscow",
        language_code: str | None = None,
    ) -> UUID:
        """
        Возвращает (global_user_id, is_new: bool).
        При создании нового пользователя:
        1. INSERT INTO users
        2. INSERT INTO channel_identities
        3. INSERT INTO user_profiles (пустая запись)
        4. INSERT INTO subscriptions (tier='free') — прямо здесь, без вызова BillingService
           (избегаем circular dependency: Identity ↔ Billing)
        Всё в одной транзакции. Subscription создаётся вручную, не через BillingService.
        """

    async def get_user(self, global_user_id: UUID) -> User | None:
        """Получить пользователя по global_user_id."""

    async def update_timezone(self, global_user_id: UUID, timezone: str) -> None:
        """Обновить timezone пользователя."""
```

> `get_or_create` координирует создание профиля и бесплатной подписки атомарно.
> `billing_service` инжектируется через конструктор (DI), не импортируется напрямую.

---

## JWT Auth

```python
# mirror/core/identity/jwt_handler.py

def create_token(global_user_id: UUID) -> str:
    """Создать JWT с sub=global_user_id, exp=24h."""

def verify_token(token: str) -> UUID:
    """Верифицировать токен, вернуть global_user_id или raise HTTPException(401)."""

# FastAPI dependency — используется будущими HTTP-эндпоинтами (Stage 2 Web)
async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> UUID:
    return verify_token(token)
```

Алгоритм: `HS256`. Секрет: `settings.secret_key`. TTL: 24 часа.

> **Важно для Stage 1:** в Telegram webhook-потоке JWT не используется.
> `global_user_id` получается из `IdentityService.get_or_create()` напрямую по `channel_user_id` из апдейта.
> `create_token()` / `get_current_user_id` — задел для Web-клиента (Stage 2). Реализовать, но не встраивать в webhook-обработчики.

---

## Timezone из Telegram

Telegram не передаёт timezone напрямую. Алгоритм определения:
1. `message.from_user.language_code` → маппинг `ru`→`Europe/Moscow`, `uk`→`Europe/Kiev`, etc.
2. Если не определяется → `Europe/Moscow`
3. Хранить в `users.timezone`, обновлять при каждом сообщении если изменилось

---

## Hard Constraints

- `user_id` только из JWT, никогда из тела запроса (§13.1)
- RLS не применяется к `users` и `channel_identities` (нет личного контента)
- Логировать только `user_id` (UUID), не `channel_user_id`, не имя

---

## DoD

- Миграция применена: `alembic upgrade head`
- `pytest tests/identity/` — зелёный
- `IdentityService.get_or_create` идемпотентен (100 вызовов с одними параметрами = 1 запись)
