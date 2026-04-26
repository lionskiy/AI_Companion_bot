# Module 04: Policy & Safety — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §3.8–3.9, §12.8, §13.1  
**Зависимости:** Module 05 (LLM Router — нужен для crisis_classify)  
**Дата:** 2026-04-20

---

## Цель

Обязательный контур безопасности. Каждое сообщение пользователя проходит через Policy Engine ДО генерации ответа. Контур нельзя обойти или отключить.

---

## Acceptance Criteria

- [ ] `PolicyEngine.check(user_id, text)` выполняется на каждом шаге диалога
- [ ] Возвращает `PolicyResult` с `risk_level`, `sales_allowed`, `blocked`
- [ ] При `risk_level="crisis"`: ответ из шаблона KB + горячая линия `8-800-2000-122`, `sales_allowed=False`
- [ ] При `risk_level="risk_signal"`: `sales_allowed=False`, обычный диалог
- [ ] При `risk_level="referral_hint"`: мягко предложить живого специалиста
- [ ] `crisis_classify` использует лучшую доступную модель (из LLM Router)
- [ ] Быстрый паттерн-матчинг (словарь) выполняется ДО вызова LLM (< 5ms)
- [ ] Кризисный ответ берётся из KB (не генерируется LLM)
- [ ] После crisis уровня 3-4: NATS event `mirror.safety.crisis_detected`
- [ ] Инцидент логируется в `safety_log` (append-only, без текста сообщения)
- [ ] Тест: сообщение с суицидальными паттернами → `risk_level="crisis"`

---

## Out of Scope

- Moderation API OpenAI (добавить в Этапе 2 как второй контур)
- Adult Mode Policy (Этап 3)
- Автоматическая эскалация модератору (Этап 2)
- `partner_recommendations` Policy (Этап 2)

---

## PolicyResult

```python
# mirror/core/policy/models.py

class RiskLevel(str, Enum):
    WELLBEING = "wellbeing"
    RISK_SIGNAL = "risk_signal"
    REFERRAL_HINT = "referral_hint"
    CRISIS = "crisis"

@dataclass
class PolicyResult:
    risk_level:      RiskLevel
    sales_allowed:   bool
    blocked:         bool          # True = не передавать в Dialog, вернуть crisis_response
    crisis_response: str | None    # готовый текст если blocked=True
    referral_hint:   str | None    # мягкий текст предложения специалиста (только для referral_hint уровня)
    # follow_up_scheduled удалён — не используется в Stage 1
```

### Поведение по risk_level

| risk_level | blocked | sales_allowed | Действие |
|---|---|---|---|
| `wellbeing` | False | True | Обычный диалог |
| `referral_hint` | False | False | Добавить `referral_hint` текст в конец ответа LLM |
| `risk_signal` | False | False | Обычный диалог без офферов |
| `crisis` | True | False | Вернуть crisis_response немедленно + NATS event |

В `generate_response_node` (Module 06):
```python
if state["risk_level"] == "referral_hint" and state.get("crisis_response"):
    response += f"\n\n{state['crisis_response']}"  # crisis_response хранит referral_hint текст
```

---

## Публичный контракт `PolicyEngine`

```python
# mirror/core/policy/safety.py  ← НЕ ИЗМЕНЯТЬ без явного ТЗ

class PolicyEngine:
    async def check(self, user_id: UUID, text: str) -> PolicyResult:
        """
        1. Быстрый паттерн-матчинг (словарь)
        2. Если паттерн найден → LLM crisis_classify для подтверждения
        3. Вернуть PolicyResult
        """

    def _fast_pattern_match(self, text: str) -> RiskLevel | None:
        """Словарный матч. Не вызывает LLM. < 5ms."""

    async def _llm_classify(self, text: str) -> RiskLevel:
        """LLM классификация. task_kind="crisis_classify"."""
```

---

## Схема БД

