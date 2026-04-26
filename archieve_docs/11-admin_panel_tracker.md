# Module 11: Admin Panel — Tracker

**Спека:** `11-admin_panel_spec.md` · **Зависимости:** Все модули 01–10 выполнены

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| AP-01 | Pydantic схемы Admin API (LLMRoutingUpdate, QuotaConfigUpdate, AppConfigUpdate, UserListItem, SafetyLogItem) | `mirror/admin/schemas.py` | `python -m py_compile` |
| AP-02 | `verify_admin` dependency: проверка `X-Admin-Token` заголовка | `mirror/admin/router.py` | Запрос без токена → 401 |
| AP-03 | `GET /admin/health` — статус DB, Redis, Qdrant, NATS | `mirror/admin/router.py` | `curl /admin/health` → JSON со статусами |
| AP-04 | `GET /admin/users` + `GET /admin/users/{user_id}` | `mirror/admin/router.py` | `curl /admin/users` → JSON список |
| AP-05 | `GET /admin/safety-log` (pagination, без текстов) | `mirror/admin/router.py` | Ответ не содержит поля `text` |
| AP-06 | `GET /admin/llm-routing` + `PUT /admin/llm-routing/{task_kind}/{tier}` | `mirror/admin/router.py` | PUT → LLMRouter.call() использует новую модель |
| AP-07 | `GET /admin/quota-config` + `PUT /admin/quota-config/{tier}` | `mirror/admin/router.py` | PUT → BillingService.check_quota() учитывает новый лимит |
| AP-08 | `GET /admin/app-config` + `PUT /admin/app-config/{key}` | `mirror/admin/router.py` | PUT crisis_response → PolicyEngine использует новый шаблон |
| AP-09 | Подключить `admin_router` в `main.py` | `mirror/main.py` | `python -m py_compile` |
| AP-10 | Добавить Appsmith в `docker-compose.dev.yml` (порт 3000) | `docker-compose.dev.yml` | `docker compose up appsmith` → http://localhost:3000 |
| AP-10b | Создать read-only PostgreSQL пользователя `appsmith_ro` (SQL-скрипт) | `mirror/db/scripts/create_appsmith_ro.sql` | `psql -U appsmith_ro mirror -c "SELECT 1"` → OK; `INSERT` → Permission denied |
| AP-11 | Seed `app_config`: `system_prompt_base`, `daily_ritual_enabled`, `maintenance_mode` | `mirror/db/migrations/versions/008_admin_config.py` | `SELECT key FROM app_config` → все 3 ключа |
| AP-12 | Тесты: auth 401, health, llm-routing update, safety-log без ПДн | `tests/admin/test_admin.py` | `pytest tests/admin/ -v` → PASSED |

🛑 **CHECKPOINT:** изменение llm_routing через API применяется немедленно, safety-log не содержит текстов сообщений.
