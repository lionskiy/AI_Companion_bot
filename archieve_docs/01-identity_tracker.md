# Module 01: Identity — Tracker

**Спека:** `01-identity_spec.md`  
**Статус:** ожидает старта

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| I-01 | Создать Alembic-миграцию: таблицы `users` + `channel_identities` + `user_profiles` | `mirror/db/migrations/versions/001_identity.py` | `alembic upgrade head` → OK; `\d user_profiles` видна |
| I-02 | Создать SQLAlchemy ORM-модели `User`, `ChannelIdentity`, `UserProfile` | `mirror/models/user.py` | `python -m py_compile mirror/models/user.py` |
| I-03 | Реализовать `IdentityService` (get_or_create создаёт user + profile + вызывает billing; get_user; update_timezone) | `mirror/core/identity/service.py` | `python -m py_compile` |
| I-04 | Реализовать `jwt_handler.py` (create_token, verify_token, get_current_user_id) | `mirror/core/identity/jwt_handler.py` | `python -m py_compile` |
| I-05 | Написать тесты: идемпотентность get_or_create, user_profiles создаётся вместе с user, verify_token | `tests/identity/test_identity.py` | `pytest tests/identity/ -v` → PASSED |

🛑 **CHECKPOINT:** `pytest tests/identity/` зелёный, `alembic upgrade head` чистый.