```sql
-- app_config: конфигурация приложения, редактируется через Admin без деплоя
CREATE TABLE app_config (
    key         text PRIMARY KEY,
    value       text NOT NULL,
    description text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- safety_log: append-only лог инцидентов
CREATE TABLE safety_log (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    uuid NOT NULL,
    session_id uuid,
    risk_level text NOT NULL,
    action     text NOT NULL,  -- "crisis_response_sent", "sales_blocked", etc.
    created_at timestamptz NOT NULL DEFAULT now()
    -- НЕТ текста сообщения (152-ФЗ + минимизация ПДн)
);
CREATE INDEX idx_safety_log_user ON safety_log(user_id, created_at DESC);
-- append-only: никогда DELETE/UPDATE
```

---

## Кризисный шаблон

```python
CRISIS_RESPONSE_TEMPLATE = """
Я здесь, и я слышу тебя. То, что ты чувствуешь — важно.

Пожалуйста, позвони на бесплатную линию психологической помощи:
📞 8-800-2000-122 (бесплатно, круглосуточно)

Напиши мне, когда будешь готов. Я никуда не ухожу.
"""
```

Шаблон хранится в БД (`app_config` таблица) — изменяется через Admin без деплоя.

---

## Быстрые паттерны (seeds для словаря)

```python
# mirror/core/policy/patterns.py
# Структура: список (regex_pattern, initial_risk_level).
# _fast_pattern_match возвращает highest initial_risk_level среди совпавших паттернов.
# LLM затем подтверждает/уточняет уровень.

import re

CRISIS_PATTERNS: list[tuple[str, str]] = [
    # (regex, initial_risk_level)
    # CRISIS — суицидальные/самоповреждение
    (r"не хочу (больше )?жить", "crisis"),
    (r"хочу умереть", "crisis"),
    (r"покончить с (собой|жизнью)", "crisis"),
    (r"суицид", "crisis"),
    (r"kill myself", "crisis"),
    (r"want to die", "crisis"),
    (r"порезать себя", "crisis"),
    (r"прощайте все", "crisis"),
    # RISK_SIGNAL — выраженный дистресс
    (r"всё бессмысленно", "risk_signal"),
    (r"нет смысла (жить|в жизни)", "risk_signal"),
    (r"никому не нужен", "risk_signal"),
    (r"больше не могу", "risk_signal"),
    # REFERRAL_HINT — запрос на профессиональную помощь
    (r"нужен (психолог|психотерапевт|специалист)", "referral_hint"),
    (r"хочу к (психологу|терапевту)", "referral_hint"),
]

def _fast_pattern_match(text: str) -> str | None:
    """Вернуть наивысший risk_level из совпавших паттернов. None если ничего."""
    text_lower = text.lower()
    found_levels = []
    for pattern, level in CRISIS_PATTERNS:
        if re.search(pattern, text_lower):
            found_levels.append(level)
    if not found_levels:
        return None
    # Приоритет: crisis > risk_signal > referral_hint
    priority = {"crisis": 3, "risk_signal": 2, "referral_hint": 1}
    return max(found_levels, key=lambda l: priority.get(l, 0))
```

---

## Интеграция в Dialog (LangGraph)

```python
# В DialogState обязательные поля:
class DialogState(TypedDict):
    ...
    risk_level:    str       # из PolicyResult
    sales_allowed: bool      # из PolicyResult
    blocked:       bool      # если True → пропустить generate_response

# Узел графа (выполняется ПОСЛЕ intent, ДО generate_response):
async def check_policy_node(state: DialogState) -> DialogState:
    result = await policy_engine.check(state["user_id"], state["message"])
    state["risk_level"] = result.risk_level
    state["sales_allowed"] = result.sales_allowed
    state["blocked"] = result.blocked
    if result.blocked:
        state["response"] = result.crisis_response
    return state
```

---

## Hard Constraints

- Policy-контур НЕЛЬЗЯ обойти — §3.8
- `crisis_classify` всегда на лучшей модели из Router
- `sales_allowed=False` при `risk_signal` и `crisis` — не генерировать офферы
- `safety_log` — append-only, без текста сообщений
- Кризисный ответ берётся из KB/шаблона, НЕ генерируется LLM

---

## DoD

- `pytest tests/policy/` зелёный включая тест кризисного сценария
- `policy_engine.check(user_id, "не хочу жить")` → `risk_level=crisis`, `blocked=True`
- `safety_log` не содержит текст сообщений (проверить в тесте)
