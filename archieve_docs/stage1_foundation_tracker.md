# Stage 1 Foundation — Tracker

**Ссылка на спеку:** `stage1_foundation_spec.md`  
**Статус:** ожидает подтверждения  

Правила выполнения: один шаг → верификация → следующий. СТОП на каждом чекпоинте 🛑.

---

## Epic 1: Инициализация проекта

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| F-01 | Создать структуру папок и `__init__.py` во всех модулях | `mirror/**/__init__.py`, `tests/__init__.py` | `find mirror -name "*.py" \| sort` |
| F-02 | Создать `pyproject.toml` (Poetry) со всеми зависимостями | `pyproject.toml` | `poetry install --no-root` → без ошибок |
| F-03 | Создать `.env.example` и `.env` (локальные значения) | `.env.example`, `.env` | Визуальная проверка всех ключей |
| F-04 | Создать `.gitignore` | `.gitignore` | Проверить что `.env` исключён |

🛑 **CHECKPOINT 1:** структура создана, зависимости установлены. Подтверждение перед Epic 2.

---

## Epic 2: Конфигурация и логирование

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| F-05 | Создать `mirror/config.py` (Pydantic Settings) | `mirror/config.py` | `python -c "from mirror.config import settings; print(settings.app_env)"` |
| F-06 | Создать `mirror/logging_setup.py` (structlog JSON) | `mirror/logging_setup.py` | Импорт без ошибок |
| F-07 | Создать `mirror/main.py` — FastAPI skeleton + lifespan + `/health` | `mirror/main.py` | `python -m py_compile mirror/main.py` |

🛑 **CHECKPOINT 2:** приложение запускается. `python -m mirror.main` → FastAPI стартует на :8000.

---

## Epic 3: Docker-compose инфраструктура

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| F-08 | Создать `docker-compose.dev.yml` (все 6 сервисов) | `docker-compose.dev.yml` | `docker compose -f docker-compose.dev.yml config` — валидный YAML |
| F-09 | Поднять инфраструктуру и проверить все сервисы | — | `docker compose -f docker-compose.dev.yml up -d` → все `running` |
| F-10 | Проверить доступность каждого сервиса | — | PostgreSQL: `psql $DATABASE_URL -c "SELECT 1"` / Qdrant: `curl http://localhost:6333/collections` / Redis: `redis-cli ping` / NATS: `curl http://localhost:8222/healthz` / RabbitMQ: `curl -u guest:guest http://localhost:15672/api/overview` / Appsmith: `curl http://localhost:3000` |

🛑 **CHECKPOINT 3:** вся инфраструктура поднята. Подтверждение перед Epic 4.

---

## Epic 4: Database setup

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| F-11 | Создать `mirror/db/session.py` — async SQLAlchemy engine + session factory | `mirror/db/session.py` | `python -c "from mirror.db.session import async_session_factory; print('OK')"` |
| F-12 | Инициализировать Alembic | `alembic.ini`, `mirror/db/migrations/env.py` | `alembic current` → без ошибок |

---

## Epic 5: Workers и Events заглушки

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| F-13 | Создать `mirror/workers/celery_app.py` — Celery с RabbitMQ broker | `mirror/workers/celery_app.py` | `python -c "from mirror.workers.celery_app import celery_app; print(celery_app.conf.broker_url)"` |
| F-14 | Создать `mirror/events/nats_client.py` — NATSClient класс с интерфейсом (connect, publish, subscribe, close) | `mirror/events/nats_client.py` | `python -m py_compile` |
| F-14b | Создать `mirror/dependencies.py` — singleton-инстансы всех сервисов (пустые заглушки с правильными именами) | `mirror/dependencies.py` | `from mirror.dependencies import llm_router` → OK |

---

## Epic 6: Тесты и финальная проверка

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| F-15 | Создать `tests/conftest.py` — engine, db_session, client фикстуры + тестовая БД `mirror_test` | `tests/conftest.py` | `createdb mirror_test` → `pytest --co` без ошибок |
| F-16 | Создать `tests/test_health.py` — тест GET /health | `tests/test_health.py` | `pytest tests/test_health.py -v` → PASSED |
| F-17 | Финальная проверка всех Acceptance Criteria из спеки | — | Пройтись по чеклисту в `stage1_foundation_spec.md` |

🛑 **CHECKPOINT FINAL:** все тесты зелёные, все сервисы запущены. Готово к разработке модуля 01 (Identity).

---

## Прогресс

| Epic | Статус |
|------|--------|
| Epic 1: Инициализация | ⏳ ожидает |
| Epic 2: Config + Logging | ⏳ ожидает |
| Epic 3: Docker-compose | ⏳ ожидает |
| Epic 4: Database | ⏳ ожидает |
| Epic 5: Workers + Events | ⏳ ожидает |
| Epic 6: Тесты | ⏳ ожидает |
