# Стек «Зеркало»: production-ready с первого дня

## Исполнительное резюме

Задача: собрать стек, который **не потребует переписывания при переходе от 0 до 100K пользователей**, максимально использует готовые open-source компоненты, и при этом решает все специфические задачи «Зеркала» — мультиканальность, персистентная память, астрорасчёты, проактивность, платежи. Ключевой принцип: писать только бизнес-логику, промпты и адаптеры каналов — всё остальное брать готовым.

**Синхронизация с POD:** актуальная каноническая спецификация — `Mirror_POD_v2.md` **v2.4** (§12 — NATS, Keycloak, Haystack, Temporal, Memory API; **§3.8–3.9** — психобезопасность и контуры Policy; **§7.6** — органические допродажи с `sales_allowed`). Этот документ — практическое дополнение к §12.4–§12.8.

***

## Архитектурный принцип: «монолит с вертикальными модулями»

Самая распространённая ошибка — строить микросервисы до Product-Market Fit. На 100K пользователей **монолит с чистыми модулями работает лучше**, чем преждевременно распределённая система. Вертикальные модули (astrology, tarot, memory, proactive, payments) изолированы внутри одного процесса — при необходимости каждый извлекается в отдельный сервис без переписывания интерфейсов.[^1]

Правило масштабирования (инфраструктура **с ПДн** — облако РФ, см. POD §13):
- **0–1K MAU:** Docker Compose / k3s: aiogram + FastAPI + PostgreSQL + Redis + RabbitMQ + **NATS JetStream** + Qdrant
- **1K–15K MAU:** k3s / K8s, managed PostgreSQL (РФ), горизонталь api + Celery workers + **KEDA**; **Temporal** при долгих Journey
- **15K–100K MAU:** Kubernetes + KEDA, Qdrant **≥3 ноды** при gold-standard, Redis Cluster, **Temporal** HA — переезд без смены прикладного кода[^2][^1]

***

## Слой 1: Каналы входа (адаптеры) — что брать готовым

### Telegram — aiogram 3

**Лучший выбор для старта.** Async-native, FSM из коробки, middleware, webhook + polling — меняется одной строкой.[^3]

```
pip install aiogram==3.x
```

Готовые boilerplate-шаблоны (берёте за основу, не пишете с нуля):

| Репозиторий | Что включает | Ссылка |
|---|---|---|
| `NotBupyc/aiogram-bot-template` | aiogram 3 + SQLAlchemy + Alembic + Redis + Docker | [^4] |
| `FajoX1/tgbotbase-aiogram3` | aiogram 3.x + Aiogram Dialog + i18n + Docker, Python 3.14 | [^5] |
| `kitty-ilnazik/telegram-bot-template` | aiogram + SQLAlchemy + Redis + Alembic + anti-spam | [^6] |

Рекомендация: взять `NotBupyc/aiogram-bot-template` как основу — там уже есть PostgreSQL, Redis, Docker, middleware для throttling, admin-фильтры.[^4]

### MAX (VK) и WhatsApp

- **MAX:** `pip install max-botapi-python` — официальный SDK, API идентичен Telegram[^7]
- **WhatsApp:** `pip install pywa` — Meta Cloud API, FastAPI out-of-the-box[^8]

Адаптеры — 50–100 строк каждый. Все три конвертируют входящие сообщения в единый `UnifiedMessage` (структура из вашего POD).[^7]

***

## Слой 2: API Gateway и шина — что брать готовым

### FastAPI + uvicorn

Единственный разумный выбор для Python async в 2026. Берём готовый шаблон:[^9]

| Репозиторий | Что включает |
|---|---|
| `onlythompson/fastapi-microservice-template` | FastAPI + PostgreSQL + Redis + Kafka + K8s + CI/CD[^1] |
| `serkanyasr/agentic_rag_project` | FastAPI + pgvector + Pydantic AI — Agentic RAG готовый[^10] |
| `alexandrughinea/python-fastapi-postgres-vector-scraper` | FastAPI + PostgreSQL + pgvector + Docker[^11] |

Рекомендация: взять `onlythompson/fastapi-microservice-template` как скелет — там уже есть CQRS-паттерн, feature flags, rate limiter, K8s манифесты.[^1]

