# Module 04: Policy & Safety — Tracker

**Спека:** `04-policy_safety_spec.md` · **Зависимости:** Module 05 (LLM-05 выполнен)

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| P-01 | Миграция: `safety_log` + `app_config` (для кризисного шаблона) | `mirror/db/migrations/versions/004_policy.py` | `alembic upgrade head` |
| P-02 | `PolicyResult`, `RiskLevel` dataclass/enum | `mirror/core/policy/models.py` | `python -m py_compile` |
| P-03 | Словарь быстрых паттернов (seed данные) | `mirror/core/policy/patterns.py` | Импорт без ошибок |
| P-04 | Реализовать `PolicyEngine` (check, _fast_pattern_match, _llm_classify) | `mirror/core/policy/safety.py` | `python -m py_compile` |
| P-05 | Кризисный шаблон: seed в `app_config` через миграцию | `mirror/db/migrations/versions/004_policy.py` | `SELECT value FROM app_config WHERE key='crisis_response'` |
| P-06 | NATS publisher: `mirror.safety.crisis_detected` | `mirror/events/publishers/safety.py` | `python -m py_compile` |
| P-07 | Тесты: crisis паттерн, risk_signal, wellbeing, sales_allowed | `tests/policy/test_policy.py` | `pytest tests/policy/ -v` → PASSED |

🛑 **CHECKPOINT:** кризисный тест проходит, `safety_log` без ПДн.
