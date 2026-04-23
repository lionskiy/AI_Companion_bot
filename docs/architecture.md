# Mirror — Архитектура приложения

## Обзор

Mirror — персонализированный AI-компаньон в Telegram. Помогает пользователю в самопознании через астрологию, таро и психологические диалоги. Архитектура — **модульный монолит**: все модули в одном Python-процессе, но с чёткими границами и независимыми зонами ответственности.

---

## Технологический стек

| Категория | Технология |
|-----------|-----------|
| Язык | Python 3.12, async/await |
| Web-фреймворк | FastAPI |
| Telegram | aiogram 3, polling или webhook |
| Оркестрация диалога | LangGraph |
| ORM | SQLAlchemy 2 async + Alembic |
| Очереди задач | Celery + RabbitMQ |
| События | NATS JetStream |
| Реляционная БД | PostgreSQL |
| Векторная БД | Qdrant |
| Кэш / сессии | Redis |
| LLM | OpenAI API (GPT-4o, GPT-4o-mini, text-embedding-3-large) |
| Логирование | structlog, JSON |
| Admin UI | Vanilla JS + Bootstrap 5 (встроен в FastAPI) |
| Метрики | prometheus-fastapi-instrumentator |

---

## Структура модулей

```
mirror/
├── main.py                  # FastAPI app + lifespan (startup/shutdown)
├── config.py                # Pydantic Settings, все переменные из .env
├── dependencies.py          # FastAPI DI-зависимости
├── logging_setup.py         # structlog настройка
│
├── channels/                # Адаптеры каналов (нормализация)
│   ├── base.py              # UnifiedMessage, UnifiedResponse
│   └── telegram/
│       ├── adapter.py       # TelegramAdapter — TG → UnifiedMessage
│       ├── handlers.py      # aiogram роутер, команды (/start, /help...)
│       └── webhook.py       # FastAPI webhook endpoint
│
├── core/                    # Ядро — не зависит от каналов
│   ├── identity/
│   │   ├── service.py       # IdentityService — get_or_create пользователя
│   │   └── jwt_handler.py   # JWT encode/decode для Admin API
│   ├── llm/
│   │   ├── router.py        # LLMRouter — роутинг по task_kind, retry, fallback
│   │   └── exceptions.py    # AllModelsUnavailableError
│   ├── memory/
│   │   ├── service.py       # MemoryService — L1/L2/L3 памяти
│   │   ├── session.py       # L1 Redis session history
│   │   └── qdrant_init.py   # Инициализация Qdrant коллекций при старте
│   └── policy/
│       ├── safety.py        # PolicyEngine — кризисный протокол §3.8
│       ├── models.py        # PolicyResult, RiskLevel
│       └── patterns.py      # Быстрый regex-матчинг до LLM
│
├── services/                # Прикладная бизнес-логика
│   ├── dialog.py            # DialogService.handle() — точка входа диалога
│   ├── dialog_graph.py      # LangGraph граф — узлы intent/policy/mode/response
│   ├── dialog_state.py      # TypedDict DialogState
│   ├── intent_router.py     # IntentRouter — LLM-классификация интентов
│   ├── astrology.py         # AstrologyService — натальная карта + транзиты
│   ├── tarot.py             # TarotService — расклады + интерпретации
│   ├── tarot_deck.py        # 78 карт таро с описаниями
│   ├── daily_ritual.py      # DailyRitualService — карта дня + аффирмация
│   └── billing.py           # BillingService — quota check + Redis rate limit
│
├── models/                  # SQLAlchemy ORM модели
│   ├── user.py              # User, ChannelIdentity, UserProfile, Subscription
│   ├── memory.py            # MemoryEpisode, MemoryFact
│   ├── billing.py           # QuotaConfig
│   ├── llm.py               # LLMProvider, LLMRouting
│   ├── policy.py            # SafetyLog
│   └── intent_log.py        # IntentLog
│
├── db/
│   ├── session.py           # async_session_factory, init/close, ensure_db_pool
│   └── migrations/versions/ # 012 Alembic миграций
│
├── events/
│   ├── nats_client.py       # NATSClient — publish/subscribe
│   ├── consumers/memory.py  # NATS consumer → Celery задачи
│   └── publishers/          # dialog.py, safety.py publishers
│
├── rag/
│   ├── psych.py             # search_psych_knowledge() → Qdrant knowledge_psych
│   ├── astrology.py         # search_astro_knowledge()
│   └── tarot.py             # search_tarot_knowledge()
│
├── workers/
│   ├── celery_app.py        # Celery app config + RabbitMQ broker
│   └── tasks/
│       ├── memory.py        # summarize_episode, extract_facts
│       ├── profile.py       # update_psych_profile
│       └── daily_ritual.py  # dispatch_daily_rituals (Celery Beat)
│
└── admin/
    ├── router.py            # FastAPI admin API (все /admin/* эндпоинты)
    ├── schemas.py           # Pydantic схемы admin API
    └── ui.py                # Встроенный HTML/JS admin UI (Bootstrap 5)
```