### Очереди и шина событий

- **Redis** — **не** основная персистентная шина: только кэш, сессии, rate limit, L1-контекст, блокировки.
- **RabbitMQ + Celery** — исполнение задач (LLM, суммаризация, индексация): DLQ, приоритеты, привычные Python-воркеры.
- **NATS JetStream** — персистентные **события** с replay/retention: enrichment, консолидация памяти, fan-out в аналитику, reindex; consumer может быть отдельным воркером или публикатором в Celery.
- **Proactive:** **Celery Beat** — cron (утро, транзиты); **Temporal** — программы на **дни/недели** (см. слой 6a ниже).

Webhook + Celery: 200 OK сразу, обработка асинхронно.[^14]

### IAM (Web / Mobile)

- **Keycloak** — OIDC/OAuth2, SSO, social brokering; отдельный контейнер/кластер. Канальные боты при необходимости живут без Keycloak в первые версии; **Identity** связывает `global_user_id` и аккаунты Keycloak после логина в вебе.

### Policy, кризис и рекомендации (POD §3.8–§3.9, §7.6)

В прикладном коде — единый **Policy Engine** до/после LLM: `risk_level`, `sales_allowed`, блок мистики в кризисе, выбор шаблона ответа. Технически:

- **Быстрые правила + классификатор** (отдельный вызов модели или rule-pack) и при наличии — **Moderation API** провайдера для self-harm/violence.
- **Redis** — краткоживущие **offer_readiness** / rate-limit показов партнёрских офферов (см. §7.6 POD).
- **PostgreSQL** — каталог партнёров и товаров; **append-only** или отдельная роль для записи **safety events** (без массового UPDATE чувствительных логов).
- **Qdrant / Haystack** — curated KB кризисных контактов и скриптов (регион, язык).
- Опционально **PostHog** (self-hosted) — A/B формулировок **вне** кризисной ветки.

***

## Слой 3: Память — ключевой слой «Зеркала»

### Выбор: Mem0 self-hosted + pgvector

Это самое важное архитектурное решение. Mem0 реализует именно ту четырёхуровневую память, которая описана в вашем POD:[^15][^16]

| Уровень памяти в POD | Реализация через Mem0 |
|---|---|
| L0 — Context Window | Стандартный system prompt |
| L1 — Session Cache | Redis TTL (Mem0 session memory) |
| L2 — Episode Memory | pgvector (суммаризации) |
| L3 — Semantic Memory | pgvector (извлечённые факты) |

**Почему Mem0, а не самописное решение:**
- +26% качества vs хранение полной истории, −80% токенов[^15]
- p95 latency **1.44 секунды** — пользователь не ждёт[^15]
- Self-hosted на pgvector — уже есть в вашем стеке, нет нового сервиса
- Apache 2.0, ~48K GitHub Stars[^17]

```python
from mem0 import Memory

config = {
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "host": "postgres",
            "dbname": "mirror_db",
            "collection_name": "user_memories",
            "embedding_model_dims": 1536
        }
    },
    "llm": {
        "provider": "openai",
        "config": {"model": "gpt-4o-mini", "temperature": 0}
    },
    "embedder": {
        "provider": "openai",
        "config": {"model": "text-embedding-3-small"}
    },
    # прод: хранить метаданные/историю Mem0 в PostgreSQL, не в SQLite (см. POD §9.6)
}

m = Memory.from_config(config)

# После каждого диалога — автоматически извлечёт факты (цели, страхи, предпочтения)
await asyncio.to_thread(m.add, messages, user_id=str(global_user_id))

# При сборке контекста
memories = await asyncio.to_thread(
    m.search, user_message, user_id=str(global_user_id), limit=10
)
```

Интеграция Mem0 с Telegram через Make/n8n доступна визуально без кода, но для production рекомендуется Python SDK напрямую.[^18] **Внешний контракт** — только **Memory API** «Зеркало» (POD §9.6); Mem0 за адаптером.

***

## Слой 4: База данных — pgvector vs Qdrant

Ключевой вопрос: нужен ли отдельный Qdrant, или pgvector справится?

