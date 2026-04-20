# Stage 1 Foundation — Spec

**Статус:** Ready for development  
**Этап роадмапа:** Этап 1 (см. §15 POD)  
**Ссылка на POD:** §12.0, §12.1, §12.7, §13, §15  
**Дата:** 2026-04-20

---

## Цель и контекст

Создать работоспособный скелет проекта Mirror: структуру папок, все зависимости, инфраструктуру (docker-compose), конфигурацию, логирование, базу данных и CI/CD. После выполнения этого ТЗ должна подниматься вся инфраструктура (`docker compose up`) и запускаться FastAPI-приложение.

Это нулевой шаг перед разработкой модулей (Identity, Telegram Adapter, Memory и т.д.).

---

## Acceptance Criteria

- [ ] `docker compose -f docker-compose.dev.yml up -d` поднимает все сервисы без ошибок
- [ ] `python -m mirror.main` запускает FastAPI-приложение на порту 8000
- [ ] `alembic current` выполняется без ошибок (нет миграций — OK)
- [ ] `python -m py_compile mirror/main.py` — синтаксических ошибок нет
- [ ] PostgreSQL доступен: `psql $DATABASE_URL -c "SELECT 1"`
- [ ] Qdrant доступен: `curl http://localhost:6333/collections` возвращает `{"result":{"collections":[]}}`
- [ ] Redis доступен: `redis-cli ping` → `PONG`
- [ ] NATS доступен: `curl http://localhost:8222/healthz` → `{"status":"ok"}`
- [ ] RabbitMQ management UI доступен: `http://localhost:15672`
- [ ] Appsmith доступен: `http://localhost:3000`
- [ ] Structlog пишет JSON в stdout при старте приложения
- [ ] `.env.example` содержит все переменные окружения

---

## Out of Scope

- Реализация бизнес-логики (Identity, Memory, Telegram и т.д.)
- Alembic-миграции с таблицами (создаются в следующих ТЗ)
- Наполнение Qdrant-коллекций
- GitHub Actions deploy (добавить отдельным шагом при наличии сервера)

---

## Структура папок

```
mirror/                         # основной Python-пакет
├── __init__.py
├── main.py                     # FastAPI app, router mounting, lifespan
├── config.py                   # Pydantic Settings (все env vars)
├── logging_setup.py            # structlog JSON config
│
├── core/                       # ядро системы (не трогать без ТЗ)
│   ├── __init__.py
│   ├── identity/               # (модуль 01 — следующее ТЗ)
│   ├── memory/                 # (модуль 03)
│   ├── policy/                 # (модуль 04)
│   └── llm/                    # (модуль 05)
│
├── channels/                   # адаптеры каналов
│   ├── __init__.py
│   └── telegram/               # (модуль 02)
│
├── services/                   # бизнес-логика режимов
│   └── __init__.py
│
├── models/                     # SQLAlchemy ORM модели
│   └── __init__.py
│
├── db/                         # БД инфраструктура
│   ├── __init__.py
│   ├── session.py              # async session factory
│   └── migrations/             # Alembic
│
├── workers/                    # Celery задачи
│   ├── __init__.py
│   └── celery_app.py
│
├── events/                     # NATS JetStream
│   └── __init__.py
│
├── rag/                        # RAG / Haystack
│   └── __init__.py
│
└── admin/                      # FastAPI Admin API (для Appsmith)
    └── __init__.py

tests/                          # тесты
├── __init__.py
└── test_health.py

docker-compose.dev.yml          # локальная разработка
.env.example                    # шаблон переменных
.env                            # локальные значения (в .gitignore)
pyproject.toml                  # Poetry зависимости
alembic.ini
```

---

## Зависимости (pyproject.toml)

### Python
```
python = "^3.12"
```

### Core
```
fastapi = "^0.115"
uvicorn = {extras = ["standard"], version = "^0.34"}
pydantic = "^2.10"
pydantic-settings = "^2.7"
```

