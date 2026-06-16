# Module 10: Free Billing — Tracker

**Спека:** `10-free_billing_spec.md` · **Зависимости:** Module 01 выполнен

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| B-01 | Миграция: `subscriptions` + `quota_config` + seed (4 тарифа) | `mirror/db/migrations/versions/007_billing.py` | `alembic upgrade head` → `SELECT * FROM quota_config` = 4 строки |
| B-02 | ORM-модели `Subscription`, `QuotaConfig` | `mirror/models/billing.py` | `python -m py_compile` |
| B-03 | `QuotaResult` dataclass + `QuotaExceededError` | `mirror/services/billing.py` | `python -m py_compile` |
| B-04 | `BillingService.get_tier(user_id)` — чтение из `subscriptions` | `mirror/services/billing.py` | `python -m py_compile` |
| B-05 | `BillingService.create_free_subscription(user_id)` + `sync_user_subscription_cache()` — вызывается из IdentityService | `mirror/services/billing.py` | `python -m py_compile`; после create — `users.subscription='free'` |
| B-06 | `BillingService.check_quota(user_id)` — Redis INCR + EXPIREAT + quota_config | `mirror/services/billing.py` | `python -m py_compile` |
| B-07 | Интеграция в `DialogService.handle()`: quota check перед графом | `mirror/services/dialog.py` | `python -m py_compile` |
| B-08 | Тесты: free лимит, pro без лимита, Redis TTL, create_free_subscription | `tests/billing/test_billing.py` | `pytest tests/billing/ -v` → PASSED |

🛑 **CHECKPOINT:** при 21-м сообщении возвращается QuotaResult(allowed=False), pro пользователь не блокируется.