| Сценарий | Что использовать |
|---|---|
| Пользовательская память (факты, эпизоды) | **Опция A:** **pgvector** в PostgreSQL (ACID с профилем)[^19] |
| То же | **Опция B:** вектора в **Qdrant** (`user_memory`), метаданные/факты в Postgres; фильтр `user_id` |
| База знаний (таро, астро-тексты, психология) | **Qdrant** — коллекция `knowledge_chunks`; при B — единый операционный контур векторов[^20] |
| До 1M векторов | pgvector справляется на SSD[^2] |
| 1M–10M+ векторов | Qdrant обгоняет pgvector по latency в 2–3× |

**Вывод для «Зеркала»:** по умолчанию **опция A** (память в pgvector + KB в Qdrant). **Опция B** — всё retrieval в Qdrant при упрощении эксплуатации или росте QPS; переключение на уровне адаптера retrieval, без смены доменной модели (POD §12). Объём см. POD §17.[^7]

### Объектное хранилище

Предпочтительно **managed S3-совместимое** (РФ). **MinIO** self-hosted — только после проверки **актуальной** лицензии и модели дистрибутива (community vs коммерческие продукты).

Docker Compose для Qdrant self-hosted (production-ready):[^21][^2]

```yaml
qdrant:
  image: qdrant/qdrant:v1.7.4
  container_name: qdrant
  restart: unless-stopped
  ports:
    - "6333:6333"
    - "6334:6334"
  volumes:
    - qdrant_data:/qdrant/storage
  environment:
    - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY}
  ulimits:
    nofile:
      soft: 65536
      hard: 65536
```

***

## Слой 5: Астрологические расчёты — Kerykeion

```
pip install kerykeion
```

Kerykeion — обёртка над pyswisseph (Swiss Ephemeris), даёт и расчёты, и SVG-карты:[^22]

```python
from kerykeion import AstrologicalSubject, NatalChartSVG
from datetime import datetime

# Натальная карта
subject = AstrologicalSubject(
    "User_123",
    year=birth_date.year,
    month=birth_date.month,
    day=birth_date.day,
    hour=birth_time.hour,
    minute=birth_time.minute,
    city=city,
    nation=country_code,
    tz_str=timezone
)

# Все планеты, дома, аспекты
natal_data = {
    "sun": {"sign": subject.sun.sign, "position": subject.sun.position, "house": subject.sun.house},
    "moon": {"sign": subject.moon.sign, "position": subject.moon.position},
    "venus": {"sign": subject.venus.sign, "position": subject.venus.position},
    # ... все планеты
}

# Кэшируем результат в user_profile.natal_chart (JSONB)
# Swiss Ephemeris больше не вызываем — только читаем из кэша

# SVG натальная карта для отправки
chart = NatalChartSVG(subject, new_output_directory="/tmp")
chart.makeSVG()
# → /tmp/User_123_Natal_Chart.svg
```

**Важно:** расчёт Swiss Ephemeris делается один раз при онбординге и кэшируется в PostgreSQL (поле `natal_chart JSONB`). Транзиты — вычисляются ежедневно через Celery Beat и кэшируются в Redis на 24 часа.

***

## Слой 6: LLM оркестрация и RAG

### LangGraph + Haystack

- **LangGraph** — основной оркестратор: режимы (компаньон, таро, игра), tools, checkpointing, pause/resume (POD §12).
- **Haystack** — слой **ingestion и retrieval**: чанкинг документов админки, document store, retrievers, reranking для базы знаний; вызывается из узлов графа или отдельного микросервиса, **не** заменяет LangGraph.

Узел графа типично параллелит: `memory_api.search`, Haystack/Qdrant KB, Redis-история — целевой бюджет контекста как в POD (~2k токенов).[^7]

### LLM Router (fallback)

```python
LLM_ROUTER = {
    "free_basic": "gpt-4o-mini",
    "plus_pro":   "gpt-4o",
    "fallback_1": "claude-3-5-haiku",
    "fallback_2": "llama-3.3-70b",  # self-hosted GPU при необходимости (периметр по политике РФ)
}
```

## Слой 6a: Долгие Journey — Temporal

- **Temporal** — саги на дни/недели: онбординг-серии, коучинговые программы, восстановление шага после сбоя.
- **Celery Beat** остаётся для **простых** cron (утренний ритуал, ночной пересчёт транзитов).

