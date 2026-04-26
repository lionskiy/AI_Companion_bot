# Module 02: Telegram Adapter — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §11, §12.8, Appendix A  
**Зависимости:** Module 01 (Identity)  
**Дата:** 2026-04-20

---

## Цель

Тонкий адаптер между Telegram API (aiogram) и бизнес-логикой. Нормализует входящие сообщения в `UnifiedMessage`, передаёт в `DialogService`, отправляет `UnifiedResponse` обратно в Telegram. Бизнес-логика ничего не знает об aiogram.

---

## Acceptance Criteria

- [ ] Webhook-эндпоинт `POST /webhook/telegram/{secret}` принимает обновления Telegram
- [ ] Верификация: заголовок `X-Telegram-Bot-Api-Secret-Token` совпадает с `settings.telegram_webhook_secret`
- [ ] Неверный secret → `403`, без деталей в ответе
- [ ] Webhook регистрируется у Telegram при старте приложения (в lifespan)
- [ ] Каждое входящее сообщение → `UnifiedMessage` с заполненным `global_user_id`
- [ ] `/start` → `is_first_message=True` в `UnifiedMessage`
- [ ] Ответ пользователю разбивается на части если > 4000 символов
- [ ] Inline-кнопки из `UnifiedResponse.buttons` → `InlineKeyboardMarkup`
- [ ] FSM state хранится в Redis (не в памяти воркера)
- [ ] `AllModelsUnavailableError` → friendly сообщение без деталей
- [ ] `QuotaExceededError` → сообщение о дневном лимите
- [ ] Все ошибки логируются без ПДн (только `user_id`, `session_id`)

---

## Out of Scope

- VK, WhatsApp, Web адаптеры (Этап 2+)
- Голосовые сообщения / STT (Этап 5)
- Inline mode Telegram
- Payments через Telegram Stars (Этап 2)

---

## UnifiedMessage / UnifiedResponse (Appendix A POD)

```python
# mirror/channels/base.py

class UnifiedMessage(BaseModel):
    message_id:       str
    channel:          str        # "telegram"
    chat_id:          str        # Telegram chat.id (для ответа; в личных чатах = channel_user_id)
    channel_user_id:  str        # Telegram user.id как строка
    global_user_id:   str        # UUID из IdentityService
    text:             str
    media_url:        str | None = None
    timestamp:        datetime
    is_first_message: bool = False
    session_id:       str        # UUID, берётся или создаётся из Redis
    metadata:         dict       # language_code, platform, timezone
    raw_payload:      dict       # полный Update для аудита (не логировать — содержит ПДн)

class UnifiedResponse(BaseModel):
    text:             str
    chat_id:          str        # Telegram chat_id (для личных чатов = channel_user_id)
    channel:          str        # "telegram"
    buttons:          list[dict] | None = None  # [{"text": "...", "callback_data": "..."}]
    media_url:        str | None = None
    parse_mode:       str | None = None         # "HTML" | None
```

---

## Архитектура адаптера

```
TelegramAdapter
├── to_unified(message: Message) → UnifiedMessage
│     └── identity_service.get_or_create(channel, channel_user_id)
│     └── _get_or_create_session(global_user_id) → session_id  (Redis)
├── send(response: UnifiedResponse) → None          # chat_id берётся из response.chat_id
│     └── split_text если > 4000 символов
│     └── build_keyboard(buttons) → InlineKeyboardMarkup
└── callback_to_unified(callback: CallbackQuery, action: str) → UnifiedMessage
```

---

## Handlers (тонкий слой)

```python
# mirror/channels/telegram/handlers.py

@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    unified = await adapter.to_unified(message)
    unified.is_first_message = True
    response = await dialog_service.handle(unified)
    await adapter.send(response)  # chat_id уже внутри UnifiedResponse

@router.message()
async def handle_message(message: Message) -> None:
    unified = await adapter.to_unified(message)
    response = await dialog_service.handle(unified)
    await adapter.send(response)  # chat_id уже внутри UnifiedResponse

@router.callback_query(lambda c: c.data.startswith("action:"))
async def handle_callback(callback: CallbackQuery) -> None:
    ...
```

