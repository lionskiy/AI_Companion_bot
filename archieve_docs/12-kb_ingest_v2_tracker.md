# 12 — KB Ingest v2: Tracker

**Ссылка на спеку:** `12-kb_ingest_v2_spec.md` (v1.2 — после инспекции и исправлений)  
**Статус:** в работе  

Правила выполнения: один шаг → верификация → следующий. СТОП на каждом чекпоинте 🛑.

---

## Прогресс

| Шаг | Задача | Статус |
|---|---|---|
| 1 | Миграция 017_ingest_v2.py + 018_ingest_routing_seed.py | ✅ готово |
| 2 | docker-compose.dev.yml: volume ingest_data | ✅ готово |
| 3 | Убрать перевод из admin/router.py | ✅ готово |
| 4 | mirror/services/ingest/extractor.py + chunker.py | ✅ готово |
| 5 | mirror/services/ingest/embedder.py (tier detection + Token Bucket) | ✅ готово |
| 6 | mirror/services/ingest/enricher.py | ✅ готово |
| 7 | mirror/services/ingest/pipeline.py (stages 1-5) | ✅ готово |
| 8 | Рефакторинг admin/router.py под новый pipeline + retry | ✅ готово |
| 9 | GET /admin/kb/jobs/{job_id}/progress + logs | ✅ готово |
| 10 | Admin UI — 5 прогресс-баров + вкладка логов | ⏳ ожидает |
| 11 | Celery tasks: cleanup_ingest_logs + reset_stale_ingest_jobs | ✅ готово |
| 12 | POST /admin/kb/collections/{col}/enrich-metadata | ⏳ ожидает |
| 13 | Тесты (19/20 passed, 1 skipped — bs4) | ✅ готово |

---

## Чекпоинты

🛑 **CHECKPOINT 1:** Миграция применена, таблицы созданы. `alembic current` без ошибок.

🛑 **CHECKPOINT 2:** Перевод удалён. Тест: ingest небольшого файла → в Qdrant 1 экземпляр чанка (не 2).

🛑 **CHECKPOINT 3:** Новый pipeline работает end-to-end. ZIP загружается, чанки появляются в Qdrant, /tmp очищается.

🛑 **CHECKPOINT 4:** Rate limiter держит RPM/TPM в норме — нет `Retrying request to...` в логах при ingest.

🛑 **CHECKPOINT 5:** Enrichment включён. Чанки в Qdrant имеют `contextual_prefix`, `keywords`, `category` в payload.

🛑 **CHECKPOINT FINAL:** Все AC из спеки выполнены. Тесты зелёные. Документация обновлена.
