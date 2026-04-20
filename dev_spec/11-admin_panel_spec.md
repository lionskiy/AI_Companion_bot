# Module 11: Admin Panel — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §14  
**Зависимости:** Все предыдущие модули (читает все таблицы)  
**Дата:** 2026-04-20

---

## Цель

Инструменты администратора без деплоя кода: управление конфигурацией LLM роутинга, просмотр safety_log, настройка квот, редактирование system prompt. Реализуется через **Appsmith** (self-hosted) + **FastAPI Admin API**.

---

## Acceptance Criteria

### FastAPI Admin API
- [ ] `GET /admin/health` — статус сервисов (БД, Redis, Qdrant, NATS)
- [ ] `GET /admin/users` — список пользователей (user_id, tier, created_at, is_tester)
- [ ] `GET /admin/users/{user_id}` — детали: профиль, тариф, сессии
- [ ] `GET /admin/safety-log` — последние инциденты (без текста сообщений, pagination)
- [ ] `GET /admin/llm-routing` — текущий конфиг роутинга
- [ ] `PUT /admin/llm-routing/{task_kind}/{tier}` — обновить модель/провайдера без деплоя
- [ ] `GET /admin/quota-config` — текущие лимиты
- [ ] `PUT /admin/quota-config/{tier}` — изменить лимит квоты
- [ ] `GET /admin/app-config` — список ключей конфигурации (без секретов)
- [ ] `PUT /admin/app-config/{key}` — изменить значение (crisis_response, system_prompt_base)
- [ ] Все Admin API эндпоинты защищены: `ADMIN_TOKEN` в заголовке `X-Admin-Token`
- [ ] Все ответы — JSON, pagination через `limit` + `offset`

### Appsmith (self-hosted)
- [ ] Appsmith запускается в `docker-compose.dev.yml` на порту 3000
- [ ] Подключается к PostgreSQL напрямую (read-only DSN)
- [ ] Подключается к FastAPI Admin API (для write-операций)
- [ ] Дашборд: список пользователей с тарифами
- [ ] Дашборд: safety_log — последние инциденты
- [ ] Форма: редактирование `llm_routing` (provider, model, fallback)
- [ ] Форма: редактирование `quota_config` (daily_limit по tier)
- [ ] Форма: редактирование `app_config` (crisis_response, system_prompt)

---

## Out of Scope

- Auth через Keycloak (Этап 2)
- Управление контентом KB (Tarot/Astro знания) — отдельный модуль Этапа 2
- Аналитика / метрики — Этап 2
- Управление Celery-задачами через UI — Этап 2
- Роли (только один глобальный admin в Этапе 1)

---

## FastAPI Admin API

```python
# mirror/admin/router.py

from fastapi import APIRouter, HTTPException, Header
from mirror.core.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])

async def verify_admin(x_admin_token: str = Header(...)):
    # admin_token — SecretStr в Pydantic Settings, требует .get_secret_value()
    if x_admin_token != settings.admin_token.get_secret_value():
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/health")
async def health_check():
    """Проверить доступность: DB, Redis, Qdrant, NATS."""
    ...

@router.get("/users")
async def list_users(limit: int = 50, offset: int = 0, _=Depends(verify_admin)):
    ...

@router.put("/llm-routing/{task_kind}/{tier}")
async def update_llm_routing(
    task_kind: str, tier: str,
    body: LLMRoutingUpdate,
    _=Depends(verify_admin)
):
    """Обновить provider_id, model_id, fallback_chain в llm_routing."""
    # После обновления БД — инвалидировать кэш роутера:
    from mirror.dependencies import llm_router
    await db_update_routing(task_kind, tier, body)
    llm_router.invalidate_cache()
    ...

@router.put("/app-config/{key}")
async def update_app_config(
    key: str,
    body: AppConfigUpdate,
    _=Depends(verify_admin)
):
    """Изменить значение в app_config (crisis_response, system_prompt и т.д.)."""
    await db_update_app_config(key, body.value)
    # Инвалидировать in-memory кэш чтобы изменение вступило в силу немедленно:
    from mirror.services.dialog import invalidate_app_config_cache
    invalidate_app_config_cache()
    ...
```