### Database
```
sqlalchemy = {extras = ["asyncio"], version = "^2.0"}
asyncpg = "^0.30"
alembic = "^1.14"
redis = {extras = ["asyncio"], version = "^5.2"}
```

### Vector DB
```
qdrant-client = "^1.13"
```
> Без `fastembed` extra — все embeddings идут через OpenAI `text-embedding-3-large` via LLMRouter.

### Telegram
```
aiogram = "^3.17"
```

### LLM / AI
```
openai = "^1.60"
anthropic = "^0.43"
langgraph = "^0.2"
# langchain-core НЕ указывать отдельно — langgraph включает совместимую версию.
# Явная версия langchain-core создаёт конфликты зависимостей.
haystack-ai = "^2.9"
```

### Astrology
```
kerykeion = "^4.20"
```

### Task Queue
```
celery = {extras = ["rabbitmq"], version = "^5.4"}
```

### Utils
```
geopy = "^2.4"        # геокодирование городов (Module 07 Astrology)
pytz = "^2024.1"      # timezone-aware расписания Celery Beat (Module 09)
```

### Messaging
```
nats-py = "^2.9"
```

### Auth
```
PyJWT = "^2.9"
```

### Logging / Monitoring
```
structlog = "^24.4"
sentry-sdk = {extras = ["fastapi"], version = "^2.19"}
prometheus-fastapi-instrumentator = "^7.0"
```

### Dev
```
pytest = "^8.3"
pytest-asyncio = "^0.24"
httpx = "^0.28"
pytest-mock = "^3.14"
```

### pytest конфигурация (в pyproject.toml)
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"          # все async def test_* запускаются как корутины автоматически
testpaths = ["tests"]
env = ["APP_ENV=test"]

[tool.pytest.ini_options.filterwarnings]
ignore = "DeprecationWarning"
```

> Без `asyncio_mode = "auto"` async-тесты silently pass без выполнения тела.

---

## docker-compose.dev.yml — сервисы

| Сервис | Image | Порт | Назначение |
|--------|-------|------|-----------|
| `postgres` | postgres:16-alpine | 5432 | OLTP БД; `POSTGRES_DB=mirror` обязательно |
| `qdrant` | qdrant/qdrant:latest | 6333, 6334 | Векторная БД |
| `redis` | redis:7-alpine | 6379 | Кэш, сессии, mem_L1 |
| `rabbitmq` | rabbitmq:3.13-management-alpine | 5672, 15672 | Celery broker |
| `nats` | nats:2.10-alpine | 4222, 8222 | JetStream event bus (`command: ["--js"]` обязателен) |
| `appsmith` | appsmith/appsmith-ce:latest | 3000 | Admin UI |

Все сервисы с `restart: unless-stopped`. Данные в named volumes. Health checks для postgres, redis, rabbitmq.

> `appsmith` в docker-compose должен иметь `depends_on: [postgres]` — **не** `mirror_api` (FastAPI запускается локально вне docker в dev-режиме).

### Celery Beat в docker-compose

```yaml
celery_beat:
  build: .
  command: celery -A mirror.workers.celery_app beat --loglevel=info
  depends_on:
    - rabbitmq
    - postgres
  env_file: .env
  restart: unless-stopped
```

> Без `celery_beat` сервиса `send_daily_rituals` никогда не запустится.

---

## config.py — переменные окружения

```python
class Settings(BaseSettings):
    # App
    app_env: str = "development"
    secret_key: SecretStr
    base_url: str  # Публичный URL приложения: https://your.domain.com (ngrok в dev)

    # PostgreSQL
    database_url: SecretStr  # postgresql+asyncpg://...

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = ""

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # NATS
    nats_url: str = "nats://localhost:4222"

    # LLM
    openai_api_key: SecretStr
    anthropic_api_key: SecretStr

    # Telegram
    telegram_bot_token: SecretStr
    telegram_webhook_secret: SecretStr

    # Admin
    admin_token: SecretStr  # X-Admin-Token для FastAPI Admin API

    # Sentry
    sentry_dsn: str = ""

    # Appsmith (используется только в docker-compose.dev.yml)
    # APPSMITH_ENCRYPTION_PASSWORD и APPSMITH_ENCRYPTION_SALT — в .env.example, не в Settings

    model_config = SettingsConfig(env_file=".env", env_file_encoding="utf-8")
