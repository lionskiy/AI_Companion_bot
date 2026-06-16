# Module 09: Daily Ritual — Tracker

**Спека:** `09-daily_ritual_spec.md` · **Зависимости:** Modules 01, 05, 07, 08 выполнены

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| DR-01 | Миграция: `daily_ritual_log` + `user_profiles.daily_ritual_enabled` | `mirror/db/migrations/versions/006_daily_ritual.py` | `alembic upgrade head` |
| DR-02 | `DailyRitual` dataclass | `mirror/services/daily_ritual.py` | `python -m py_compile` |
| DR-03 | `DailyRitualService.build_ritual()` — карта + транзит + аффирмация (task_kind="proactive_compose") | `mirror/services/daily_ritual.py` | `python -m py_compile` |
| DR-04 | `DailyRitualService.format_ritual_message()` — форматирование Markdown | `mirror/services/daily_ritual.py` | `python -m py_compile` |
| DR-05 | `DailyRitualService.handle()` — вход из DialogService | `mirror/services/daily_ritual.py` | `python -m py_compile` |
| DR-06 | Celery задача `send_daily_rituals` (hourly) + `send_ritual_to_user` | `mirror/workers/tasks/daily_ritual.py` | `python -m py_compile` |
| DR-07 | Celery Beat расписание (crontab hourly) | `mirror/workers/celery_app.py` | `celery inspect scheduled` → задача видна |
| DR-08 | Тесты: build_ritual без birth_date, идемпотентность, format_message | `tests/daily_ritual/test_daily_ritual.py` | `pytest tests/daily_ritual/ -v` → PASSED |

🛑 **CHECKPOINT:** ритуал строится без birth_date, повторный запуск задачи не создаёт дубль.
