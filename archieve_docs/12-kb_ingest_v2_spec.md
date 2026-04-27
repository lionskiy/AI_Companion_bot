# 12 — KB Ingest v2: Рефакторинг пайплайна загрузки Базы знаний

**Версия:** 1.2  
**Статус:** Готово к реализации  
**Приоритет:** Высокий  

**Changelog v1.2:**
- Исправлено: тип job_id/file_id в новых таблицах — TEXT (совместимость с ingest_jobs.id TEXT)
- Исправлено: дублирующийся сломанный `acquire` метод удалён — оставлена только правильная версия
- Добавлено: `enrichment_done` — точка обновления явно указана в flow Stage 3
- Исправлено: `_enrich_metadata_batch` теперь внутренне использует `_ENRICH_SEM`
- Добавлено: инициализация `_RATE_LIMITER` и `EMBED_SEM` после tier probe в pipeline.py
- Добавлено: JOIN с ingest_files при загрузке чанков для embed (получение doc_context)
- Добавлено: параметры chunker (max_chars=900, overlap=100) — соответствуют текущей реализации
- Исправлено: `asyncio.get_running_loop()` вместо неопределённого `loop`
- Добавлено: enrichment failure handling (skip → keywords=None, log warning)
- Добавлено: _ENRICH_SEM — ленивая инициализация (не на уровне модуля)

**Changelog v1.1:**
- Убраны противоречия: enrichment всегда включён в pipeline, флаги управляют типами (не мастер-выключателем)
- Исправлено: `/tmp` → `/data/ingest/` (Docker volume, не ephemeral tmpfs)
- Исправлено: ProcessPoolExecutor → ThreadPoolExecutor (chunking — не CPU-bound)
- Исправлено: Token Bucket vs Semaphore — унифицировано в Section 9
- Исправлено: token estimate 200 → 500 токенов/чанк (с contextual prefix)
- Исправлено: Tier таблица — реальные лимиты OpenAI
- Добавлено: `qdrant_upserted` и `tier` колонки в ingest_jobs
- Добавлено: составной индекс (job_id, chunk_status)
- Добавлено: contextual_prefix убран из ingest_chunks (хранится только в ingest_files.document_context)
- Добавлено: raw_text хранится на диске, не в PostgreSQL
- Добавлено: задачи для task_kind routing (kb_enrich_context, kb_enrich_metadata)
- Добавлено: flow для одиночного файла (не ZIP)
- Добавлено: lock вокруг tier probe (race condition)
- Добавлено: retry flow для v2 джобов
- Добавлено: enrichment rate limiter
- Добавлено: app_config seed миграция
- Добавлено: lang detection (langdetect)
- Добавлено: stale job reset Celery task
- Добавлено: deduplication policy
- Добавлено: partial resume механизм

---

## 1. Цели и мотивация

### 1.1 Проблемы текущей реализации

| Проблема | Описание |
|---|---|
| Перевод (bilingual) | На каждый чанк делается LLM-вызов для перевода RU↔EN. При 1792 чанках — 60+ LLM-вызовов только на перевод. Дорого, медленно, rate-limit. |
| Файл хранится в БД | `ingest_jobs.file_data` хранит BYTEA — вся книга в PostgreSQL. Раздувает БД, медленно. |
| Нет staging для чанков | Чанки нигде не сохраняются до эмбеддинга — нельзя показать прогресс по этапам, нельзя возобновить с места остановки. |
| Семафор вместо rate-limiter | Concurrency-семафор не контролирует RPM/TPM точно — при быстрых вызовах превышаем лимиты. |
| Один прогресс-бар | UI показывает только chunks_done/total — нет разбивки по этапам. |
| Нет enrichment | Эмбеддинг делается по «голому» тексту — качество retrieval ниже возможного. |
| Нет очистки временных данных | После завершения файл остаётся в `ingest_jobs.file_data`. |

### 1.2 Цели рефакторинга

1. **Убрать перевод полностью** — хранить только оригинальный язык (экономия ~60% токенов на инджест).
2. **Staging-таблицы** — файлы и чанки живут в отдельных таблицах, дают прогресс по этапам.
3. **Tier-aware embedding** — автоопределение тира по ключу, адаптивный batch_size и max_concurrent.
4. **Параллелизм на каждом этапе** — extract, chunk, embed идут параллельно в пределах лимитов.
5. **Semantic enrichment всегда включён** — contextual prefix + payload metadata улучшают качество retrieval; флаги управляют типами обогащения, не включают/выключают целиком.
6. **Очистка** — временные файлы и staging-строки удаляются после завершения.
7. **5 прогресс-баров** в Admin UI по этапам.
8. **Ротация логов** — ingest-логи чистятся через 7 дней.

---

## 2. Архитектура пайплайна

### 2.1 Этапы (stages)

```
┌─────────────────────────────────────────────────────────────┐
│                     INGEST PIPELINE v2                      │
├──────────┬──────────┬─────────┬──────────┬──────────────────┤
│ Stage 1  │ Stage 2  │ Stage 3 │ Stage 4  │ Stage 5          │
│ UPLOAD   │ EXTRACT  │ CHUNK   │ EMBED    │ CLEANUP          │
├──────────┴──────────┴─────────┴──────────┴──────────────────┤
│                                                             │
│  ZIP/file         ┌─ file_1 ─►  chunks ─► [enrich] ─► emb ─┐│
│  uploaded    ──►  ├─ file_2 ─►  chunks ─► [enrich] ─► emb  ││
│  to /data/        └─ file_N ─►  chunks ─► [enrich] ─► emb ─┘│
│  ingest/                                         │          │
│  {job_id}/                               Qdrant upsert      │
│                                                  │          │
│                                          cleanup temp        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Детальный flow — ZIP

```
STAGE 1: UPLOAD
  ├── Получить файл от клиента
  ├── Проверить размер: <= kb_max_zip_size_mb (default 500MB)
  ├── Сохранить на диск: /data/ingest/{job_id}/original.zip
  ├── Записать ingest_jobs (status='queued', stage='upload', tmp_path='/data/ingest/{job_id}')
  └── Поставить job_id в asyncio.Queue

