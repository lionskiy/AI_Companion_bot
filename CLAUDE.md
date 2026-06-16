# Mirror — AI Companion Bot

## Проект

Персонализированный AI-компаньон для самопознания через Telegram. Интегрирует астрологию, таро и психологию. Кодовое название: **Mirror**.

**Статус:** Этап 1 в разработке — Telegram + astrology/tarot/daily_ritual + Free-биллинг.  
**Источник истины:** `dev_spec/Mirror_POD_v2.md` — при конфликте POD приоритетнее всего.

---

## Технологический стек

- **Язык:** Python, async/await везде (FastAPI, aiogram, SQLAlchemy 2 async)
- **Telegram:** aiogram, webhook (не long polling)
- **БД:** PostgreSQL OLTP + Qdrant (векторы) + Redis (кэш/сессии)
- **Очереди:** NATS JetStream (события) + Celery+RabbitMQ (задачи)
- **Оркестрация диалога:** LangGraph
- **RAG:** Haystack
- **Auth:** PyJWT (Этап 1, Telegram only); Keycloak добавляется на Этапе 2 при появлении Web/App
- **Admin UI:** Appsmith (self-hosted, open-source) — подключается к PostgreSQL напрямую + к FastAPI Admin REST API; входит в `docker-compose.dev.yml`
- **Timezone:** берётся из Telegram metadata (`from_user`), хранится в `user_profiles.timezone`; fallback: `Europe/Moscow`
- **Логирование:** structlog/loguru, JSON format

---

## Hard Constraints (нарушение = стоп)

### Хранилища
- **Qdrant** = ВСЕ dense-эмбеддинги для семантического поиска (KB, mem_L2, mem_L3)
- **pgvector ЗАПРЕЩЁН** для retrieval — только через Qdrant
- **PostgreSQL** = OLTP, source of truth для текстов, метаданных, `qdrant_point_id`
- **Redis** = кэш, сессии, rate limit, mem_L1 — НЕ event store

### Шина событий
- **NATS JetStream** = персистентная шина событий (replay, fan-out)
- **Celery+RabbitMQ** = исполнитель задач Python
- Redis Streams как шина — запрещено

### LLM
- Каждый вызов LLM обязан иметь `task_kind`
- Роутинг берётся из БД (`llm_routing`), не хардкодится
- Retry: 3 попытки → fallback chain → «технические работы» пользователю
- Тариф/лимиты — только из БД после аутентификации, не из текста LLM

### Безопасность
- `user_id` — ТОЛЬКО из верифицированного JWT токена, никогда из тела запроса
- Prompt injection защита: пользовательский ввод не в system prompt напрямую
- Логи без ПДн: хэши и классы, не сырые тексты и имена
- RLS обязателен: `memory_episodes`, `memory_facts`, `user_companion_persona`, `journal_entries`

### Policy §3.8 (кризисный протокол — ОБЯЗАТЕЛЕН)
- `crisis_classify` на каждое сообщение, лучшая модель
- При `risk_level = crisis`: тёплый ответ + горячая линия **8-800-2000-122**, `sales_allowed = False`
- Запрещено использовать сигналы уязвимости как триггер продаж

---

## Нейминг (обязателен в коде, БД, событиях)

```
Память:
  mem_L0 — Context Window (промпт, RAM)
  mem_L1 — Session Cache (Redis, 48ч TTL)
  mem_L2 — Episode Memory (PostgreSQL + Qdrant)
  mem_L3 — Semantic Memory / Facts (PostgreSQL + Qdrant)

Верификация возраста:
  age_L0 — кнопка «Мне 18+»
  age_L1 — банковская карта
  age_L2 — Госуслуги (ЕСИА)
  age_L3 — VK ID / Сбер ID
  age_L4 — KYC-документ
```

---

## Доменная модель (модульный монолит)

```
Auth, Identity, Consent, Dialog, Memory, Profile, ProfileEnrich,
Policy, Persona, Journey, Billing, Proactive, GameEngine, Analytics, Admin
```

Границы строгие — модуль не вызывает внутренности другого напрямую.

---

## Архитектура каналов

```
Telegram (aiogram) → ChannelAdapter → UnifiedMessage → DialogService → UnifiedResponse → ChannelAdapter → Telegram
```

- Бизнес-логика НЕ импортирует ничего из aiogram
- Handler содержит только нормализацию, никакой бизнес-логики

---

## Этап 1 — что реализуется / что НЕТ

**Реализуется:**
- Telegram + aiogram (webhook)
- Режимы: `astrology`, `tarot`, `daily_ritual`
- Память mem_L0–L3 (PostgreSQL + Qdrant)
- Policy & кризисный протокол
- Free-биллинг (лимит N/день из БД, без приёма оплаты)
- Базовая админка

**НЕ реализуется на этапе 1:**
- Adult Mode, аддоны
- Публичный приём оплаты
- Web, VK, WhatsApp, Mobile
- Proactive messaging как продукт
- Сонник, нумерология, психология
- Keycloak (добавить на Этапе 2 с Web)

---

## Ветки (обязательно соблюдать)

| Ветка | Назначение |
|---|---|
| `main` | Последняя стабильная (релизная) версия. Только merge из `new_features`. |
| `new_features` | Вся разработка: правки, фичи, эксперименты. |