***

## Слой 7: Proactive Scheduler — Celery Beat

Проактивное поведение бота («живёт, пишет первым») — через Celery Beat:[^13][^12]

```python
# tasks/proactive.py
from celery import Celery
from celery.schedules import crontab

app = Celery('mirror')

@app.task
async def send_morning_ritual():
    """Утренний ритуал — 07:30 для morning-users, 09:00 для остальных"""
    users = await get_users_for_morning_ritual()
    for user in users:
        await dispatch_message(user.channel, user.global_id, "morning_ritual")

@app.task
async def send_astro_event(user_id: str, event_type: str, planet: str):
    """Оповещение о транзите — отложенная задача"""
    await dispatch_astro_notification(user_id, event_type, planet)

@app.task
async def check_inactive_users():
    """Эмоциональный чекин — если молчит >48 часов"""
    inactive = await get_inactive_users(hours=48)
    for user in inactive:
        if user.proactive_enabled:
            await dispatch_checkin(user)

# Расписание
app.conf.beat_schedule = {
    'morning-ritual': {
        'task': 'tasks.proactive.send_morning_ritual',
        'schedule': crontab(hour=7, minute=30),
    },
    'check-inactive': {
        'task': 'tasks.proactive.check_inactive_users',
        'schedule': crontab(minute='*/30'),  # каждые 30 минут
    },
    'daily-transits': {
        'task': 'tasks.astro.calculate_daily_transits',
        'schedule': crontab(hour=3, minute=0),  # ночью — кэш на день
    },
}
```

***

## Слой 8: Платежи — полная интеграция

### Telegram Stars (нулевая комиссия для продавца)

```python
# handlers/payments/stars.py
from aiogram.types import LabeledPrice

async def send_subscription_invoice(bot, user_id: int, tier: str):
    prices = {
        "basic": 299 * 100,   # Telegram Stars в нано-Stars? Нет — Stars это целые
        "plus":  599,          # 599 Stars ≈ 599 × 1.5₽ ≈ 899₽ (примерно)
        "pro":   999,
    }
    await bot.send_invoice(
        chat_id=user_id,
        title=f"Подписка «Зеркало» {tier.capitalize()}",
        description="AI-компаньон для самопознания",
        payload=f"sub_{tier}_{user_id}",
        currency="XTR",      # Telegram Stars
        prices=[LabeledPrice(label=f"Тариф {tier}", amount=prices[tier])],
        provider_token="",   # пустой для Stars
    )

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def payment_success(message: Message):
    payload = message.successful_payment.invoice_payload
    # tier и user_id из payload → активировать подписку
    await activate_subscription(payload)
```

### ЮKassa (рублёвые карты, СБП)

```python
from yookassa import Configuration, Payment

Configuration.account_id = settings.YUKASSA_SHOP_ID
Configuration.secret_key = settings.YUKASSA_SECRET_KEY

async def create_yukassa_payment(user_id: str, amount: int, tier: str) -> str:
    payment = Payment.create({
        "amount": {"value": str(amount), "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": f"{settings.BASE_URL}/payment/success?user={user_id}"
        },
        "capture": True,
        "description": f"Подписка «Зеркало» {tier} — {amount}₽",
        "metadata": {"user_id": user_id, "tier": tier},
        "payment_method_data": {"type": "sbp"}  # или "bank_card"
    })
    return payment.confirmation.confirmation_url  # отправляем пользователю
```

### Сравнение способов оплаты для «Зеркала»

| Метод | Каналы | Комиссия | Требования | Рекомендация |
|---|---|---|---|---|
| Telegram Stars | TG, MAX | 0% для продавца | Без юрлица | **MVP — начать здесь** |
| ЮKassa СБП | Все | 0.1–0.7% | ИП/ООО | **Production RU** |
| ЮKassa карта | Все | 2.8–3.5% | ИП/ООО | Production RU |
| TON Connect | TG, Web | ~1% | Без юрлица | Криптосегмент |
| Stripe | Web, СНГ | 2.9%+30¢ | Юрлицо EU/KZ | Казахстан, Беларусь |
| VK Pay | VK Mini App | 1–3.5% | ИП/ООО | VK-канал |

***

## Итоговая карта: что берём готовым vs пишем сами

