# Module 06: Dialog Service — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §4, §5, §12.3  
**Зависимости:** Module 01 (Identity), Module 02 (Telegram Adapter), Module 03 (Memory), Module 04 (Policy), Module 05 (LLM Router)  
**Дата:** 2026-04-20

---

## Цель

Центральный оркестратор диалога. Принимает `UnifiedMessage`, запускает LangGraph граф, возвращает `UnifiedResponse`. Изолирует бизнес-логику от деталей каналов. Обязательно проходит через Policy Engine перед генерацией ответа.

---

## Acceptance Criteria

- [ ] `DialogService.handle(msg: UnifiedMessage) → UnifiedResponse`
- [ ] LangGraph граф с узлами: `classify_intent → check_policy → route_mode → generate_response`
- [ ] `IntentRouter.classify(text)` → `IntentResult` (task_kind="intent_classify")
- [ ] Policy node выполняется ДО `generate_response`, не после
- [ ] Если `DialogState.blocked=True` → вернуть `crisis_response` без вызова LLM
- [ ] Режим `astrology` → вызов `AstrologyService.handle()`
- [ ] Режим `tarot` → вызов `TarotService.handle()`
- [ ] Режим `daily_ritual` → вызов `DailyRitualService.handle()`
- [ ] Режим `chat` → основной диалог через LLMRouter (task_kind="main_chat" / "main_chat_premium")
- [ ] Контекст собирается: mem_L1 (сессия) + mem_L2 (эпизоды) + mem_L3 (факты)
- [ ] При завершении сессии: NATS event `mirror.dialog.session.closed`
- [ ] `sales_allowed=False` → не добавлять оффер в ответ
- [ ] Логируется: `user_id`, `intent`, `mode`, `latency_ms` — без текста сообщений

---

## Out of Scope

- Игровой режим (Module Game Engine, Этап 2)
- Proactive messaging (Этап 2)
- Streaming ответов (Этап 2)
- Multi-turn сложные сценарии (онбординг — Этап 2)

---

## DialogState (LangGraph)

```python
# mirror/services/dialog_state.py

class DialogState(TypedDict):
    # Входные данные
    user_id:        str           # UUID строкой
    session_id:     str           # UUID строкой
    message:        str           # текст от пользователя
    tier:           str           # "free", "basic", "plus", "pro"

    # После classify_intent
    intent:         str | None    # "astrology", "tarot", "daily_ritual", "chat", "help", "cancel"
    intent_conf:    float | None  # уверенность 0.0–1.0

    # После check_policy
    risk_level:     str | None
    sales_allowed:  bool
    blocked:        bool
    crisis_response: str | None

    # Контекст памяти (собирается в route_mode)
    session_history: list[dict]   # mem_L1
    memory_context:  dict         # {"episodes": [...], "facts": [...]} из mem_L2+L3

    # После generate_response
    response:       str | None
    mode_used:      str | None    # "astrology", "tarot", "daily_ritual", "chat"
```

---

## LangGraph граф

```python
# mirror/services/dialog_graph.py

from langgraph.graph import StateGraph, END

def build_dialog_graph() -> StateGraph:
    graph = StateGraph(DialogState)

    graph.add_node("classify_intent",  classify_intent_node)
    graph.add_node("check_policy",     check_policy_node)
    graph.add_node("route_mode",       route_mode_node)
    graph.add_node("generate_response", generate_response_node)

    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "check_policy")

    graph.add_conditional_edges(
        "check_policy",
        lambda s: "end" if s["blocked"] else "route_mode",
        {"end": END, "route_mode": "route_mode"},
    )
    graph.add_edge("route_mode", "generate_response")
    graph.add_edge("generate_response", END)

    return graph.compile()
```

---

## Узлы графа