---

## Поток сообщения

```
Telegram
  ↓
aiogram Handler (handlers.py)
  ↓
TelegramAdapter.to_unified()           ← идентификация пользователя (IdentityService)
  ↓                                    ← сессия (Redis)
UnifiedMessage
  ↓
DialogService.handle()
  ├── BillingService.check_quota()     ← Redis quota check + increment
  └── LangGraph.ainvoke(DialogState)
        ├── classify_intent_node       ← LLM (intent_classify)
        ├── check_policy_node          ← PolicyEngine (regex → LLM crisis_classify)
        ├── route_mode_node            ← MemoryService + RAG psych_knowledge
        └── generate_response_node    ← Astrology / Tarot / Ritual / Chat LLM
  ↓
add_to_session (Redis L1)
  ↓
_log_intent (PostgreSQL intent_log)
  ↓
UnifiedResponse → TelegramAdapter.send() → Telegram
```

---

## LangGraph граф

4 узла, скомпилированы в `build_dialog_graph()`:

```
classify_intent → check_policy → (если blocked: END) → route_mode → generate_response → END
```

**classify_intent** — LLM классификация в одно из: `astrology | tarot | daily_ritual | chat | help | cancel | onboarding`

**check_policy** — двухуровневая проверка:
1. `fast_pattern_match()` — regex по ключевым словам (кризис, суицид, насилие)
2. Если сработал — LLM `crisis_classify` для уточнения уровня `wellbeing | concern | crisis`
3. При `crisis`: блокирует ответ, подставляет кризисный шаблон + телефон 8-800-2000-122

**route_mode** — параллельно загружает:
- `memory_service.get_session_history(uid)` → последние N сообщений из Redis
- `memory_service.search(uid, message)` → L2/L3 из Qdrant + PostgreSQL
- `search_psych_knowledge(message)` → RAG из `knowledge_psych`

**generate_response** — маршрутизирует к нужному сервису:
- `astrology` → AstrologyService
- `tarot` → TarotService
- `daily_ritual` → DailyRitualService
- всё остальное → `_chat_response()` → LLM `main_chat` / `main_chat_premium`

---

## Система памяти

| Уровень | Хранилище | TTL | Содержимое |
|---------|-----------|-----|-----------|
| **L0** | Context Window | per-request | Последние 10 сообщений сессии |
| **L1** | Redis `session:{uid}` | 48 ч | История сообщений текущей сессии |
| **L2** | PostgreSQL `memory_episodes` + Qdrant `user_episodes` | permanent | Сжатые резюме завершённых сессий |
| **L3** | PostgreSQL `memory_facts` + Qdrant `user_facts` | permanent | Извлечённые факты о пользователе |

**Psych Profile** — `user_profiles` (PostgreSQL JSONB): `mbti_type`, `attachment_style`, `communication_style`, `dominant_themes`, `profile_summary`. Обновляется Celery-задачей `update_psych_profile`.

**Жизненный цикл:**
1. Сессия закрывается при бездействии > `SESSION_IDLE_SECONDS` → NATS событие `mirror.dialog.session.closed`
2. NATS consumer → Celery: `summarize_episode` (LLM → L2) + `extract_facts` (LLM → L3)
3. После N эпизодов → `update_psych_profile` (LLM → PostgreSQL)

**RLS:** `memory_episodes`, `memory_facts`, `user_companion_persona`, `journal_entries` — Row Level Security в PostgreSQL.

---

## LLM Router

`LLMRouter` читает конфигурацию роутинга из PostgreSQL (`llm_routing`):

```
task_kind + tier → provider_id + model_id + fallback_chain + max_tokens + temperature
```

- Primary модель: 3 попытки с паузой 2с при rate limit / timeout
- Fallback chain: при исчерпании попыток — следующий провайдер/модель
- При полном отказе: `AllModelsUnavailableError`
- Роутинг кэшируется в памяти, сбрасывается через Admin API

**Канонические task_kinds:** `main_chat`, `main_chat_premium`, `intent_classify`, `crisis_classify`, `memory_summarize`, `memory_extract_facts`, `tarot_interpret`, `astro_interpret`, `game_narration`, `proactive_compose`, `persona_evolve`, `embedding`

---

## Identity

При каждом сообщении `TelegramAdapter.to_unified()` вызывает `IdentityService.get_or_create()`:

- Ищет `ChannelIdentity` по `(channel="telegram", channel_user_id)`
- Если нашёл — сравнивает TG-метаданные (имя, username, is_premium), обновляет при изменении
- Если нет — создаёт в одной транзакции: `User` + `ChannelIdentity` + `UserProfile` + `Subscription(tier="free")`
- Timezone определяется из `language_code` (ru → Europe/Moscow, uk → Europe/Kiev и т.д.)

