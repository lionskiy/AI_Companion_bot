# Module 05: LLM Router — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §12.6, §14.1.1  
**Зависимости:** Module 01 (Identity — нужна таблица users.subscription)  
**Дата:** 2026-04-20

---

## Цель

Единая точка вызова LLM. Любой вызов языковой модели — только через `LLMRouter.call(task_kind, ...)`. Router читает конфигурацию из БД, применяет retry + fallback, изолирует от деталей провайдеров.

---

## Acceptance Criteria

- [ ] `LLMRouter.call(task_kind, tier, messages)` → `str`
- [ ] `LLMRouter.embed(text)` → `list[float]` (task_kind="embedding")
- [ ] Конфиг роутинга берётся из таблицы `llm_routing` (не хардкодится)
- [ ] 3 retry с интервалом 2с на каждую модель
- [ ] При исчерпании retry → следующая модель в `fallback_chain`
- [ ] Если все модели недоступны → `AllModelsUnavailableError`
- [ ] Пользователь не видит имя модели/провайдера
- [ ] task_kind без записи в `llm_routing` → `ValueError` при старте
- [ ] Seed данные для `llm_routing` заполняют все канонические task_kinds
- [ ] `LLMRouter` не хардкодит модели — только читает из БД
- [ ] Логируется: `task_kind`, `tier`, `latency_ms`, `provider`, `attempt` — без текста промптов

---

## Out of Scope

- Circuit breaker (Этап 2)
- Canary / shadow eval (Этап 2)
- Streaming ответов (Этап 2)
- vision, stt task_kinds (Этап 5)

---

## Схема БД

```sql
CREATE TABLE llm_providers (
    provider_id  text PRIMARY KEY,  -- "openai", "anthropic"
    base_url     text,
    api_key_env  text NOT NULL,     -- имя env-переменной с ключом
    is_active    boolean NOT NULL DEFAULT true
);

CREATE TABLE llm_routing (
    task_kind       text NOT NULL,
    tier            text NOT NULL DEFAULT '*',  -- "free","basic","plus","pro","*"
    provider_id     text NOT NULL REFERENCES llm_providers(provider_id),
    model_id        text NOT NULL,              -- "gpt-4o-mini", "claude-haiku-4-5-20251001"
    fallback_chain  jsonb NOT NULL DEFAULT '[]', -- [{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]
    max_tokens      int NOT NULL DEFAULT 1000,
    temperature     numeric(3,2) NOT NULL DEFAULT 0.7,
    PRIMARY KEY (task_kind, tier)
);
```

### Seed данные (канонические task_kinds)

```sql
-- Providers
INSERT INTO llm_providers VALUES ('openai', NULL, 'OPENAI_API_KEY', true);
INSERT INTO llm_providers VALUES ('anthropic', NULL, 'ANTHROPIC_API_KEY', true);

-- Routing (tier='*' применяется если нет специфичной строки для тарифа)
INSERT INTO llm_routing (task_kind, tier, provider_id, model_id, fallback_chain) VALUES
  ('main_chat',            '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('main_chat_premium',    '*',    'openai',    'gpt-4o',                   '[{"provider_id":"anthropic","model_id":"claude-sonnet-4-6"}]'),
  ('intent_classify',      '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('crisis_classify',      '*',    'anthropic', 'claude-sonnet-4-6',        '[{"provider_id":"openai","model_id":"gpt-4o"}]'),
  ('memory_summarize',     '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('memory_extract_facts', '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('tarot_interpret',      '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('astro_interpret',      '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('game_narration',       '*',    'openai',    'gpt-4o',                   '[{"provider_id":"anthropic","model_id":"claude-sonnet-4-6"}]'),
  ('proactive_compose',    '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('persona_evolve',       '*',    'openai',    'gpt-4o-mini',              '[{"provider_id":"anthropic","model_id":"claude-haiku-4-5-20251001"}]'),
  ('embedding',            '*',    'openai',    'text-embedding-3-large',   '[]');
```

> Примечание: `crisis_classify` использует Claude Sonnet как primary (надёжность важнее стоимости).

---

## Публичный контракт `LLMRouter`