```python
# classify_intent_node
async def classify_intent_node(state: DialogState) -> DialogState:
    result = await intent_router.classify(state["message"])
    state["intent"] = result.intent
    state["intent_conf"] = result.confidence
    return state

# check_policy_node
async def check_policy_node(state: DialogState) -> DialogState:
    result = await policy_engine.check(
        user_id=UUID(state["user_id"]),
        text=state["message"]
    )
    state["risk_level"] = result.risk_level
    state["sales_allowed"] = result.sales_allowed
    state["blocked"] = result.blocked
    if result.blocked:
        state["response"] = result.crisis_response
    return state

# route_mode_node — собирает контекст памяти
async def route_mode_node(state: DialogState) -> DialogState:
    uid = UUID(state["user_id"])
    session_history = await memory_service.get_session_history(uid)
    memory_context = await memory_service.search(uid, state["message"])
    state["session_history"] = session_history
    state["memory_context"] = memory_context
    return state

# generate_response_node
async def generate_response_node(state: DialogState) -> DialogState:
    intent = state["intent"]
    if intent == "astrology":
        response = await astrology_service.handle(state)
    elif intent == "tarot":
        response = await tarot_service.handle(state)
    elif intent == "daily_ritual":
        response = await daily_ritual_service.handle(state)
    elif intent == "help":
        response = HELP_TEXT  # статичный текст, не вызывает LLM
    elif intent == "cancel":
        response = "Хорошо, давай поговорим о чём-нибудь другом."  # статичный
    else:  # "chat" и любой неизвестный intent
        response = await _chat_response(state)
    # Добавить мягкое предложение специалиста если referral_hint
    if state.get("risk_level") == "referral_hint" and state.get("crisis_response"):
        response += f"\n\n{state['crisis_response']}"

    state["response"] = response
    state["mode_used"] = intent
    return state

HELP_TEXT = """Я умею:
🔮 Таро — расклады и интерпретации
⭐ Астрология — натальная карта и транзиты
🌅 Ежедневный ритуал — карта дня и аффирмация
💬 Просто поговорить

Напиши что тебя интересует."""
```

---

## IntentRouter

```python
# mirror/services/intent_router.py

INTENTS = ["astrology", "tarot", "daily_ritual", "chat", "help", "cancel"]

class IntentResult:
    intent:     str
    confidence: float

class IntentRouter:
    async def classify(self, text: str) -> IntentResult:
        """
        task_kind="intent_classify". Возвращает один из INTENTS.
        При низкой уверенности (< 0.5) → "chat".
        """
```

---

## Публичный контракт `DialogService`

```python
# mirror/services/dialog.py  ← НЕ ИЗМЕНЯТЬ без явного ТЗ

class DialogService:
    async def handle(self, msg: UnifiedMessage) -> UnifiedResponse:
        """
        1. Получить tier пользователя из BillingService.get_tier()
        2. Проверить quota через BillingService.check_quota() — до графа
        3. Сформировать initial_state и запустить LangGraph граф
        4. Сохранить сообщение и ответ в mem_L1
        5. Вернуть UnifiedResponse
        """
        tier = await billing_service.get_tier(UUID(msg.global_user_id))
        quota = await billing_service.check_quota(UUID(msg.global_user_id))
        if not quota.allowed:
            return UnifiedResponse(
                text=quota.message or "Дневной лимит исчерпан.",
                chat_id=msg.chat_id,
                channel=msg.channel,
            )

        initial_state: DialogState = {
            "user_id":        msg.global_user_id,
            "session_id":     msg.session_id,
            "message":        msg.text,
            "tier":           tier,
            "intent":         None,
            "intent_conf":    None,
            "risk_level":     None,
            "sales_allowed":  True,   # переопределяется PolicyEngine
            "blocked":        False,  # переопределяется PolicyEngine
            "crisis_response": None,
            "session_history": [],
            "memory_context": {"episodes": [], "facts": []},
            "response":       None,
            "mode_used":      None,
        }
        try:
            final_state = await graph.ainvoke(initial_state)
        except Exception:
            logger.exception("dialog_graph_error", user_id=msg.global_user_id)
            return UnifiedResponse(
                text="Сейчас немного занята, вернусь через минуту ✨",
                chat_id=msg.chat_id,
                channel=msg.channel,
            )

        await memory_service.add_to_session(UUID(msg.global_user_id), "user", msg.text)
        await memory_service.add_to_session(UUID(msg.global_user_id), "assistant", final_state["response"])

        return UnifiedResponse(
            text=final_state["response"],
            chat_id=msg.chat_id,
            channel=msg.channel,
        )
```

---

## `_chat_response` и выбор task_kind

```python
# Маппинг tier → task_kind для основного чата
CHAT_TASK_KIND: dict[str, str] = {
    "free":  "main_chat",
    "basic": "main_chat",
    "plus":  "main_chat_premium",
    "pro":   "main_chat_premium",
}

async def _chat_response(state: DialogState) -> str:
    task_kind = CHAT_TASK_KIND.get(state["tier"], "main_chat")
    messages = build_messages(state)
    return await llm_router.call(
        task_kind=task_kind,
        messages=messages,
        tier=state["tier"],
    )
```