---

## Billing

`BillingService.check_quota(uid, tier, quota_type)`:
- Читает лимиты из PostgreSQL `quota_config` (или дефолт 20/3/3)
- Lua-скрипт в Redis: атомарно инкрементирует счётчик `quota:{uid}:{type}:{date}`, проверяет лимит
- При превышении → `QuotaExceededError`
- Счётчики TTL до полуночи UTC

---

## Policy & Safety (§3.8)

Обязательный контур на каждое сообщение:

1. `fast_pattern_match()` — regex матчинг по словарю кризисных паттернов (быстро, без LLM)
2. Если сработал — LLM `crisis_classify` подтверждает уровень риска
3. Уровни: `wellbeing` (норма) → `concern` (добавляет referral_hint) → `crisis` (блокирует, подставляет кризисный ответ)
4. При `crisis`: `sales_allowed=False`, горячая линия 8-800-2000-122, NATS событие `mirror.safety.crisis_detected`
5. Все инциденты логируются в `safety_log`

---

## База знаний (RAG)

Qdrant коллекции для семантического поиска:

| Коллекция | Назначение |
|-----------|-----------|
| `knowledge_psych` | Психологические материалы |
| `knowledge_astro` | Астрология: символы, транзиты, толкования |
| `knowledge_tarot` | Таро: 78 карт, расклады, значения |
| `knowledge_dreams` | Сонник |
| `knowledge_numerology` | Нумерология |

Каждый чанк хранится в **двух версиях**: оригинал + перевод (RU↔EN). Определение языка — по доле кириллицы (>20% = RU). Перевод через LLM `intent_classify` task_kind.

Поле `lang` в payload Qdrant (`"ru"` / `"en"`) для будущей фильтрации по языку пользователя.

---

## Celery Workers

Брокер: RabbitMQ. Три модуля задач:

**`tasks/memory.py`**
- `summarize_episode(user_id, session_id)` — LLM резюмирует сессию → `memory_episodes` + `user_episodes` Qdrant
- `extract_facts(user_id, episode_id)` — LLM извлекает факты из эпизода → `memory_facts` + `user_facts` Qdrant

**`tasks/profile.py`**
- `update_psych_profile(user_id)` — LLM анализирует эпизоды + факты → обновляет `user_profiles`

**`tasks/daily_ritual.py`**
- `dispatch_daily_rituals()` — Celery Beat, каждый день 07:00 UTC
- Для каждого пользователя с `daily_ritual_enabled=True`: карта таро дня + астро-аффирмация → отправка в Telegram

---

## NATS Events

Шина событий JetStream, stream `MIRROR`:

| Subject | Издаётся | Подписчик |
|---------|---------|---------|
| `mirror.dialog.session.closed` | adapter.py (новый /start) + dialog.py | memory consumer → Celery |
| `mirror.safety.crisis_detected` | policy/safety.py | (резервирован для алертинга) |

Memory consumer (`events/consumers/memory.py`): подписывается на `mirror.dialog.session.closed`, запускает `summarize_episode` + `extract_facts` задачи.

---

## Admin Panel

Доступен по `/admin/ui/`, защищён JWT токеном.

**Разделы:**
- **Dashboard** — статистика (юзеры, сообщения, ритуалы, интенты по типам)
- **Конфиг** — `app_config` (system prompt, onboarding, crisis_response и т.д.)
- **LLM Routing** — таблица `llm_routing`, смена моделей без деплоя
- **Квоты** — `quota_config` по тарифам
- **Пользователи** — список с TG-метаданными, тарифом, статусом ритуала
- **База знаний** — управление Qdrant коллекциями, загрузка материалов (URL / файл / датасет / ZIP)

ZIP-ингест поддерживает авторазметку по коллекциям: папки вида `knowledge_psych_cbt/` внутри ZIP → автоматически роутятся в соответствующую Qdrant коллекцию (создаётся если нет).

---

## База данных PostgreSQL

**Таблицы:**

| Таблица | Назначение |
|---------|-----------|
| `users` | Глобальные пользователи, timezone, language_code |
| `channel_identities` | TG user_id → global user_id, TG-метаданные |
| `user_profiles` | Психологический профиль (JSONB), daily_ritual_enabled |
| `subscriptions` | Тариф пользователя (free / basic / plus / pro) |
| `memory_episodes` | L2: резюме сессий, qdrant_point_id |
| `memory_facts` | L3: факты о пользователе, qdrant_point_id |
| `llm_providers` | Конфиг провайдеров (OpenAI, Anthropic) |
| `llm_routing` | Роутинг task_kind → model |
| `quota_config` | Лимиты по тарифам |
| `app_config` | key-value конфиг (промпты, шаблоны) |
| `safety_log` | Лог кризисных инцидентов |
| `daily_ritual_log` | Лог отправленных ритуалов |
| `intent_log` | Лог интентов пользователей (аналитика) |