```python
# mirror/core/llm/router.py  ← НЕ ИЗМЕНЯТЬ без явного ТЗ

class LLMRouter:
    async def call(
        self,
        task_kind: str,
        messages: list[dict],
        tier: str = "free",
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict | None = None,  # {"type": "json_object"}
    ) -> str:
        """
        Вызвать LLM по task_kind. Retry 3x → fallback chain → AllModelsUnavailableError.
        Никогда не раскрывает имя провайдера/модели в исключениях.
        """

    async def embed(self, text: str) -> list[float]:
        """Получить эмбеддинг. task_kind="embedding"."""
```

---

## Retry + Fallback pattern

```python
async def call(self, task_kind, messages, tier="free", ...):
    routing = await self._get_routing(task_kind, tier)
    models_to_try = [
        (routing.provider_id, routing.model_id)
    ] + [(f["provider_id"], f["model_id"]) for f in routing.fallback_chain]

    for provider_id, model_id in models_to_try:
        for attempt in range(3):
            try:
                return await self._call_provider(provider_id, model_id, messages, ...)
            except (RateLimitError, APITimeoutError):
                if attempt < 2:
                    await asyncio.sleep(2.0)
                    continue
                break
            except APIError:
                break

    raise AllModelsUnavailableError()
```

---

## `_call_provider` — реализация для OpenAI и Anthropic

```python
async def _call_provider(
    self,
    provider_id: str,
    model_id: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    response_format: dict | None,
) -> str:
    api_key = os.environ[self._get_api_key_env(provider_id)]

    if provider_id == "openai":
        client = AsyncOpenAI(api_key=api_key)
        kwargs = dict(model=model_id, messages=messages,
                      max_tokens=max_tokens, temperature=temperature)
        if response_format:
            kwargs["response_format"] = response_format
        resp = await client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

    elif provider_id == "anthropic":
        # Anthropic API: system отдельный параметр, messages без role=system
        client = AsyncAnthropic(api_key=api_key)
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        chat_msgs = [m for m in messages if m["role"] != "system"]
        system_text = "\n\n".join(system_msgs) if system_msgs else None
        kwargs = dict(model=model_id, messages=chat_msgs,
                      max_tokens=max_tokens, temperature=temperature)
        if system_text:
            kwargs["system"] = system_text
        resp = await client.messages.create(**kwargs)
        return resp.content[0].text

    else:
        raise ValueError(f"Unknown provider: {provider_id}")
```

> Клиенты создаются на каждый вызов — они stateless. Для production можно добавить connection pool.

---

## Prompt injection защита

```python
# Правильно — user input всегда в role="user", НЕ интерполируется в system:
messages = [
    {"role": "system", "content": build_system_prompt(profile)},
    *session_history,
    {"role": "user", "content": sanitize_input(user_text)},
]

def sanitize_input(text: str) -> str:
    return text[:4000].strip()
```

---

## Кэширование routing config

Routing config читается из БД при первом обращении к каждому `(task_kind, tier)` и кэшируется in-process (`dict`). После изменения через Admin API кэш должен инвалидироваться:

```python
class LLMRouter:
    _routing_cache: dict[tuple[str, str], LLMRouting] = {}

    async def _get_routing(self, task_kind: str, tier: str) -> LLMRouting:
        key = (task_kind, tier)
        if key not in self._routing_cache:
            row = await self._fetch_routing(task_kind, tier)
            if row is None:
                raise ValueError(f"No routing for task_kind={task_kind!r} tier={tier!r}")
            self._routing_cache[key] = row
        return self._routing_cache[key]

    def invalidate_cache(self) -> None:
        """Вызывается из Admin API после PUT /admin/llm-routing/{task_kind}/{tier}."""
        self._routing_cache.clear()
```

Admin API (`PUT /admin/llm-routing/...`) должен вызывать `llm_router.invalidate_cache()` после обновления БД.

---

## Hard Constraints

- Роутинг только из БД — не хардкодить модели в коде (§12.6)
- Тариф/лимиты берутся из БД, не из ответа LLM — §13.1
- При ошибке: сообщение «технические работы» без деталей провайдера — §1.8.1
- `crisis_classify` — всегда лучшая модель (Sonnet primary, GPT-4o fallback)
- Логировать без текста промптов: только task_kind, latency, attempt, provider

---

## DoD

- Seed данные для всех 12 task_kinds в БД
- Retry тест: при ошибке primary → переход на fallback
- `pytest tests/llm/` зелёный
- Приложение не стартует если хотя бы один canonical task_kind не покрыт в routing