```

---

## main.py — структура

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_db_pool()
    await init_qdrant_collections()  # idempotent
    await nats_client.connect(settings.nats_url)
    # Регистрация webhook Telegram (обязательно при каждом старте)
    await bot.set_webhook(
        url=f"{settings.base_url}/webhook/telegram/{settings.telegram_webhook_secret.get_secret_value()}",
        secret_token=settings.telegram_webhook_secret.get_secret_value(),
    )
    yield
    # shutdown
    await bot.delete_webhook()
    await nats_client.close()
    await close_db_pool()

app = FastAPI(title="Mirror", lifespan=lifespan)

# Routers
app.include_router(health_router)    # GET /health, GET /ready
app.include_router(telegram_router)  # POST /webhook/telegram/{secret}
app.include_router(admin_router)     # /admin/*

# Prometheus metrics
Instrumentator().instrument(app).expose(app)
```

> `BASE_URL` — полный публичный URL приложения (ngrok в dev, домен в prod). Добавить в `Settings` как `base_url: str`.

---

## Logging setup

Structlog с JSON-рендерером в production, ConsoleRenderer в development. Без ПДн в логах. Интеграция с Sentry для error-уровня.

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),  # prod
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
```

---

## NATS client — минимальный интерфейс

```python
# mirror/events/nats_client.py

class NATSClient:
    """Обёртка над nats-py. Singleton, инициализируется в lifespan."""

    async def connect(self, url: str) -> None:
        """Подключиться к NATS + создать JetStream context."""

    async def publish(self, subject: str, payload: dict) -> None:
        """Publish JSON-сообщение в JetStream. Fire-and-forget."""

    async def subscribe(self, subject: str, handler: Callable) -> None:
        """Подписаться на subject. handler(msg: dict) -> None."""

    async def close(self) -> None:
        """Закрыть соединение при shutdown."""

# Глобальный singleton (создаётся в main.py lifespan):
nats_client = NATSClient()
```

**Canonical subjects:**
```
mirror.dialog.session.closed     # publisher: Telegram Adapter (при /start), consumer: Memory
mirror.safety.crisis_detected    # publisher: Policy, consumer: (Этап 2 — эскалация)
```

---

## DI (Dependency Injection) — паттерн

Все сервисы создаются как модуль-уровневые singleton-ы в `mirror/dependencies.py` и инжектируются через конструкторы или FastAPI `Depends()`:

```python
# mirror/dependencies.py — создаётся один раз при старте

from mirror.core.llm.router import LLMRouter
from mirror.core.memory.service import MemoryService
from mirror.core.identity.service import IdentityService
from mirror.core.policy.safety import PolicyEngine
from mirror.services.billing import BillingService
from mirror.events.nats_client import nats_client