### Берём готовым (open-source, не трогаем)

| Компонент | Проект | Лицензия |
|---|---|---|
| Telegram-бот основа | `NotBupyc/aiogram-bot-template`[^4] | MIT |
| FastAPI скелет | `onlythompson/fastapi-microservice-template`[^1] | MIT |
| Память (внутр. ускоритель) | `mem0ai/mem0`[^16] | Apache 2.0 |
| Астрорасчёты | `kerykeion` + `pyswisseph`[^22] | LGPL / коммерческая |
| Векторный поиск | `qdrant/qdrant`[^23] | Apache 2.0 |
| RAG pipelines | `deepset-ai/haystack` | Apache 2.0 |
| Оркестрация агента | `langgraph` | MIT |
| Очереди задач | `celery` + `rabbitmq` | BSD / MPL |
| Event bus | **NATS Server** + JetStream | Apache 2.0 |
| Долгие workflow | **Temporal** | MIT |
| IAM Web | **Keycloak** | Apache 2.0 |
| Кэш / лимиты | `redis` | BSD |
| Миграции БД | `alembic` | MIT |
| ORM | `sqlalchemy` async | MIT |
| Наблюдаемость | OpenTelemetry + Prometheus + Grafana | |
| Ошибки приложения | `sentry-sdk` | BSL |

### Пишем сами (только бизнес-логика)

| Что | Сложность | Время |
|---|---|---|
| Адаптеры каналов (UnifiedMessage) | Низкая | 2–3 дня |
| Intent Router (классификатор режима) | Средняя | 3–5 дней |
| Сборщик контекста (build_context) | Средняя | 3–4 дня |
| Системные промпты по режимам | Нет кода | 1–2 недели |
| Proactive Scheduler логика | Средняя | 3–5 дней |
| Механика «занят» | Низкая | 1 день |
| YAML-движок игр | Средняя | 1 неделя |
| Астро-сервис (обёртка над Kerykeion) | Низкая | 2–3 дня |
| Платёжная логика (webhooks, активация) | Средняя | 3–5 дней |
| Админ-панель | Средняя | 2–3 недели |

**Итого до MVP (Telegram + Астрология + Таро + Память + Платежи):** ~6–8 недель при одном full-stack разработчике, если взять готовые boilerplate-шаблоны.[^7]

***

## Docker Compose (prod-старт) — ориентировочный файл

Добавлены **NATS** (JetStream) и сохранены RabbitMQ+Celery. **Keycloak** и **Temporal** вынесите отдельными сервисами при подключении web и долгих Journey (см. официальные образы).

```yaml
version: '3.9'

services:
  # ── Telegram бот ──────────────────────────────────────
  bot:
    build: ./bot
    env_file: .env
    depends_on: [postgres, redis]
    restart: unless-stopped
    volumes:
      - ephemeris_data:/app/ephemeris

  # ── FastAPI API ────────────────────────────────────────
  api:
    build: ./api
    env_file: .env
    ports:
      - "8000:8000"
    depends_on: [postgres, redis, qdrant, nats]
    restart: unless-stopped

  # ── NATS JetStream (события, replay) ───────────────────
  nats:
    image: nats:2-alpine
    command: ["-js", "-sd", "/data", "-m", "8222"]
    ports:
      - "4222:4222"
      - "8222:8222"
    volumes:
      - nats_data:/data
    restart: unless-stopped

  # ── Celery воркер (LLM задачи) ─────────────────────────
  worker:
    build: ./api
    command: celery -A app.celery worker -Q llm_tasks -c 4
    env_file: .env
    depends_on: [redis, rabbitmq]
    restart: unless-stopped

  # ── Celery Beat (проактивность) ────────────────────────
  scheduler:
    build: ./api
    command: celery -A app.celery beat --loglevel=info
    env_file: .env
    depends_on: [redis]
    restart: unless-stopped

  # ── PostgreSQL + pgvector ──────────────────────────────
  postgres:
    image: pgvector/pgvector:pg16
    env_file: .env
    environment:
      POSTGRES_DB: mirror_db
      POSTGRES_USER: mirror
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql
    restart: unless-stopped

  # ── Redis ──────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    restart: unless-stopped

  # ── RabbitMQ ───────────────────────────────────────────
  rabbitmq:
    image: rabbitmq:3-management-alpine
    environment:
      RABBITMQ_DEFAULT_USER: mirror
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD}
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    restart: unless-stopped

  # ── Qdrant (knowledge base) ────────────────────────────
  qdrant:
    image: qdrant/qdrant:v1.7.4
    environment:
      - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY}
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped

  # ── Nginx reverse proxy ────────────────────────────────
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - certbot_data:/etc/letsencrypt
    depends_on: [api]
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  rabbitmq_data:
  qdrant_data:
  nats_data:
  ephemeris_data:
  certbot_data:
```

