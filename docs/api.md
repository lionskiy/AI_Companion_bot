# Mirror — Admin API Reference

Base path: `/admin`  
Auth: `Authorization: Bearer <JWT>` (токен из `ADMIN_SECRET_KEY`)

---

## Stats

### GET /admin/stats
Статистика дашборда.

**Response:**
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
`chat_today` = `messages_today - tarot_today - astrology_today - rituals_sent_today`

---

## App Config

### GET /admin/config
Все ключи из таблицы `app_config`.

### PUT /admin/config/{key}
Обновить значение ключа.

```json
{ "value": "новый текст" }
```

Ключевые ключи:
- `system_prompt_base` — базовый system prompt
- `onboarding_message` — prompt первого сообщения
- `crisis_response` — текст при `risk_level=crisis`
- `referral_hint` — подсказка про специалиста

---

## LLM Routing

### GET /admin/llm-routing
Вся таблица `llm_routing`.

### PUT /admin/llm-routing/{task_kind}/{tier}
Обновить роутинг для конкретного task_kind + tier.

```json
{
  "provider_id": "openai",
  "model_id": "gpt-4o",
  "fallback_chain": [{"provider_id": "openai", "model_id": "gpt-4o-mini"}],
  "max_tokens": 1024,
  "temperature": 0.7
}
```

---

## Quota Config

### GET /admin/quota
Все тарифы из `quota_config`.

### PUT /admin/quota/{tier}
Обновить лимиты тарифа.

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
Список пользователей с TG-метаданными.

```json
[{
  "user_id": "uuid",
  "username": "Имя Фамилия",
  "full_name": "Имя Фамилия",
  "tg_username": "username",
  "is_premium": false,
  "tier": "free",
  "daily_ritual_enabled": true,
  "created_at": "2026-04-22T10:00:00"
}]
```

---

## Knowledge Base

### GET /admin/kb/collections
Список Qdrant коллекций с метриками.

```json
[{
  "name": "knowledge_psych",
  "count": 1420,
  "status": "green",
  "segments": 2
}]
```

### POST /admin/kb/collections
Создать новую коллекцию.

```json
{ "name": "knowledge_psych_cbt", "description": "КПТ техники и протоколы" }
```

### GET /admin/kb/entries?collection=knowledge_psych&limit=20
Просмотр записей в коллекции.

### DELETE /admin/kb/entries/{point_id}?collection=knowledge_psych
Удалить точку из коллекции.

### POST /admin/kb/ingest-url
Загрузить контент с URL.

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

Поддерживаемые форматы: `.txt`, `.md`, `.epub`, `.fb2`, `.pdf`, `.zip`, `.docx`  
Параметры формы: `collection`, `topic`, `source_lang`, `file`

ZIP-архив: если содержит папки с именами вида `knowledge_*` — файлы автоматически роутятся в соответствующие коллекции.

### POST /admin/kb/ingest-dataset
Загрузить датасет (JSON/JSONL/CSV по URL).

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

---

## System

### POST /admin/cache/invalidate
Сбросить кэш LLM роутинга и app_config.

### GET /health
`{"status": "ok"}` — liveness probe

### GET /ready
`{"status": "ready"}` — readiness probe

### GET /metrics
Prometheus метрики (latency, request count и т.д.)