STAGE 2: EXTRACT (параллельно по файлам)
  ├── Открыть ZIP → список файлов (пропустить __MACOSX, .DS_Store)
  ├── UPDATE ingest_jobs (stage='extract', files_total=N)
  ├── asyncio.gather(*[extract_file(f) for f in files], return_exceptions=True)
  │     ├── loop.run_in_executor(thread_pool, _extract_text_sync, file_bytes, ext)
  │     │     ├── PDF: pypdf.PdfReader → extract pages
  │     │     ├── EPUB: ebooklib → html → BeautifulSoup → text
  │     │     └── TXT/MD: decode utf-8
  │     ├── Определить язык: langdetect.detect(text[:2000]) → source_lang
  │     ├── Записать текст на диск: /data/ingest/{job_id}/texts/{file_id}.txt
  │     ├── INSERT INTO ingest_files (job_id, filename, collection, topic, source_lang,
  │     │     text_path, char_count, file_status='extracted')
  │     └── При ошибке: INSERT ingest_files(file_status='error', error=str(exc)) — продолжить
  └── UPDATE ingest_jobs (files_extracted=N_ok, stage='chunk')

STAGE 3: CHUNK + ENRICH (параллельно по файлам)
  ├── asyncio.gather(*[chunk_and_enrich_file(f) for f in ingest_files WHERE status='extracted'])
  │     ├── Прочитать текст: open(ingest_files.text_path)
  │     ├── UPDATE ingest_files (file_status='chunking')
  │     ├── _chunk_text(raw_text) → chunks[]  (TextSplitter)
  │     ├── ENRICH (contextual prefix):
  │     │     ├── Если kb_enrichment_context=true:
  │     │     │     ├── async with _ENRICH_SEM: llm_router.call("kb_enrich_context", ...)
  │     │     │     └── UPDATE ingest_files (document_context=...)
  │     │     │     └── При ошибке: log warning, document_context = None (не abort)
  │     │     └── Если false: document_context = None
  │     ├── ENRICH (payload metadata):
  │     │     ├── Если kb_enrichment_metadata=true:
  │     │     │     ├── Батчи по 50 чанков:
  │     │     │     │     ├── async with _ENRICH_SEM: llm_router.call("kb_enrich_metadata", ...)
  │     │     │     │     ├── При ошибке: log warning, keywords=None для этого батча (не abort)
  │     │     │     │     └── UPDATE ingest_jobs SET enrichment_done += len(batch)
  │     │     └── Если false: keywords=None, category=None
  │     ├── INSERT INTO ingest_chunks (batch) — без contextual_prefix (хранится в ingest_files)
  │     └── UPDATE ingest_files (file_status='chunked', chunk_count=len(chunks))
  ├── SELECT COUNT(*) FROM ingest_chunks WHERE job_id → total
  └── UPDATE ingest_jobs (chunks_total=total, files_chunked=N_ok,
        enrichment_total=total, stage='embed')

  ВАЖНО: enrichment_done обновляется после каждого metadata батча (50 чанков), а НЕ в конце.
  При kb_enrichment_metadata=false — enrichment_done остаётся 0, enrichment_total=0.

STAGE 4: EMBED (параллельно батчами, tier-aware)
  ├── Получить/обновить tier: tier = await _get_embedding_tier() [с lock на probe]
  ├── Создать rate limiter: rate_limiter = EmbeddingRateLimiter(tier.tpm, tier.rpm)  [локальная переменная]
  ├── Создать semaphore: embed_sem = asyncio.Semaphore(tier.max_concurrent)           [локальная переменная]
  ├── UPDATE ingest_jobs (tier=tier.name)
  ├── SELECT ic.*, inf.document_context
  │     FROM ingest_chunks ic JOIN ingest_files inf ON ic.file_id = inf.id
  │     WHERE ic.job_id=? AND ic.chunk_status='pending'
  │     ORDER BY ic.chunk_index
  │     — resume-friendly: 'done' чанки пропускаются автоматически
  ├── Разбить на батчи по tier.batch_size
  ├── asyncio.gather(*[embed_batch(b, embed_sem, rate_limiter) for b in batches], return_exceptions=True)
  │     ├── Склеить текст каждого чанка: f"{doc_context}\n---\n{chunk_text}" если doc_context != None
  │     │     иначе: chunk_text  (doc_context уже есть в объекте чанка из JOIN выше)
  │     ├── tokens_est = len(batch) * 500
  │     ├── await rate_limiter.acquire(tokens_est)   [локальная переменная из Stage 4 начала]
  │     ├── async with embed_sem:
  │     ├── UPDATE ingest_chunks SET chunk_status='embedding' WHERE id IN batch_ids
  │     ├── openai.embeddings.create(model=tier.model, input=texts)
  │     ├── qdrant.upsert(collection, points=[PointStruct(vector, payload)])
  │     │     payload = {topic, text, collection, lang, keywords, category,
  │     │                file_id, has_context, source_lang}
  │     ├── UPDATE ingest_chunks SET chunk_status='done', qdrant_point_id=... WHERE id IN (...)
  │     └── UPDATE ingest_jobs SET chunks_done+=n, qdrant_upserted+=n
  └── UPDATE ingest_jobs (stage='cleanup')

STAGE 5: CLEANUP
  ├── shutil.rmtree(/data/ingest/{job_id}/) — удалить все файлы на диске
  ├── DELETE FROM ingest_chunks WHERE job_id  [staging — не нужны после успеха]
  ├── UPDATE ingest_files SET text_path=NULL, char_count сохраняем (метаданные)
  └── UPDATE ingest_jobs SET status='done', stage='done', chunks_added=total,
        file_data=NULL, tmp_path=NULL
```

### 2.3 Детальный flow — одиночный файл (не ZIP)

```
STAGE 1: UPLOAD
  ├── Сохранить файл: /data/ingest/{job_id}/original.{ext}
  ├── Создать ingest_jobs (job_type='file', ...)
  └── Поставить в queue