---

## `get_app_config` — загрузка и кэш

```python
# mirror/services/dialog.py

_app_config_cache: dict[str, str] = {}

async def load_app_config_cache(session: AsyncSession) -> None:
    """Вызывается в lifespan после init_db_pool(). Загружает все ключи из app_config."""
    rows = await session.execute(select(AppConfig))
    _app_config_cache.update({row.key: row.value for row in rows.scalars()})

def get_app_config(key: str, default: str = "") -> str:
    """Читает из in-memory кэша. Если ключ отсутствует — возвращает default (не падает)."""
    return _app_config_cache.get(key, default)

def invalidate_app_config_cache() -> None:
    """Вызывается из Admin API после PUT /admin/app-config/{key}."""
    _app_config_cache.clear()
    # После очистки при следующем вызове get_app_config вернёт default.
    # Для немедленного обновления: вызвать load_app_config_cache() в background task.
```

> `invalidate_app_config_cache()` импортируется в `PUT /admin/app-config/{key}` handler.

---

## `build_system_prompt` — структура

```python
# mirror/services/dialog.py

def build_system_prompt(
    facts: list[dict],
    tier: str,
    sales_allowed: bool,
) -> str:
    """
    Собирает system prompt из трёх частей:
    1. Базовый промпт из app_config['system_prompt_base'] (читается из БД при старте)
    2. Факты о пользователе (mem_L3) — форматируются как "Пользователь: {key} = {value}"
    3. Опциональный блок sales если sales_allowed=True и tier!='pro'
    """
    base = get_app_config("system_prompt_base")  # кэшируется при старте
    parts = [base]
    if facts:
        facts_text = "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:20])
        parts.append(f"Что я знаю о тебе:\n{facts_text}")
    if sales_allowed and tier == "free":
        parts.append("Если уместно, можешь мягко упомянуть что есть расширенные возможности.")
    return "\n\n".join(parts)
```

---

## Сборка контекста промпта (mem_L0)

```python
def build_messages(state: DialogState) -> list[dict]:
    system = build_system_prompt(
        facts=state["memory_context"]["facts"],
        tier=state["tier"],
        sales_allowed=state["sales_allowed"],
    )
    history = state["session_history"][-10:]  # последние 10 из mem_L1
    # Эпизоды как дополнительный контекст
    episodes_text = "\n".join(
        ep["summary"] for ep in state["memory_context"]["episodes"]
    )
    if episodes_text:
        history = [{"role": "system", "content": f"Контекст прошлых сессий:\n{episodes_text}"}] + history

    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": sanitize_input(state["message"])},
    ]
```

---

## NATS события

```python
# Публикуется после генерации ответа (закрытие сессии — при TTL истечении)
# mirror/events/publishers/dialog.py

async def publish_session_closed(user_id: str, session_id: str):
    await nats_client.publish(
        "mirror.dialog.session.closed",
        payload={"user_id": user_id, "session_id": session_id},
    )
```

---

## Схема БД

Дополнительных таблиц не создаёт — использует `users`, `subscriptions` (Module 01, 10), `memory_*` (Module 03).

```sql
-- app_config — уже создана в Module 04 (Policy)
-- Добавляем запись для system prompt если не существует:
INSERT INTO app_config (key, value, description) VALUES
  ('system_prompt_base', '...', 'Базовый system prompt для main_chat')
ON CONFLICT (key) DO NOTHING;
```

---

## Hard Constraints

- Policy-узел НЕЛЬЗЯ пропустить — §3.8
- `sales_allowed=False` → не добавлять офферы или упоминания платных тарифов в ответ
- Логи без текстов сообщений пользователя
- `tier` берётся из БД, не из тела запроса
- Все внешние вызовы с timeout (LLM ≤ 30s, Memory ≤ 5s)

---

## DoD

- LangGraph граф: intent → policy → route → generate — все 4 узла работают
- Кризисный сценарий: `blocked=True` → ответ возвращается без generate_response
- `pytest tests/dialog/` зелёный
- Тест: сообщение "покажи мне таро" → `intent="tarot"`
- Тест: сообщение "не хочу жить" → `blocked=True`, ответ = crisis_response
