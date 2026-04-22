# LLM Routing — архитектура и план развития

## Текущее состояние (Этап 1)

Таблица `llm_routing` хранит маппинг `task_kind × tier → provider + model`.

Сейчас все строки имеют `tier = *` (wildcard) — одна модель для всех тарифов.

**Канонические task_kind:**

| task_kind | Назначение |
|---|---|
| `main_chat` | Основной чат (free/basic) |
| `main_chat_premium` | Основной чат (plus/pro) |
| `intent_classify` | Классификация намерения пользователя |
| `crisis_classify` | Кризисный детектор (всегда лучшая модель) |
| `memory_summarize` | Сжатие эпизодов памяти |
| `memory_extract_facts` | Извлечение фактов из диалога |
| `tarot_interpret` | Интерпретация расклада таро |
| `astro_interpret` | Интерпретация астрологии |
| `game_narration` | Нарратив игровых механик |
| `proactive_compose` | Проактивные сообщения |
| `persona_evolve` | Эволюция персоны компаньона |
| `embedding` | Эмбеддинг для Qdrant (OpenAI text-embedding-3-large) |

## Этап 2 — Per-tier роутинг

### Концепция

Для каждого `task_kind` добавить строки по тарифам вместо одного wildcard `*`:

```
main_chat / free  → openai / gpt-4o-mini
main_chat / basic → openai / gpt-4o-mini
main_chat / plus  → openai / gpt-4o
main_chat / pro   → anthropic / claude-opus-4-7
```

Логика в `LLMRouter._get_routing()` уже поддерживает это — сначала ищет точное совпадение `(task_kind, tier)`, затем fallback на `(task_kind, *)`.

### UI изменения (admin panel)

Страница LLM Routing получает **вкладки по тарифам**: `free | basic | plus | pro`.

- Переключение таба показывает роутинг для конкретного тарифа
- Если для тарифа нет отдельной строки — показывает унаследованный `*` с пометкой "наследует от wildcard"
- Кнопка "Добавить override для тарифа" создаёт новую строку

### Миграция данных

При переходе на per-tier: существующие строки `tier=*` остаются как fallback, новые строки добавляются только для тарифов где нужно отличие от дефолта.

### Принцип дифференциации по тарифам

- **free/basic** — быстрые/дешёвые модели (gpt-4o-mini, claude-haiku)
- **plus** — сбалансированные (gpt-4o, claude-sonnet)
- **pro** — лучшие (gpt-4o, claude-opus) + больший max_tokens
- **crisis_classify** — всегда лучшая модель независимо от тарифа