**Правило старта:** В начале каждой сессии/задачи — проверить текущую ветку.
- Если не `new_features` → `git checkout new_features` (или `git checkout -b new_features origin/main` если ветки нет).
- Никогда не коммитить напрямую в `main`.

### ЖЁСТКИЕ ЗАПРЕТЫ — нарушение недопустимо

> ⛔ **Самодеятельность в git и деплое ЗАПРЕЩЕНА.** Без явной команды пользователя нельзя:
> - делать `git push` в любую ветку (в том числе `new_features`)
> - делать `git merge` или переключать ветки
> - запускать деплой на стейдж или прод
> - перезапускать контейнеры на любом сервере

**Правила без исключений:**
1. Вся разработка ведётся только локально, в ветке `new_features`.
2. Проверка изменений — только на локальном стейдже (`./scripts/stage.sh`), и только по команде.
3. `git push origin new_features` — только по явной команде "закоммить" / "залей в new_features".
4. Merge `new_features` → `main` и деплой на прод — только по явной команде "деплой на прод" / "деплой на бой".
5. После завершения любой задачи — спросить: "Закоммитить изменения?", но не коммитить самостоятельно.

---

## CI/CD — команды деплоя

### "деплой на стейдж" / "задеплой локально"
Пересобрать и перезапустить локальный Docker для проверки:
```bash
./scripts/stage.sh
```
- Запускает `docker compose -f docker-compose.dev.yml up -d --build`
- Прогоняет `alembic upgrade head`
- **НЕ коммитит автоматически** — после выполнения спросить: "Закоммитить текущие изменения в `new_features`?"

### "комит в новые фичи" / "закоммить" / "залей в new_features"
Сохранить текущие изменения в ветку `new_features`:
```bash
git add <изменённые файлы>
git commit -m "..."
git push origin new_features
```

### "деплой на прод" / "деплой на бой" / "лей на прод"
Слить `new_features` в `main` и задеплоить на сервер:
```bash
./scripts/deploy_prod.sh
```
Скрипт делает:
1. Проверяет что мы в `new_features` и нет незакоммиченных изменений
2. `git merge new_features → main` + `git push origin main`
3. SSH на сервер: `git pull` + `docker compose -f docker-compose.prod.yml up -d --build` + миграции

### Сервер
```
Хост: YOUR_SERVER_IP (заполнить в scripts/deploy_prod.sh)
Пользователь: YOUR_SSH_USER
Путь: /opt/mirror
Порт prod: 8000 (за Nginx, снаружи 443)
```
- `.env.prod` хранится только на сервере, никогда не коммитится
- Первый деплой на сервер: запустить `./scripts/ssl_init.sh email domain` для SSL

---

## Структура папок документации

| Папка | Назначение |
|---|---|
| `dev_spec/` | Технические задания (ТЗ) на разработку новых фич. Здесь живут спеки пока фича в работе. |
| `archieve_docs/` | Архив выполненных ТЗ. ТЗ перемещается сюда только после завершения разработки, прохождения тестирования и подтверждения что фича принята. |
| `docs/` | Проектная документация: описание как реализовано приложение, архитектурные решения, runbook-и, API-описания. Формируется по итогу выполненных задач. |

**Правила:**
- Новое ТЗ → создавать в `dev_spec/<feature>_spec.md` + `dev_spec/<feature>_tracker.md`
- После принятия фичи → переместить ТЗ из `dev_spec/` в `archieve_docs/`
- По итогу реализации → обновить/создать соответствующий документ в `docs/`
- `dev_spec/Mirror_POD_v2.md` — главный документ продукта, не архивируется

---

## Workflow для нетривиальных задач

1. Контекст — изучить файлы, grep, git blame
2. Анализ — декомпозиция, edge cases, Acceptance Criteria
3. Дизайн — минимальные изменения, контракты, план отката
4. Ревью — идемпотентность, гонки, деградация
5. Реализация — код + тест + smoke-check
6. Документация — обновить docs

**Если есть готовая спека в `dev_spec/` — переходить сразу к шагу 4.**

---

## Definition of Done

- Acceptance Criteria выполнены
- Логирование: structlog/loguru, JSON, без ПДн
- Timeout на все внешние вызовы (LLM, Qdrant, NATS, Redis)
- Минимум 1–2 теста или smoke-чеклист
- Policy-контур §3.8 не обходится
- Документация обновлена

---

## Файлы которые НЕЛЬЗЯ менять без явного указания

- `core/llm/router.py` — LLM Router
- `core/policy/safety.py` — Policy & Safety (кризисный протокол)
- `core/memory/service.py` — Memory Service API
- `core/identity/service.py` — Identity
- `channels/*/adapter.py` — нормализаторы каналов
- Файлы миграций Alembic (только создавать новые)

---

## Qdrant коллекции (канонические имена)

```python
"knowledge_tarot", "knowledge_astro", "knowledge_psych",
"knowledge_dreams", "knowledge_numerology",
"user_episodes",  # mem_L2
"user_facts",     # mem_L3
```

---

## task_kind (канонические значения)

```python
"main_chat", "main_chat_premium", "intent_classify", "crisis_classify",
"memory_summarize", "memory_extract_facts", "tarot_interpret",
"astro_interpret", "game_narration", "proactive_compose",
"persona_evolve", "embedding"
```
