# Module 02: Telegram Adapter — Tracker

**Спека:** `02-telegram_adapter_spec.md`  
**Зависимости:** I-05 выполнен

---

| ID | Задача | Файлы | Верификация |
|----|--------|-------|------------|
| T-01 | Создать `UnifiedMessage`, `UnifiedResponse` в `base.py` | `mirror/channels/base.py` | `python -m py_compile mirror/channels/base.py` |
| T-02 | Реализовать `TelegramAdapter` (to_unified, send, callback_to_unified, _get_or_create_session) | `mirror/channels/telegram/adapter.py` | `python -m py_compile` |
| T-03 | Реализовать webhook endpoint: проверка заголовка `X-Telegram-Bot-Api-Secret-Token`, вызов `dp.process_update()` | `mirror/channels/telegram/webhook.py` | Запрос без заголовка → 403; с правильным токеном → 200 |
| T-04 | Реализовать handlers: `/start` (закрытие старой сессии + NATS), `/help`, `/quiet`, `/active`, обычное сообщение | `mirror/channels/telegram/handlers.py` | `python -m py_compile` |
| T-05 | Webhook регистрируется в lifespan: `bot.set_webhook(url, secret_token=...)` | `mirror/main.py` | При старте в логах: `webhook set: https://...` |
| T-06 | Написать тесты: to_unified, верификация заголовка, split_text, session close при /start | `tests/telegram/test_adapter.py` | `pytest tests/telegram/ -v` → PASSED |

🛑 **CHECKPOINT:** тесты зелёные, webhook принимает update.