Развёртывание с **ПДн** — в инфраструктуре РФ по POD §13; только пример состава сервисов.[^7]

***

## Переход к 100K: что меняется и что не меняется

| Компонент | Compose / k3s | 100K (Kubernetes) | Что меняется |
|---|---|---|---|
| Код бота | aiogram 3 | aiogram 3 | Ничего |
| Код API | FastAPI | FastAPI | Ничего |
| Оркестратор | LangGraph | LangGraph | Ничего |
| RAG слой | Haystack | Haystack | Топология воркеров |
| Память | Memory API + pgvector (опц. Mem0) | То же или Qdrant опция B | Топология |
| События | NATS JetStream | NATS cluster | Репликация |
| Задачи | Celery + RabbitMQ | То же + KEDA | Реплики воркеров |
| Journey | Celery Beat; Temporal при сагах | Temporal HA | — |
| Web IAM | Keycloak по мере запуска web | Keycloak HA | — |
| Астрорасчёты | Kerykeion local | Отдельный pod | Масштаб |
| БД | PostgreSQL single | PostgreSQL HA | Топология |
| Redis | Single | Redis Cluster | Топология |
| Деплой | compose / k3s | ArgoCD + Helm | CI/CD |
| LLM роутинг | По POD §12.6 | + circuit breaker | Политики |

**Главный вывод:** при правильном выборе стека сейчас — весь прикладной код остаётся без изменений. Меняется только инфраструктурный слой (Docker Compose → Kubernetes), который никак не связан с бизнес-логикой.[^2][^1]

***

## Порядок сборки MVP (недели)

**Неделя 1–2: Скелет**
1. Клонировать `NotBupyc/aiogram-bot-template` + `onlythompson/fastapi-microservice-template`
2. Настроить Docker Compose (добавить Qdrant, Mem0)
3. Реализовать `UnifiedMessage` + channel adapter для Telegram
4. Базовая схема БД (миграции Alembic): `user_profiles`, `channel_identities`, `user_memories`, `user_episodes`

**Неделя 3: Астрология и память**
5. Интегрировать Kerykeion → Natal Chart Service
6. Подключить Mem0 к pgvector
7. Реализовать `build_context()` — параллельный RAG
8. Первый системный промпт «Астролог»

**Неделя 4: Режимы и Таро**
9. Intent Router (gpt-4o-mini классификатор)
10. Таро-модуль (78 карт в Qdrant knowledge base)
11. Ежедневный ритуал (Celery Beat 07:30)
12. Онбординг (сбор даты рождения → натальная карта)

**Неделя 5: Платежи и подписки**
13. Telegram Stars invoice flow
14. ЮKassa СБП + webhook
15. Subscription middleware в aiogram (проверка тарифа)
16. Grace period + retry logic

**Неделя 6: Шлифовка и деплой**
17. Sentry + базовый мониторинг
18. Nginx + SSL на Hetzner
19. Базовая Admin API (FastAPI endpoint для управления промптами)
20. Smoke tests + нагрузочный тест (Locust)

**Результат через 6 недель:** рабочий Telegram-бот «Зеркало» с астрологией, таро, памятью, платежами — готовый к первым пользователям.[^7]

---

## References