llm_router     = LLMRouter()
memory_service = MemoryService(llm_router=llm_router)
identity_service = IdentityService()
billing_service  = BillingService()
policy_engine    = PolicyEngine(llm_router=llm_router)
```

Handlers импортируют из `mirror.dependencies` — не создают сервисы сами. Async DB-соединения инициализируются в `lifespan`, не при импорте модуля.

---

## Qdrant коллекции — канонический реестр

Все коллекции создаются в `mirror/core/memory/qdrant_init.py` (единое место). При добавлении нового модуля — дополнять этот файл, не создавать отдельные init-функции:

```python
QDRANT_COLLECTIONS = {
    "user_episodes":   {"size": 3072, "distance": "Cosine"},  # Module 03
    "user_facts":      {"size": 3072, "distance": "Cosine"},  # Module 03
    "knowledge_astro": {"size": 3072, "distance": "Cosine"},  # Module 07
    "knowledge_tarot": {"size": 3072, "distance": "Cosine"},  # Module 08
}
```

---

## Порядок Alembic-миграций (обязательный)

Миграции нумеруются по порядку реализации (не по номерам модулей):

| Файл | Модуль | Таблицы |
|------|--------|---------|
| `001_identity.py` | 01 Identity | `users`, `channel_identities`, `user_profiles` |
| `002_memory.py` | 03 Memory | `memory_episodes`, `memory_facts` |
| `003_llm_routing.py` | 05 LLM Router | `llm_providers`, `llm_routing` |
| `004_policy.py` | 04 Policy | `app_config`, `safety_log` |
| `005_astrology.py` | 07 Astrology | ALTER `user_profiles` ADD birth_* |
| `006_daily_ritual.py` | 09 Daily Ritual | `daily_ritual_log`, ALTER `user_profiles` ADD daily_ritual_enabled |
| `007_billing.py` | 10 Billing | `subscriptions`, `quota_config` |
| `008_admin_config.py` | 11 Admin | seed `app_config` |

> Модули 02 (Telegram Adapter) и 06 (Dialog Service) не создают таблиц — миграций нет.

---

## Hard Constraints

- pgvector для retrieval — **ЗАПРЕЩЁН** (§12.1)
- Redis Streams как event bus — **ЗАПРЕЩЁН**
- Keycloak — **не в Этапе 1**
- Логировать ПДн (тексты сообщений, имена) — **ЗАПРЕЩЕНО**
- `user_id` из тела запроса — **ЗАПРЕЩЕНО**

---

## Риски

- Appsmith при первом запуске тянет ~2 GB Docker image — нормально, один раз
- NATS JetStream требует `--js` флага — учесть в docker-compose command
- asyncpg несовместим с PgBouncer в transaction mode — использовать session mode или прямое подключение

---

## conftest.py — обязательные фикстуры

```python
# tests/conftest.py

import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

TEST_DATABASE_URL = "postgresql+asyncpg://mirror:mirror@localhost:5432/mirror_test"

@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()

@pytest.fixture
async def db_session(engine):
    async with AsyncSession(engine) as session:
        yield session
        await session.rollback()

@pytest.fixture
async def client():
    from mirror.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

Добавить в `.env.example`:
```
TEST_DATABASE_URL=postgresql+asyncpg://mirror:mirror@localhost:5432/mirror_test
```

Создать тестовую БД: `createdb mirror_test` (один раз при настройке).

---

## Полное содержимое `.env.example`

```dotenv
# App
APP_ENV=development
SECRET_KEY=your-secret-key-min-32-chars
BASE_URL=https://your-ngrok-or-domain.com

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://mirror:mirror@localhost:5432/mirror
TEST_DATABASE_URL=postgresql+asyncpg://mirror:mirror@localhost:5432/mirror_test

# Redis
REDIS_URL=redis://localhost:6379/0

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

# RabbitMQ
RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# NATS
NATS_URL=nats://localhost:4222

# LLM
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-...
TELEGRAM_WEBHOOK_SECRET=your-webhook-secret-min-32-chars

# Admin
ADMIN_TOKEN=your-admin-token-min-32-chars

# Appsmith
APPSMITH_ENCRYPTION_PASSWORD=your-appsmith-password
APPSMITH_ENCRYPTION_SALT=your-appsmith-salt
APPSMITH_DB_URL=postgresql://appsmith_ro:appsmith_password@localhost:5432/mirror

# Sentry (опционально)
SENTRY_DSN=
```

---

## DoD

- Все Acceptance Criteria выполнены
- `pytest tests/test_health.py` — зелёный
- Все сервисы в `docker compose ps` в статусе `healthy` или `running`
- `.env.example` актуален (все переменные из Settings присутствуют)