**Правило:** handlers содержат ТОЛЬКО нормализацию + делегирование. Никакой бизнес-логики.

---

## Session management (Redis)

```
Ключ: session:{global_user_id}
Value: {"session_id": UUID, "created_at": ISO}
TTL: 48ч (mem_L1)

Логика: если ключ есть → вернуть session_id; нет → создать новый UUID
```

### Закрытие сессии и NATS-событие

Сессия считается закрытой в двух случаях:

1. **Пользователь отправил `/start`** — явное начало новой сессии.
   - Если в Redis есть старый `session_id` → опубликовать `mirror.dialog.session.closed` со старым `session_id`, затем создать новый.
2. **TTL Redis истёк (48ч без активности)** — пассивное закрытие, система об этом не узнает до следующего сообщения.
   - При следующем сообщении пользователя: ключ в Redis отсутствует → создать новый `session_id`. Старая сессия закрылась молча — для суммаризации памяти это нормально.

**Вывод для Stage 1:** публикуем `mirror.dialog.session.closed` только при `/start` с предыдущей сессией. Keyspace notifications Redis — не используем (лишняя сложность).

```python
async def _get_or_create_session(self, global_user_id: UUID, is_new_start: bool = False) -> str:
    key = f"session:{global_user_id}"
    existing = await redis.get(key)
    if existing and is_new_start:
        old_data = json.loads(existing)
        await publish_session_closed(str(global_user_id), old_data["session_id"])
    if not existing or is_new_start:
        session_id = str(uuid4())
        await redis.set(key, json.dumps({"session_id": session_id, "created_at": datetime.utcnow().isoformat()}), ex=172800)
        return session_id
    return json.loads(existing)["session_id"]
```

---

## Верификация webhook Telegram

```python
# mirror/channels/telegram/webhook.py

@router.post("/webhook/telegram/{secret}")
async def telegram_webhook(
    secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None),
):
    # Telegram отправляет secret token в заголовке X-Telegram-Bot-Api-Secret-Token
    # (установлен через bot.set_webhook(..., secret_token=SECRET))
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret.get_secret_value():
        raise HTTPException(status_code=403)
    update = await request.json()
    await dp.process_update(Update(**update))
    return {"ok": True}
```

---

## Команды Этапа 1

```python
COMMANDS = {
    "/start":  "Начать",
    "/help":   "Что я умею",
    "/quiet":  "Не писать первой",
    "/active": "Писать активнее",
}
```

---

## Обработка ошибок

| Исключение | Ответ пользователю |
|-----------|-------------------|
| `AllModelsUnavailableError` | «Сейчас немного занята, вернусь через минуту ✨» |
| `QuotaExceededError` | «Достигла дневного лимита. Приходи завтра 💫» |
| `TelegramAPIError` | Не отвечаем (TG сделает retry) |
| `Exception` | «Что-то пошло не так, попробуй ещё раз 🙏» |

---

## Hard Constraints

- Webhook режим (не long polling) — §12.1
- Верификация: `X-Telegram-Bot-Api-Secret-Token` header == `settings.telegram_webhook_secret` — §13.1
  - НЕ HMAC-SHA256. Telegram использует простое сравнение секретного токена в заголовке.
- FSM state в Redis (RedisStorage aiogram) — §12.7
- Бизнес-логика не импортирует aiogram — §12.8
- Логи: только `user_id`, `session_id`, `intent`, длина текста — без текста сообщений
- `dialog_service.handle()` — метод называется именно так (не `.process()`)

---

## DoD

- `pytest tests/telegram/` зелёный (unit-тесты адаптера с mock aiogram)
- Webhook принимает тестовый update и возвращает 200 OK
- Подпись с неверным secret → 403
