# Mirror — Admin API Reference

Base path: `/admin`  
Auth: `Authorization: Bearer <token>` где токен = значение `ADMIN_TOKEN` из `.env`

Токен вводится в login-экране Admin UI и хранится в `sessionStorage` браузера.

---

## Stats

### GET /admin/stats
Статистика дашборда.

```json
{
  "total_users": 42,
  "active_today": 7,
  "messages_today": 134,
  "rituals_sent_today": 12,
  "tarot_today": 5,
  "astrology_today": 18,
  "chat_today": 111
}
```
- `messages_today` — из Redis quota-счётчиков
- `active_today` — уникальных пользователей с сообщениями сегодня
- `chat_today` = `messages_today - tarot_today - astrology_today - rituals_sent_today`

---

## App Config

### GET /admin/config
Все ключи из таблицы `app_config`.

### PUT /admin/config/{key}
Обновить значение. Автоматически инвалидирует in-memory кэш app_config в DialogService.

```json
{ "value": "новый текст" }
```

Ключевые ключи:
- `system_prompt_base` — базовый system prompt компаньона
- `onboarding_message` — prompt первого сообщения (/start)
- `crisis_response` — текст при `risk_level=crisis` (обязательно: номер 8-800-2000-122)
- `referral_hint` — подсказка про живого специалиста

---

## LLM Routing

### GET /admin/routing
Вся таблица `llm_routing`.

### PUT /admin/routing/{task_kind}
Обновить роутинг для task_kind. Инвалидирует кэш LLMRouter.

```json
{
  "provider_id": "openai",
  "model_id": "gpt-4o",
  "fallback_chain": [{"provider_id": "openai", "model_id": "gpt-4o-mini"}],
  "max_tokens": 1024,
  "temperature": 0.7
}
```

### GET /admin/llm-keys
Список провайдеров и замаскированные API ключи.

### PUT /admin/llm-keys/{provider}
Обновить API ключ провайдера (`openai` / `anthropic`).

```json
{ "api_key": "sk-..." }
```

### GET /admin/llm-models
Получить список доступных моделей OpenAI (вызывает OpenAI API, используется в UI при выборе модели).

---

## Quota Config

### GET /admin/quota
Все тарифы из `quota_config`.

### PUT /admin/quota/{tier}
Обновить лимиты тарифа. Инвалидирует кэш BillingService.

```json
{
  "daily_messages": 50,
  "tarot_per_day": 5,
  "astrology_per_day": 5
}
```

---

## Users

### GET /admin/users?limit=50&offset=0
Список пользователей с TG-метаданными (JOIN channel_identities).

```json
[{
  "user_id": "uuid",
  "full_name": "Имя Фамилия",
  "tg_username": "username",
  "is_premium": false,
  "tier": "free",
  "daily_ritual_enabled": true,
  "created_at": "2026-04-22T10:00:00"
}]
```

### PUT /admin/users/{user_id}/ritual?enabled=true
Включить или выключить ежедневный ритуал для конкретного пользователя.

---

## Knowledge Base

### GET /admin/kb/collections
Список Qdrant коллекций с метриками (status, count, segments).

```json
[{"name": "knowledge_psych", "count": 1420, "status": "green", "segments": 2}]
```

### POST /admin/kb/collections
Создать новую коллекцию (vectors size=3072, distance=Cosine).

```json
{ "name": "knowledge_psych_cbt", "description": "КПТ техники и протоколы" }
```

### DELETE /admin/kb/collections/{collection}?confirm=yes
Удалить коллекцию со всеми данными. Требует `confirm=yes`.

### GET /admin/kb/stats
Список коллекций с количеством точек (упрощённый, без деталей статуса).

### GET /admin/kb/entries/{collection}?limit=20&offset=0
Просмотр записей коллекции (topic + text preview).

### POST /admin/kb/add
Добавить одну запись вручную.

```json
{
  "collection": "knowledge_psych",
  "topic": "КПТ — когнитивное искажение",
  "text": "текст записи"
}
```

### DELETE /admin/kb/entry/{collection}/{point_id}
Удалить одну точку из коллекции.

### GET /admin/kb/hf-search?query=psychology+therapy&limit=10
Поиск датасетов на HuggingFace Hub по ключевым словам.

### GET /admin/kb/hf-splits/{repo_owner}/{repo_name}
Получить список splits и preview полей датасета с HuggingFace.

### POST /admin/kb/ingest-url
Загрузить и нарезать контент с URL (HTML, текст).

```json
{
  "collection": "knowledge_psych",
  "url": "https://example.com/article",
  "topic": "КПТ тревога",
  "source_lang": "auto"
}
```

### POST /admin/kb/ingest-file
Загрузить файл (multipart/form-data).

Форматы: `.txt`, `.md`, `.epub`, `.fb2`, `.pdf`, `.zip`, `.docx`  
Параметры: `collection`, `topic`, `source_lang`, `file`

ZIP-архив: папки вида `knowledge_*/` → авторутинг в соответствующую коллекцию (создаётся автоматически).

### POST /admin/kb/ingest-dataset
Загрузить датасет (JSON/JSONL/CSV по URL или с HuggingFace).

```json
{
  "collection": "knowledge_psych",
  "dataset_url": "https://raw.githubusercontent.com/.../dataset.jsonl",
  "question_field": "input",
  "answer_field": "output",
  "topic_prefix": "психология",
  "source_lang": "auto",
  "limit": 0
}
```
`limit: 0` = загрузить все записи.

---

## System

### GET /health
`{"status": "ok"}` — liveness probe

### GET /ready
`{"status": "ready"}` — readiness probe

### GET /metrics
Prometheus метрики (HTTP latency, request count, status codes)