---

## Pydantic схемы Admin API

```python
# mirror/admin/schemas.py

class LLMRoutingUpdate(BaseModel):
    provider_id:    str
    model_id:       str
    fallback_chain: list[dict] = []
    max_tokens:     int | None = None
    temperature:    float | None = None

class QuotaConfigUpdate(BaseModel):
    daily_limit: int  # -1 = без лимита

class AppConfigUpdate(BaseModel):
    value: str

class UserListItem(BaseModel):
    user_id:    str
    tier:       str
    is_tester:  bool
    created_at: str
    timezone:   str | None

class SafetyLogItem(BaseModel):
    id:         int
    user_id:    str
    risk_level: str
    action:     str
    created_at: str
    # НЕТ поля text — append-only без ПДн
```

---

## Docker Compose — Appsmith

```yaml
# В docker-compose.dev.yml добавить:
appsmith:
  image: appsmith/appsmith-ce:latest
  ports:
    - "3000:80"
  volumes:
    - appsmith_data:/appsmith-stacks
  environment:
    - APPSMITH_ENCRYPTION_PASSWORD=${APPSMITH_ENCRYPTION_PASSWORD}
    - APPSMITH_ENCRYPTION_SALT=${APPSMITH_ENCRYPTION_SALT}
  depends_on:
    - db
```

---

## app_config таблица (seed)

```sql
-- Уже создана в Module 04. Добавляем недостающие ключи:
INSERT INTO app_config (key, value, description) VALUES
    ('system_prompt_base',   '...', 'Базовый system prompt для main_chat'),
    ('daily_ritual_enabled', 'true', 'Глобальный флаг daily ritual'),
    ('maintenance_mode',     'false', 'Режим технических работ')
ON CONFLICT (key) DO NOTHING;
```

---

## Синхронизация users.subscription при изменении tier через Admin

```python
# При вызове PUT /admin/quota-config/{tier} или будущего endpoint смены тарифа:
# Если меняется tier конкретного пользователя — обязательно вызвать:
await billing_service.sync_user_subscription_cache(user_id, new_tier)
```

---

## Read-only PostgreSQL пользователь для Appsmith

```sql
-- Выполнить один раз при настройке БД (добавить в Foundation миграцию или отдельный SQL-скрипт):
CREATE USER appsmith_ro WITH PASSWORD 'appsmith_password';
GRANT CONNECT ON DATABASE mirror TO appsmith_ro;
GRANT USAGE ON SCHEMA public TO appsmith_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO appsmith_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO appsmith_ro;
```

Добавить в `.env.example`:
```
APPSMITH_DB_URL=postgresql://appsmith_ro:appsmith_password@db:5432/mirror
```

---

## Безопасность Admin API

```python
# .env.example
ADMIN_TOKEN=change_me_strong_secret_here

# Заголовок на каждый запрос:
# X-Admin-Token: <ADMIN_TOKEN>
```

- `ADMIN_TOKEN` — длинный случайный токен из `.env`
- Все Admin-эндпоинты на отдельном роутере с prefix `/admin`
- В продакшн: Admin API доступен только из внутренней сети (nginx restrict)
- Логировать каждое Admin-действие: `admin_action`, `target`, `changed_by=admin`

---

## Hard Constraints

- `safety_log` отдаётся без текстов сообщений (только метаданные)
- Изменение `llm_routing` через API вступает в силу немедленно (LLMRouter читает из БД)
- `ADMIN_TOKEN` никогда не логируется
- Appsmith подключается к PostgreSQL через отдельного read-only пользователя для SELECT-операций
- Write-операции только через FastAPI Admin API (не напрямую в БД из Appsmith)

---

## DoD

- `GET /admin/health` возвращает статус всех сервисов
- `PUT /admin/llm-routing/main_chat/*` — новая модель применяется в следующем вызове LLMRouter
- `GET /admin/safety-log` — инциденты без текста сообщений
- Appsmith запускается через `docker-compose up`
- `pytest tests/admin/` зелёный (тесты на Auth + CRUD эндпоинты)