**Миграции:** Alembic, 12 версий (001–012), chain: identity → memory → policy → llm_routing → astrology → daily_ritual → billing → admin_config → persona_prompts → psych_profile → intent_log → tg_metadata

---

## Telegram команды

| Команда | Поведение |
|---------|-----------|
| `/start` | Новая сессия, onboarding LLM ответ |
| `/help` | Статичный текст с описанием возможностей |
| `/quiet` | Отключает проактивные сообщения (`daily_ritual_enabled=false`) |
| `/active` | Включает обратно |
| Любой текст | `handle_message` → DialogService → LangGraph |

---

## Сервисы предметной области

### AstrologyService
- При первом запросе астрологии проверяет наличие данных рождения в `user_profiles`
- Если данных нет — задаёт вопрос про дату/время/город рождения
- Парсит ответ пользователя через LLM, сохраняет в `user_profiles`
- Строит натальную карту (планеты, дома, аспекты) через библиотеку Kerykeion
- Вычисляет текущие транзиты
- RAG: `search_astro_knowledge()` → `knowledge_astro`
- Кэширует натальную карту в Redis на 24ч

### TarotService
- Колода: 78 карт (22 старших + 56 младших аркана) из `tarot_deck.py`
- Типы раскладов: `single` (1 карта), `three_card` (прошлое/настоящее/будущее), `celtic_cross` (10 карт) — определяется из текста запроса
- Каждая карта может лечь перевёрнутой (`is_reversed`)
- RAG: `search_tarot_knowledge()` → `knowledge_tarot` для каждой карты
- LLM интерпретация: `tarot_interpret` task_kind

### DailyRitualService
- Утренний ритуал: карта таро дня + астро-транзит (если есть данные рождения) + аффирмация
- `DailyRitualService.handle()` — по команде пользователя внутри диалога
- `workers/tasks/daily_ritual.py` — Celery Beat 07:00 UTC, рассылка всем с `daily_ritual_enabled=True`
- Лог в `daily_ritual_log`

---

## DB Session — Celery lazy-init

FastAPI lifespan инициализирует `async_session_factory` при старте. Celery workers стартуют отдельно, lifespan не вызывается.

`db/session.py` предоставляет:
- `ensure_db_pool()` — ленивая инициализация, вызывается в начале каждой Celery async-задачи
- `get_session()` — async context manager с автоинициализацией

```python
async def _my_celery_task_async():
    await ensure_db_pool()
    async with get_session() as session:
        ...
```

---

## Admin Auth

Admin UI доступен по `/admin/ui/`. Вход через статичный токен:
- `ADMIN_TOKEN` из `.env` — единый токен доступа
- Хранится в `sessionStorage` браузера после ввода
- Передаётся в заголовке `Authorization: Bearer <token>`
- JWT (`jwt_handler.py`) используется для будущих Web-эндпоинтов Stage 2, не для текущего admin

---

## Конфигурация

Все параметры через `.env` → `mirror/config.py` (Pydantic Settings):

```
DATABASE_URL             PostgreSQL async DSN
REDIS_URL                Redis DSN
QDRANT_URL               Qdrant HTTP URL
NATS_URL                 NATS server URL
RABBITMQ_URL             Celery broker URL
TELEGRAM_BOT_TOKEN       Telegram Bot API token
TELEGRAM_WEBHOOK_SECRET  Секрет для webhook
POLLING_MODE             true = polling (dev), false = webhook (prod)
OPENAI_API_KEY           OpenAI API key
ANTHROPIC_API_KEY        Anthropic API key (для fallback chain)
BASE_URL                 Публичный URL сервера (для webhook)
ADMIN_TOKEN              Токен доступа к Admin Panel
SECRET_KEY               JWT секрет (для будущего Web auth Stage 2)
APP_ENV                  development / production
SENTRY_DSN               Sentry DSN (опционально, для error tracking)
```

**POLLING_MODE:** `true` — бот работает через long polling (удобно для локальной разработки без публичного URL), `false` — webhook (продакшн).

---

## Запуск (dev)

```bash
# Инфраструктура
docker compose -f docker-compose.dev.yml up -d

# Миграции
alembic upgrade head

# Приложение
python -m mirror.main   # или uvicorn mirror.main:app --reload

# Workers
celery -A mirror.workers.celery_app worker -l info
celery -A mirror.workers.celery_app beat -l info
```

**Health checks:**
- `GET /health` → `{"status": "ok"}`
- `GET /ready` → `{"status": "ready"}`
- `GET /metrics` → Prometheus метрики