STAGE 2: EXTRACT (один файл)
  ├── UPDATE ingest_jobs (files_total=1, stage='extract')
  ├── _extract_text_sync(file_bytes, ext)
  ├── Записать /data/ingest/{job_id}/texts/{file_id}.txt
  ├── INSERT ingest_files ...
  └── UPDATE ingest_jobs (files_extracted=1)

STAGE 3-5: аналогично ZIP, но files_total=1
```

### 2.4 Flow для retry

```
Пользователь нажимает Retry:
  ├── Если ingest_jobs.tmp_path EXISTS на диске:
  │     └── Сбросить статус → 'queued', stage='extract', поставить в queue
  │         Staging-строки (ingest_files, ingest_chunks) — DELETE перед перезапуском
  └── Если tmp_path НЕ существует (очищено):
        └── Вернуть 409 с сообщением: "Файл удалён. Загрузите снова."
            Не пытаться перезапустить — файла нет.

Для 'done' джобов: retry запрещён (409 "Уже завершён").
```

---

## 3. Схема базы данных

### 3.1 Новая таблица: `ingest_files`

```sql
-- ВАЖНО: ingest_jobs.id — TEXT (см. миграцию 013). Новые таблицы используют TEXT для совместимости.
-- gen_random_uuid() возвращает TEXT-представление UUID (работает с pgcrypto/uuid-ossp).
CREATE TABLE ingest_files (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    job_id          TEXT NOT NULL REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    collection      TEXT NOT NULL,
    topic           TEXT NOT NULL DEFAULT '',
    source_lang     TEXT NOT NULL DEFAULT 'auto',   -- определяется langdetect после extract
    -- Content (cleared after cleanup — хранится на диске, не в PG)
    text_path       TEXT,                           -- /data/ingest/{job_id}/texts/{id}.txt
    char_count      INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    -- Document-level enrichment (один на файл, не на чанк)
    document_context TEXT,     -- LLM-generated: 2-3 предложения о документе
    -- Status
    file_status     TEXT NOT NULL DEFAULT 'pending',
                    -- pending / extracting / extracted / chunking / chunked / error
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ingest_files_job_id_idx ON ingest_files(job_id);
CREATE INDEX ingest_files_status_idx ON ingest_files(file_status);
```

**Важно:** `raw_text` НЕ хранится в PostgreSQL — хранится в файле `text_path` на диске.
Это позволяет избежать раздувания PG при больших документах (книга = 200k символов = ~200KB).

### 3.2 Новая таблица: `ingest_chunks`

```sql
CREATE TABLE ingest_chunks (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    job_id          TEXT NOT NULL REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    file_id         TEXT NOT NULL REFERENCES ingest_files(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    -- Content
    text            TEXT NOT NULL,
    -- Metadata payload (stored in Qdrant)
    keywords        TEXT,           -- comma-separated, из enricher
    category        TEXT,           -- LLM-classified category, из enricher
    -- Status
    chunk_status    TEXT NOT NULL DEFAULT 'pending',
                    -- pending / embedding / done / error
    qdrant_point_id TEXT,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- contextual_prefix НЕ хранится в ingest_chunks — он одинаков для всех чанков файла.
-- Во время embed читается ingest_files.document_context и препендится к тексту.

CREATE INDEX ingest_chunks_job_id_idx    ON ingest_chunks(job_id);
CREATE INDEX ingest_chunks_file_id_idx   ON ingest_chunks(file_id);
CREATE INDEX ingest_chunks_status_idx    ON ingest_chunks(chunk_status);
CREATE INDEX ingest_chunks_job_status_idx ON ingest_chunks(job_id, chunk_status);  -- для resume query
```

### 3.3 Изменения в `ingest_jobs`

```sql
ALTER TABLE ingest_jobs
    ADD COLUMN stage            TEXT NOT NULL DEFAULT 'upload',
    ADD COLUMN files_total      INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN files_extracted  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN files_chunked    INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN enrichment_total INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN enrichment_done  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN qdrant_upserted  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN tier             TEXT,        -- 'free'/'tier_1'/..'tier_5' — после probe
    ADD COLUMN tmp_path         TEXT;        -- /data/ingest/{job_id}, NULL после cleanup

-- file_data (BYTEA) больше не используется в v2. Остаётся для совместимости.
-- Новые джобы: file_data=NULL с самого начала.
```

### 3.4 Новая таблица: `ingest_logs`

```sql
CREATE TABLE ingest_logs (
    id          BIGSERIAL PRIMARY KEY,
    job_id      TEXT REFERENCES ingest_jobs(id) ON DELETE SET NULL,
    level       TEXT NOT NULL,          -- info / warning / error
    stage       TEXT,
    message     TEXT NOT NULL,
    details     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ingest_logs_job_id_idx  ON ingest_logs(job_id);
CREATE INDEX ingest_logs_created_idx ON ingest_logs(created_at);
-- Celery beat чистит записи старше 7 дней
```

---

## 4. Tier detection для Embeddings API

### 4.1 Логика определения тира

```python
# Синглтон на уровне модуля embedder.py
_EMBEDDING_TIER: EmbeddingTierConfig | None = None
_EMBEDDING_TIER_AT: float = 0.0
_EMBEDDING_TIER_LOCK = asyncio.Lock()   # защита от race при одновременных workers
_EMBEDDING_TIER_TTL = 3600.0

async def _get_embedding_tier() -> EmbeddingTierConfig:
    global _EMBEDDING_TIER, _EMBEDDING_TIER_AT
    async with _EMBEDDING_TIER_LOCK:
        if _EMBEDDING_TIER and time.monotonic() - _EMBEDDING_TIER_AT < _EMBEDDING_TIER_TTL:
            return _EMBEDDING_TIER
        _EMBEDDING_TIER = await _probe_embedding_tier()
        _EMBEDDING_TIER_AT = time.monotonic()
        return _EMBEDDING_TIER

async def _probe_embedding_tier() -> EmbeddingTierConfig:
    # Модель берётся из llm_routing ("embedding", "*") — не хардкодится
    routing = await llm_router._get_routing("embedding", "*")
    api_key = llm_router._get_api_key(routing.provider_id)
    client = AsyncOpenAI(api_key=api_key, timeout=10)
    resp = await client.embeddings.create(
        model=routing.model_id,
        input=["probe"],
        encoding_format="float",
    )
    # Читаем заголовки из httpx response
    raw = resp._raw_response
    tpm = int(raw.headers.get("x-ratelimit-limit-tokens", 0))
    rpm = int(raw.headers.get("x-ratelimit-limit-requests", 0))
    return _classify_tier(tpm, rpm, routing.model_id)
```

### 4.2 Таблица тиров и параметров

| Tier | TPM (embeddings) | RPM | batch_size | max_concurrent |
|---|---|---|---|---|
| free | 1 000 000 | 3 000 | 100 | 1 |
| tier_1 | 1 000 000 | 3 000 | 200 | 2 |
| tier_2 | 5 000 000 | 5 000 | 500 | 5 |
| tier_3 | 10 000 000 | 5 000 | 1 000 | 8 |
| tier_4 | 30 000 000 | 10 000 | 2 048 | 15 |
| tier_5 | 100 000 000 | 10 000 | 2 048 | 40 |

Формула `max_concurrent`:
```python
avg_tokens_per_chunk = 500  # ~300 токенов чанк + ~200 contextual prefix
max_concurrent = max(1, min(40, tpm * 2 // (batch_size * avg_tokens_per_chunk * 60)))
```

**Важно:** Коэффициент `* 2` (не `* 3`+) — запас на случай когда реальная latency < 4s.
При latency=2s: эффективный rate = max_concurrent / 2s × 60 × batch_size × 500 tokens.

**Разница free vs tier_1:** OpenAI embeddings free tier имеет TPM=1M, но суточный лимит ниже.
Практически: batch_size у free=100 (меньше ошибок при первом превышении суточного).

### 4.3 EmbeddingRateLimiter — синглтон

`_RATE_LIMITER` и `_EMBED_SEM` создаются в `pipeline.py` в начале Stage 4:
```python
tier = await _get_embedding_tier()
rate_limiter = EmbeddingRateLimiter(tpm=tier.tpm, rpm=tier.rpm)
embed_sem = asyncio.Semaphore(tier.max_concurrent)
# Передаются как аргументы в embed_batch, не как глобальные переменные.
```

```python
# embedder.py — класс и tier detection. Синглтон _RATE_LIMITER не нужен —
# pipeline.py создаёт rate_limiter локально для каждого job (один job = один эмбеддинг-пасс).


class EmbeddingRateLimiter:  # создаётся в pipeline.py в начале Stage 4
    def __init__(self, tpm: int, rpm: int):
        self._tpm = tpm
        self._rpm = rpm
        self._token_bucket = float(tpm)
        self._request_bucket = float(rpm)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens_needed: int) -> None:
        while True:
            async with self._lock:
                self._refill()
                if self._token_bucket >= tokens_needed and self._request_bucket >= 1:
                    self._token_bucket -= tokens_needed
                    self._request_bucket -= 1
                    return
                needed = max(
                    (tokens_needed - self._token_bucket) / self._tpm * 60,
                    (1 - self._request_bucket) / self._rpm * 60,
                    0.05,
                )
            await asyncio.sleep(needed)  # sleep вне lock — не блокирует event loop

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._token_bucket = min(
            float(self._tpm),
            self._token_bucket + self._tpm * elapsed / 60,
        )
        self._request_bucket = min(
            float(self._rpm),
            self._request_bucket + self._rpm * elapsed / 60,
        )
        self._last_refill = now
```

---

## 5. Semantic Enrichment

### 5.1 Enrichment всегда включён в pipeline

**Enrichment является обязательной частью pipeline.** Флаги управляют только типами:

```
app_config:
  kb_enrichment_context  = "true"   # contextual prefix (меняет вектор)
  kb_enrichment_metadata = "true"   # keywords + category (только payload)
```

При `kb_enrichment_context=false` — `document_context=NULL`, чанки эмбеддятся без префикса.  
При `kb_enrichment_metadata=false` — `keywords=NULL`, `category=NULL` в Qdrant payload.

Оба флага `false` = режим без обогащения (допустим, но не рекомендован).

### 5.2 Вид 1: Contextual Prefix (меняет вектор)

Для каждого **файла** — один LLM вызов (`task_kind="kb_enrich_context"`):

```
Промпт:
  "Прочитай первые 2000 символов документа. Напиши 2-3 предложения:
   1. О чём этот документ в целом
   2. Какие основные темы/концепции рассматриваются
   3. Для кого он предназначен
   Текст: {text[:2000]}"

Результат записывается в ingest_files.document_context.
```

Перед эмбеддингом к каждому чанку того же файла препендится:
```
{document_context}
---
{chunk_text}
```

### 5.3 Вид 2: Payload Metadata (не меняет вектор)

Для батча чанков (~50 штук) — один LLM вызов (`task_kind="kb_enrich_metadata"`):

```python
CATEGORY_LIST = [
    "КПТ", "психоанализ", "травма", "отношения", "детская_психология",
    "саморазвитие", "духовность", "нарратив", "тревога", "депрессия", "другое"
]
# Список category берётся из app_config ключа "kb_category_list" (JSON array)
# Это позволяет настраивать под разные коллекции без кода.
```

```
Промпт:
  "Для каждого пронумерованного фрагмента извлеки:
   - keywords: 3-5 ключевых слов через запятую
   - category: одна из {CATEGORY_LIST}
   Формат: [N] keywords: ... | category: ..."
```

Результат кладётся в `ingest_chunks.keywords` и `ingest_chunks.category`,
затем в Qdrant payload при upsert.

### 5.4 Rate limiter для enrichment

Enrichment LLM вызовы используют **тот же LLM router** с task_kind'ами:
- `kb_enrich_context` — один вызов на файл, можно параллелить файлы
- `kb_enrich_metadata` — один вызов на 50 чанков, батчевый

Конкурентность для enrichment LLM ограничивается через asyncio.Semaphore,
настраиваемый из `app_config`:
```
kb_enrich_concurrency = "4"   # одновременных LLM enrichment вызовов
```

```python
# Ленивая инициализация — нельзя создавать asyncio.Semaphore на уровне модуля
# (event loop может ещё не стартовать при импорте). Создаётся при первом вызове.
_ENRICH_SEM: asyncio.Semaphore | None = None  # см. get_enrich_sem() в enricher.py
```

### 5.5 Новые task_kind в llm_routing

**Требование CLAUDE.md:** каждый LLM вызов через `llm_router.call()` должен иметь task_kind,
зарегистрированный в таблице `llm_routing`. Миграция 017 должна добавить seed-данные:

```sql
-- В том же файле 017_ingest_v2.py или в отдельной 018_ingest_routing_seed.py
INSERT INTO llm_routing (task_kind, tier, provider_id, model_id, max_tokens, temperature)
VALUES
  ('kb_enrich_context',  '*', 'openai', 'gpt-4o-mini', 300, 0.3),
  ('kb_enrich_metadata', '*', 'openai', 'gpt-4o-mini', 500, 0.1)
ON CONFLICT (task_kind, tier) DO NOTHING;
```

### 5.6 Обогащение существующих данных

Для уже загруженных коллекций — отдельный endpoint:

```
POST /admin/kb/collections/{collection}/enrich-metadata
```

- Перебирает все точки в Qdrant через scroll API (по 100 точек)
- Для батча точек вызывает `task_kind="kb_enrich_metadata"` → keywords/category
- Обновляет payload через `qdrant.set_payload()` — без ре-эмбеддинга

**NB:** Contextual prefix для существующих данных требует полного ре-индексинга
(удалить коллекцию → загрузить заново с `kb_enrichment_context=true`).

---

## 6. Временное хранилище файлов

### 6.1 Docker volume (не /tmp)

```yaml
# docker-compose.dev.yml
services:
  app:
    volumes:
      - ingest_data:/data/ingest   # Docker named volume — переживает restart

volumes:
  ingest_data:
```

**Важно:** `/tmp` в Docker — ephemeral tmpfs, очищается при рестарте контейнера.
Используем Docker named volume `/data/ingest` который переживает restart.

### 6.2 Структура на диске

```
/data/ingest/{job_id}/
  ├── original.zip         # или original.pdf / original.epub
  └── texts/
        ├── {file_id_1}.txt    # extracted raw text
        ├── {file_id_2}.txt
        └── ...
```

### 6.3 Жизненный цикл

| Событие | Действие |
|---|---|
| Upload | Создать `/data/ingest/{job_id}/`, сохранить исходный файл |
| Extract | Записать `/data/ingest/{job_id}/texts/{file_id}.txt` |
| Chunk | Чтение текстовых файлов (не удалять — нужны для retry) |
| Cleanup (stage 5) | `shutil.rmtree(/data/ingest/{job_id}/)` |
| App restart | При старте: очистить все `/data/ingest/*/` для job_id где status='done' |
| App restart | При старте: reset `ingest_jobs SET status='error' WHERE status='running'` |

### 6.4 Лимиты

Конфигурируются в `app_config`:
```
kb_max_zip_size_mb  = "500"   # максимальный размер ZIP
kb_max_file_size_mb = "100"   # максимальный размер одного файла в ZIP
kb_max_files_in_zip = "500"   # максимальное количество файлов в ZIP
```

### 6.5 Deduplication

При загрузке файла с тем же именем в ту же коллекцию:
- Новый джоб создаётся как обычно (нет блокировки)
- Qdrant upsert идёт по `qdrant_point_id` = UUID нового чанка (новые точки)
- Старые точки того же файла **не удаляются автоматически**
- Перед загрузкой дубля: Admin UI показывает предупреждение если коллекция уже содержит
  данные из файла с тем же именем (поиск по `ingest_files.filename`)

---

## 7. Admin UI — обновление прогресс-баров

### 7.1 Новая структура карточки джоба

```
┌─────────────────────────────────────────────────────────────┐
│  knowledge_psych_relationships.zip → knowledge_psych_rel... │
│  Загружено: 23 апр 20:07  │  Статус: embedding             │
├─────────────────────────────────────────────────────────────┤
│  Извлечение файлов   ████████████████████  18/18  ✓        │
│  Нарезка чанков      ████████████████████  18/18  ✓        │
│  Обогащение          ██████████████░░░░░░  1400/1792  78%  │
│  Эмбеддинг           █████████░░░░░░░░░░░   820/1792  46%  │
│  Qdrant upsert       █████████░░░░░░░░░░░   820/1792  46%  │
├─────────────────────────────────────────────────────────────┤
│  ETA: ~8 мин  │  Скорость: ~35 чанков/сек  │  Tier: 2     │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Polling endpoint

```
GET /admin/kb/jobs/{job_id}/progress
Response:
{
  "job_id": "...",
  "status": "embedding",
  "stage": "embed",
  "filename": "knowledge_psych_relationships.zip",
  "files_total": 18,
  "files_extracted": 18,
  "files_chunked": 18,
  "enrichment_total": 1792,
  "enrichment_done": 1400,
  "chunks_total": 1792,
  "chunks_done": 820,
  "qdrant_upserted": 820,
  "tier": "tier_2",
  "speed_cps": 35.2,        // chunks per second (скользящее среднее за последние 30s)
  "eta_seconds": 480,
  "error": null
}
```

`speed_cps` и `eta_seconds` вычисляются в endpoint из `chunks_done` и временного окна — не хранятся в БД.

### 7.3 Частота обновления UI

- Активный джоб: poll каждые **2 секунды**
- Завершённый за последние 5 мин: poll каждые **10 секунд**
- Старше 5 мин: отображается статично

---

## 8. API изменения

### 8.1 Новые/изменённые endpoints

```
# Загрузка файла — теперь НЕ хранит в БД как blob
POST /admin/kb/ingest-file
  - Проверяет размер файла (kb_max_zip_size_mb)
  - Сохраняет на диск /data/ingest/{job_id}/
  - Создаёт ingest_jobs (без file_data)
  - Возвращает: { job_id, status: "queued" }

# Загрузка URL — интерфейс без изменений, рефакторинг внутри
# URL flow по-прежнему синхронный (не через queue), т.к. GitHub/HF датасеты
# обрабатываются специальными функциями. Рефакторинг URL flow — вне скопа v2.

# Прогресс по джобу (новый)
GET /admin/kb/jobs/{job_id}/progress
  - Детальный прогресс по этапам

# Список джобов — расширен новыми полями
GET /admin/kb/jobs
  - Добавлены: stage, files_total, files_extracted, files_chunked,
               enrichment_total, enrichment_done, qdrant_upserted, tier

# Retry (изменён)
POST /admin/kb/jobs/{job_id}/retry
  - Проверяет наличие tmp_path на диске
  - Если не существует → 409 с пояснением
  - Если существует → сбрасывает staging, ставит в queue

# Обогащение существующих данных (новый)
POST /admin/kb/collections/{collection}/enrich-metadata
  - Запускает enrichment job для уже загруженной коллекции
  - Только keywords + category (без ре-эмбеддинга)

# Логи по джобу (новый)
GET /admin/kb/jobs/{job_id}/logs?limit=100&level=all
  - Возвращает ingest_logs для job_id
  - Сортировка по created_at DESC
```

### 8.2 Удалённые/изменённые функции

| Функция | Действие |
|---|---|
| `_batch_translate_texts()` | **УДАЛИТЬ** полностью |
| `_llm_translate_to()` | **УДАЛИТЬ** полностью |
| `_parse_numbered_translations()` | **УДАЛИТЬ** полностью |
| `_upsert_bilingual_chunks()` | **ЗАМЕНИТЬ** на `_embed_and_upsert_chunks()` |
| `_upsert_bilingual_entries()` | **ЗАМЕНИТЬ** на `_embed_and_upsert_entries()` |
| `_ingest_zip()` | **ЗАМЕНИТЬ** на `_run_ingest_zip_v2()` |
| `_run_ingest_job()` | **РЕФАКТОРИНГ** — делегирует в `pipeline.py` |
| `_GLOBAL_TRANSLATE_SEM` | **УДАЛИТЬ** → заменить на `EmbeddingRateLimiter` в `embedder.py` |
| `_maybe_refresh_translate_sem()` | **ЗАМЕНИТЬ** на `_get_embedding_tier()` |

---

## 9. Параллелизм и производительность

### 9.1 Параллелизм по этапам

**Stage 2 (Extract):**
```python
# CPU-bound работа (pypdf, ebooklib) — в ThreadPoolExecutor
_THREAD_POOL = ThreadPoolExecutor(max_workers=4)
EXTRACT_SEM = asyncio.Semaphore(10)  # не более 10 файлов одновременно

async def extract_file(file_bytes, ext):
    async with EXTRACT_SEM:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_THREAD_POOL, _extract_text_sync, file_bytes, ext)
```

**Stage 3 (Chunk + Enrich):**
```python
# Chunking — параметры: max_chars=900, overlap=100 (сохраняем текущую реализацию)
# _ENRICH_SEM — ленивая инициализация при первом use (нельзя на уровне модуля до app startup)
_ENRICH_SEM: asyncio.Semaphore | None = None

def get_enrich_sem(concurrency: int = 4) -> asyncio.Semaphore:
    global _ENRICH_SEM
    if _ENRICH_SEM is None:
        _ENRICH_SEM = asyncio.Semaphore(concurrency)
    return _ENRICH_SEM

CHUNK_SEM = asyncio.Semaphore(10)   # по файлам параллельно

async def chunk_and_enrich_file(file, enrich_sem):
    async with CHUNK_SEM:
        text = open(file.text_path).read()
        chunks = _chunk_text(text, max_chars=900, overlap=100)

        # Context enrichment — 1 LLM call per file
        async with enrich_sem:
            doc_context = await _enrich_context(text[:2000])  # может вернуть None при ошибке

        # Metadata enrichment — по батчам, каждый батч под семафором
        metadata_list = []
        for i in range(0, len(chunks), 50):
            batch = chunks[i:i+50]
            async with enrich_sem:
                meta = await _enrich_metadata_batch(batch)  # возвращает [{keywords, category}]
            metadata_list.extend(meta)
            # UPDATE ingest_jobs enrichment_done += len(batch)

        await _insert_chunks(chunks, metadata_list)
```

**Stage 4 (Embed):**
```python
# _RATE_LIMITER и embed_sem создаются в pipeline.py в начале Stage 4
# после получения tier (см. flow Section 2.2)

async def embed_batch(batch_chunks, embed_sem, rate_limiter):
    # batch_chunks = [{id, text, doc_context, keywords, category, ...}]
    texts = [
        f"{c['doc_context']}\n---\n{c['text']}" if c.get('doc_context') else c['text']
        for c in batch_chunks
    ]
    tokens_estimate = len(texts) * 500
    await rate_limiter.acquire(tokens_estimate)
    async with embed_sem:
        # API call + qdrant upsert
        ...
```

### 9.2 Оценка производительности

| Tier | batch_size | concurrent | Скорость (чанков/мин) | Время 1792 чанков |
|---|---|---|---|---|
| free/tier_1 | 100-200 | 1-2 | ~150-300 | ~6-12 мин |
| tier_2 | 500 | 5 | ~800 | ~2 мин |
| tier_3 | 1000 | 8 | ~2000 | ~1 мин |
| tier_4 | 2048 | 15 | ~5000 | ~20 сек |

*(С enrichment: +30-60% времени на LLM вызовы. Enrichment идёт на stage 3 до embed,
поэтому время embed не меняется — pipeline stages overlap если workers>1.)*

---

## 10. Логирование

### 10.1 Структура лога

Каждое значимое событие логируется в `ingest_logs`:

```python
# Примеры событий
{"level": "info",  "stage": "extract",  "message": "file_extracted",
 "details": {"filename": "burns.epub", "char_count": 284000, "source_lang": "ru", "file_id": "..."}}

{"level": "warning", "stage": "extract", "message": "file_extract_failed",
 "details": {"filename": "corrupt.pdf", "error": "PdfReadError: EOF marker not found"}}

{"level": "info",  "stage": "chunk",    "message": "file_chunked",
 "details": {"filename": "burns.epub", "chunk_count": 319, "file_id": "..."}}

{"level": "info",  "stage": "enrich",   "message": "context_generated",
 "details": {"file_id": "...", "doc_context_len": 287, "latency_ms": 890}}

{"level": "info",  "stage": "embed",    "message": "batch_embedded",
 "details": {"batch_size": 500, "tokens_used": 250000, "latency_ms": 1240}}

{"level": "error", "stage": "embed",    "message": "batch_failed",
 "details": {"error": "RateLimitError", "retry": 2, "batch_start": 500}}

{"level": "info",  "stage": "cleanup",  "message": "job_done",
 "details": {"total_chunks": 1792, "qdrant_upserted": 1792, "duration_s": 87}}
```

### 10.2 Ротация логов

Celery beat task (новый, ежедневно в 03:00):

```python
@celery_app.task
def cleanup_ingest_logs():
    """Delete ingest_logs older than 7 days."""
    # DELETE FROM ingest_logs WHERE created_at < now() - interval '7 days'
```

### 10.3 Просмотр логов в Admin UI

Вкладка "Логи" в карточке джоба:
- Таблица с уровнем, этапом, сообщением, временем
- Фильтр по уровню (info / warning / error)
- Автообновление пока джоб в процессе

---

## 11. Файловая структура изменений

```
mirror/
├── admin/
│   ├── router.py          # Рефакторинг: ingest endpoint + _ingest_worker
│   ├── schemas.py         # Новые схемы: IngestProgressResponse, IngestLogEntry
│   └── ui.py              # 5 прогресс-баров, вкладка логов
├── services/
│   └── ingest/            # НОВЫЙ модуль
│       ├── __init__.py
│       ├── pipeline.py    # _run_ingest_job_v2(): orchestrates stages 1-5
│       ├── extractor.py   # _extract_text_sync (PDF/EPUB/TXT), lang detection
│       ├── chunker.py     # _chunk_text, _split_sentences (RecursiveTextSplitter)
│       ├── enricher.py    # _enrich_context, _enrich_metadata_batch, _ENRICH_SEM
│       ├── embedder.py    # _get_embedding_tier, EmbeddingRateLimiter, _embed_and_upsert
│       └── cleanup.py     # cleanup stage: rmtree + DB cleanup
├── workers/
│   └── tasks/
│       └── ingest.py      # НОВЫЙ: cleanup_ingest_logs, reset_stale_ingest_jobs
└── db/
    └── migrations/
        └── versions/
            ├── 017_ingest_v2.py         # DDL: ingest_files, ingest_chunks, ingest_logs,
            │                             #      ALTER ingest_jobs, Docker volume note
            └── 018_ingest_routing_seed.py  # INSERT kb_enrich_context, kb_enrich_metadata
                                             # INSERT app_config keys
```

---

## 12. Миграция данных и конфигурация

### 12.1 Обратная совместимость

Старые джобы (status='done') остаются как есть. Новые поля (stage, files_total и т.д.) —
значение по умолчанию '0'/NULL — не ломают существующие строки.

Старые джобы с `status='error'` → retry проверяет tmp_path. Если `tmp_path=NULL`
(старый формат без v2 полей) → возвращает 409 "Загрузите файл заново".

### 12.2 Очистка старых blob-данных

После деплоя — опциональный SQL:
```sql
UPDATE ingest_jobs SET file_data = NULL
WHERE status = 'done' AND file_data IS NOT NULL;
```
Запускается вручную в удобное время (не в миграции, т.к. блокирует большую таблицу).

### 12.3 app_config seed (в миграции 017 или 018)

```sql
INSERT INTO app_config (key, value, description)
VALUES
  ('kb_enrichment_context',  'true',  'Enable contextual prefix for KB ingest'),
  ('kb_enrichment_metadata', 'true',  'Enable keywords+category extraction for KB ingest'),
  ('kb_enrich_concurrency',  '4',     'Max parallel LLM calls for enrichment'),
  ('kb_max_zip_size_mb',     '500',   'Max ZIP upload size in MB'),
  ('kb_max_file_size_mb',    '100',   'Max single file size in ZIP in MB'),
  ('kb_max_files_in_zip',    '500',   'Max files per ZIP'),
  ('kb_category_list',       '["КПТ","психоанализ","травма","отношения","детская_психология","саморазвитие","духовность","нарратив","тревога","депрессия","другое"]',
                             'JSON array of categories for enrichment classifier')
ON CONFLICT (key) DO NOTHING;
```

### 12.4 Docker Compose обновление

```yaml
# docker-compose.dev.yml
services:
  app:
    volumes:
      - ingest_data:/data/ingest
      # ... остальные volumes

volumes:
  ingest_data:
    driver: local
```

---

## 13. Celery задачи

### 13.1 cleanup_ingest_logs

```python
@celery_app.task(name="ingest.cleanup_logs")
def cleanup_ingest_logs():
    # DELETE FROM ingest_logs WHERE created_at < now() - '7 days'::interval
    # Логировать количество удалённых строк
```

Schedule: ежедневно в 03:00.

### 13.2 reset_stale_ingest_jobs

```python
@celery_app.task(name="ingest.reset_stale")
def reset_stale_ingest_jobs():
    """
    Джоб в статусе 'running' дольше 2 часов — застрял (crash/restart).
    Сбрасываем в 'error' чтобы пользователь мог сделать retry.
    """
    # UPDATE ingest_jobs
    # SET status='error', error='Job stalled — restarted by system', updated_at=now()
    # WHERE status='running'
    #   AND updated_at < now() - '2 hours'::interval
```

Schedule: каждые 15 минут.

**NB:** При старте FastAPI lifespan — тоже вызвать reset_stale_ingest_jobs синхронно,
чтобы не ждать Celery beat.

---

## 14. Acceptance Criteria

### AC-01: Перевод отключён
- [ ] Нет вызовов к `_batch_translate_texts`, `_llm_translate_to`
- [ ] В Qdrant каждый чанк хранится в **одном** экземпляре (не два)
- [ ] Поле `lang` в payload заполняется из `ingest_files.source_lang` (определяется langdetect)

### AC-02: Staging таблицы
- [ ] После upload: строка в ingest_jobs с `stage='upload'`, `tmp_path` заполнен
- [ ] После extract: строки в `ingest_files` с `file_status='extracted'`, `text_path` заполнен
- [ ] После chunk: строки в `ingest_chunks` созданы, `file_status='chunked'`
- [ ] После embed: `chunk_status='done'`, `qdrant_point_id` заполнен
- [ ] После cleanup: `/data/ingest/{job_id}/` удалена, `tmp_path=NULL`, ingest_chunks удалены

### AC-03: Tier detection
- [ ] При первом инджесте — пробинг `/embeddings` API (с Lock, без race)
- [ ] `batch_size` и `max_concurrent` соответствуют таблице тиров
- [ ] `ingest_jobs.tier` заполняется после probe
- [ ] Пробинг кешируется на 1 час

### AC-04: Прогресс-бары
- [ ] GET `/admin/kb/jobs/{job_id}/progress` возвращает все поля включая `qdrant_upserted` и `tier`
- [ ] UI показывает 5 прогресс-баров для активного джоба
- [ ] ETA и скорость обновляются в реальном времени

### AC-05: Semantic enrichment
- [ ] При `kb_enrichment_context=true`: `ingest_files.document_context` заполнен, payload содержит `has_context=true`
- [ ] При `kb_enrichment_metadata=true`: `keywords` и `category` заполнены в Qdrant payload
- [ ] LLM вызовы идут через `llm_router.call("kb_enrich_context", ...)` и `("kb_enrich_metadata", ...)`
- [ ] Оба task_kind зарегистрированы в llm_routing (миграция 018)
- [ ] При `kb_enrichment_context=false`: pipeline работает без contextual prefix, не падает

### AC-06: Параллелизм и rate limiting
- [ ] Extract: CPU-bound работа (pypdf/ebooklib) идёт в ThreadPoolExecutor
- [ ] Embed: Token Bucket не даёт превысить TPM/RPM лимиты тира
- [ ] Нет rate-limit ошибок при нормальной работе (0 `Retrying request to...` в логах)

### AC-07: Очистка и логирование
- [ ] `ingest_logs` заполняется на каждом этапе включая ошибки отдельных файлов
- [ ] Celery task `cleanup_ingest_logs` удаляет записи старше 7 дней
- [ ] Вкладка "Логи" в Admin UI показывает события джоба

### AC-08: Обратная совместимость
- [ ] Завершённые (status='done') джобы не затронуты
- [ ] Endpoint `/admin/kb/ingest-file` принимает те же параметры
- [ ] ZIP-авторутинг по коллекциям работает как раньше

### AC-09: Retry и stale job handling
- [ ] Retry для v2 джоба с существующим tmp_path — успешно перезапускает с чистого состояния
- [ ] Retry без tmp_path — возвращает 409 с понятным сообщением
- [ ] Celery task `reset_stale_ingest_jobs` сбрасывает застрявшие 'running' джобы

### AC-10: Конфигурация
- [ ] app_config ключи из 12.3 присутствуют после миграции
- [ ] Изменение `kb_enrichment_context` в Admin UI Config — следующий инджест применяет новое значение

---

## 15. Зависимости и риски

| Риск | Вероятность | Митигация |
|---|---|---|
| OpenAI rate limit при burst | Средняя | Token Bucket limiter; EmbeddingRateLimiter singleton |
| LLM enrichment rate limit | Средняя | `_ENRICH_SEM` + `kb_enrich_concurrency` в app_config |
| Большие ZIP (>500MB) вызовут OOM | Низкая | Лимит в `kb_max_zip_size_mb` + проверка до сохранения |
| Незавершённые джобы при restart | Высокая | Docker volume переживает restart; Celery reset_stale; resume по chunk_status='pending' |
| Disk space — /data/ingest переполнится | Низкая | Limits per zip; cleanup после done; startup-cleanup стale dirs |
| Частичный сбой embed (500/1792) | Средняя | Resume: SELECT WHERE chunk_status='pending' — skip already done chunks |
| Дубль файла в коллекции | Низкая | UI предупреждение; деdup — ответственность пользователя |
| Файл внутри ZIP с ошибкой | Средняя | Log + skip, не abort весь job; file_status='error' |
| race при tier probe | Низкая | asyncio.Lock(_EMBEDDING_TIER_LOCK) |

---

## 16. Порядок реализации

| Шаг | Задача | Приоритет |
|---|---|---|
| 1 | Миграция 017_ingest_v2.py + 018_ingest_routing_seed.py | Критично |
| 2 | docker-compose.dev.yml: добавить volume ingest_data | Критично |
| 3 | Убрать перевод (`_batch_translate_texts` и всё связанное) из admin/router.py | Критично |
| 4 | `mirror/services/ingest/extractor.py` — extract + lang detection (langdetect) | Высокий |
| 5 | `mirror/services/ingest/chunker.py` — chunk text | Высокий |
| 6 | `mirror/services/ingest/embedder.py` — tier detection (с Lock) + Token Bucket | Высокий |
| 7 | `mirror/services/ingest/enricher.py` — contextual prefix + payload metadata | Высокий |
| 8 | `mirror/services/ingest/pipeline.py` — stages 1-5 (single file + ZIP) | Высокий |
| 9 | Рефакторинг `admin/router.py` — использует pipeline.py, новый retry flow | Высокий |
| 10 | GET `/admin/kb/jobs/{job_id}/progress` | Средний |
| 11 | Admin UI — 5 прогресс-баров + вкладка логов | Средний |
| 12 | Celery tasks: cleanup_ingest_logs + reset_stale_ingest_jobs | Средний |
| 13 | POST `/admin/kb/collections/{col}/enrich-metadata` | Низкий |
| 14 | Тесты | Обязательно перед мержем |