1. [onlythompson/fastapi-microservice-template - GitHub](https://github.com/onlythompson/fastapi-microservice-template) - This template provides a robust starting point for building scalable, maintainable, and efficient mi...

2. [When Self Hosting Vector Databases Becomes Cheaper Than SaaS](https://openmetal.io/resources/blog/when-self-hosting-vector-databases-becomes-cheaper-than-saas/) - Use this simple formula: Monthly Pinecone Bill = Storage Cost + (Queries × Read Cost) + (Writes × Wr...

3. [Aiogram - Asynchronous Telegram Bot Framework - DEV Community](https://dev.to/imrrobot/aiogram-asynchronous-telegram-bot-framework-2fkp) - Aiogram is a Python library for creating Telegram bots using asynchronous programming. It provides a...

4. [README.md - NotBupyc/aiogram-bot-template - GitHub](https://github.com/NotBupyc/aiogram-bot-template/blob/main/README.md) - Used technologies: Aiogram 3.x (Telegram bot framework); SQLAlchemy (working with database from Pyth...

5. [FajoX1/tgbotbase-aiogram3: Telegram bot template for Aiogram 3.x.](https://github.com/FajoX1/tgbotbase-aiogram3) - Telegram bot template for Aiogram 3.x. Contribute to FajoX1/tgbotbase-aiogram3 development by creati...

6. [Telegram Bot Template: a flexible Python aiogram boilerplate ...](https://github.com/kitty-ilnazik/telegram-bot-template) - Telegram Bot Template is a flexible boilerplate for creating Telegram bots in Python using aiogram. ...

7. [Mirror_POD_v2.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/58550804/899579ae-49a3-4c52-a372-605ebbd2fbfd/Mirror_POD_v2.md?AWSAccessKeyId=ASIA2F3EMEYEZ6JFREPS&Signature=RVAE8bwYwh00rDgwwP5J29nWD2c%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEEkaCXVzLWVhc3QtMSJHMEUCICwaT1tvNgOKoS%2BtFlb3tsOgrQzrATorPkKl9qNb5AU8AiEAlj0JilnzeEZOe0c85EfDiCNq0TfpNyCt7EskmjUQ20Mq8wQIEhABGgw2OTk3NTMzMDk3MDUiDGCRkhZFbpPxnImSDirQBD1jxLkPeg6sJclRqG8sX0zw%2BvkicnJDWjw5PkHQIgOAX98SZGpXTpixZs6FGHl35jKMOnN2%2BhkGmlQlhrD6hfffeeblHj6zJju%2B35%2Fj0dhmFkMln7%2FDCaJiB1BcWF649OqM%2BmrCHJdUIoXcScEZbgomuobwODtHE1eLQsphIZ9XYKE1uedSUv4e7yEdZbeNcRCK2SChs6rAoDi1SsokZtgkhzOfwMV%2F%2FFPEv2RTldioTVTUuymzMXFSJ1t9FYSFwev1wcOFUWYomVZXMBENP3nGrRzh4Cn%2Fi%2BZJjaBQWi8%2B3jp8LuKEEdLrAWnj%2FkokRffldQwBq8zqKXV2gXuFlz6xMpM3AUJrvEXSJeXXQsKJWhfl5zyxYO%2FMH6W%2Bl8HO2p2Whupe8sCiN08ESn8HkyS%2BKys6b5%2FNyOrFOAlWjYwlMA3RVOUFs5S1wYpRe7%2FdfFBWQjf0f3Ikn1d1mkng%2B51gMGuUtfrbqwmA2LfXf2%2BLNPrvNywYz%2BsRFaLS4U89ClxmX5B4cOFgVT1JPFnOKhgLsZmHtTbW4QD8%2BPulN08n0T3j5p%2F4yBINZ%2F%2BnlOY2nq8K%2Bq8qr1VnWXEd%2Fomjv4ypZGp5nBAuJtQgUvGmu9V0VD%2FrwkImFdLUBKdaWA5OrR5pu%2BYELZ55ynHadYbijXP1w%2Fzf0rv9P8zT%2FtvlGhKueQ4p5m8%2BJA3vIEJw8jFEYX%2FmfCc3QlZwLper7Bk2yya2QjXhVdyzoQ2EeL3Cg5wWIce0IZa57qSyhbZKC5Q1mX5m1PKNU3ZDJ8l3RsA3%2FIgwv7alzgY6mAGal5OVOkel0g7goQkgSIDg1Z89mT5JkinFnuZjQ6DabcAOgfKXDB6EBRCsS63IX4Hha80XU827goe8RvRZEbO1sQKBQupk2UTBHMuK5EabPyMaPPA6jvB1Dgge73dfXGwBxKQwVJr9WlHSqt5KMCMXpaQuFo6K7rla%2BfGGHOi8837vkdyR4h7FDuvUq1FFw1p3FKa2zMe6aA%3D%3D&Expires=1774807314) - # ЗЕРКАЛО — AI-компаньон для самопознания
## Product Overview Document (POD) · Версия 2.0 · Март 202...

8. [PyWa • Python wrapper for the WhatsApp Cloud API](https://pywa.readthedocs.io/en/2.2.0/) - PyWa • Python wrapper for the WhatsApp Cloud API

9. [FastAPI + PostgreSQL Starter Kit - GitHub](https://github.com/bibektimilsina00/FastAPI-PgStarterKit) - FastAPI + PostgreSQL Starter Kit: A streamlined template for building backends with FastAPI, Postgre...

10. [serkanyasr/agentic_rag_project: Scalable Agentic RAG ... - GitHub](https://github.com/serkanyasr/agentic_rag_project) - A modern Agentic RAG (Retrieval-Augmented Generation) system built with Pydantic AI, FastAPI, and Po...

11. [FastAPI PostgreSQL Web Scraper with Vector Similarity Search](https://github.com/alexandrughinea/python-fastapi-postgres-vector-scraper) - A powerful web scraping and content similarity search application built with FastAPI, PostgreSQL wit...

12. [Python telegram bot celery start conflict](https://stackoverflow.com/questions/72946881/python-telegram-bot-celery-start-conflict) - I have a very simple telegram bot and want to send an automated message to my bot users every 1 hour...

13. [Periodic and Non periodic tasks with Django + Telegram + Celery](https://stackoverflow.com/questions/70065507/periodic-and-non-periodic-tasks-with-django-telegram-celery) - I am building a project based on Django and one of my intentions is to have a telegram bot which is ...

14. [Telegram bot using Celery and Django #2792 - GitHub](https://github.com/python-telegram-bot/python-telegram-bot/discussions/2792) - Hi,. I am using Django + Celery and I want to create a telegram bot using this library. I do not kno...

15. [Mem0: Building Production-Ready AI Agents with Scalable Long ...](https://arxiv.org/html/2504.19413v1) - We introduce Mem0, a scalable memory-centric architecture that addresses this issue by dynamically e...

16. [AI Memory Layer for LLMs and AI Agents - Mem0](https://mem0.ai/blog/introducing-mem0) - Mem0 AI memory layer enables personalized LLM applications with long-term memory for user preference...

17. [Mem0 vs Letta (MemGPT): AI Agent Memory Compared (2026)](https://vectorize.io/articles/mem0-vs-letta) - Mem0 vs Letta (MemGPT) — compare passive memory extraction with self-editing agent runtime for AI ag...

18. [Mem0 and Telegram Bot Integration | Workflow Automation - Make](https://www.make.com/en/integrations/mem0/telegram) - Connect Mem0 and Telegram Bot to sync data between apps and create powerful automated workflows. Int...

19. [pgvector vs Qdrant: PostgreSQL Extension or Dedicated Vector ...](https://encore.dev/articles/pgvector-vs-qdrant) - Self-hosted, that means a Docker container (or Kubernetes deployment), its own storage volume, its o...

20. [Which Vector DB should I use for production? : r/Rag - Reddit](https://www.reddit.com/r/Rag/comments/1qlftqz/which_vector_db_should_i_use_for_production/) - If you want a purpose-built vector DB, Qdrant. Best latency performance in most independent tests, a...

21. [Docker Compose for OpenWebUI + Postgres + Qdrant - GitHub](https://github.com/danielrosehill/OpenWebUI-Postgres-Qdrant) - Given the high probability that these docs will become rapidly outdated and soon after obsolete, the...

22. [astroahava/astro-sweph: High precision Swiss Ephemeris ... - GitHub](https://github.com/astroahava/astro-sweph) - A high-performance WebAssembly interface to the Swiss Ephemeris astronomical library, providing prec...

23. [Installation - Qdrant](https://qdrant.tech/documentation/operations/installation/) - However, you can also use Docker and Docker Compose to run Qdrant in production, by following the se...

