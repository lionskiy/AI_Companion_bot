# Module 14: Сонник — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §3.4  
**Зависимости:** 03-memory, 07-astrology, 12-kb_ingest_v2, 16-psychology_journal  
**Дата:** 2026-04-26

---

## Цель

Добавить режим интерпретации снов. Пользователь описывает сон — бот интерпретирует символы с учётом лунного дня, астрологических транзитов, эмоционального контекста и личной истории. Сны сохраняются в дневнике, паттерны повторяющихся образов отслеживаются.

---

## Acceptance Criteria

- [ ] Intent Router распознаёт намерение «рассказать сон» и маршрутизирует в `DreamsService`
- [ ] Сервис извлекает символы сна через LLM (task_kind=`dream_extract_symbols`)
- [ ] RAG поиск по коллекции `knowledge_dreams` возвращает толкования символов (top-3 на символ)
- [ ] Интерпретация учитывает: лунный день, текущие транзиты (интеграция с AstrologyService), эмоцию сна
- [ ] Сон сохраняется в `memory_episodes` с `source_mode='dream'`
- [ ] Факты из снов (повторяющиеся образы, темы) сохраняются в `memory_facts` с `fact_type='dream_pattern'`
- [ ] При 3+ повторениях одного образа — бот уведомляет об этом паттерне
- [ ] База символов: минимум **300 символов** в `knowledge_dreams` при запуске (загружается через KB ingest)
- [ ] Команда `/dream` или фраза «расскажу сон» запускает режим
- [ ] Работает без даты рождения (лунный контекст — без транзитов); с датой рождения — полный контекст
- [ ] Policy §3.8 применяется **до** интерпретации: тревожные/кризисные темы в снах перехватываются PolicyEngine

---

## Архитектура

### Компоненты DreamsService

```python
class DreamsService:
    def __init__(self, llm_router, memory_service, astrology_service) -> None: ...

    async def handle(self, state: DialogState) -> str:
        """
        Основной обработчик. Вызывается из generate_response_node в dialog_graph.py.
        1. Проверяет policy (кризисный перехват до сохранения)
        2. Извлекает символы
        3. Получает moon_context + transit_context
        4. RAG поиск по knowledge_dreams
        5. LLM interpret
        6. Async: save_dream + check_patterns
        """

    async def extract_symbols(self, dream_text: str) -> list[str]:
        """
        LLM (task_kind='dream_extract_symbols') возвращает JSON-список символов.
        Нормализация: lowercase → strip → pymorphy2 lemmatize.
        При ошибке парсинга JSON: логировать, вернуть [] (не бросать).
        Максимум 20 символов на сон (ограничение в промпте LLM).
        """

    def get_moon_context(self, target_date: date) -> dict:
        """Синхронный. Использует ephem, без внешних API. Никогда не бросает."""

    async def search_dream_kb(
        self, symbols: list[str], top_k_per_symbol: int = 3
    ) -> list[dict]:
        """
        Embed каждый символ → Qdrant search knowledge_dreams.
        Возвращает list[{"symbol": str, "interpretation": str, "lunar_context": str}].
        Символы не найденные в KB — пропускаются (не вызывают ошибку).
        """

    async def save_dream(
        self,
        user_id: UUID,
        dream_text: str,
        symbols: list[str],
        interpretation: str,
        moon_context: dict,
    ) -> None:
        """Сохраняет в memory_episodes (source_mode='dream')."""

    async def check_patterns(
        self, user_id: UUID, symbols: list[str]
    ) -> list[str]:
        """
        Ищет повторяющиеся образы в memory_facts (fact_type='dream_pattern').
        Возвращает список символов с count >= 3.
        При 3+ повторениях — обновляет факт (incrememts count), не создаёт дубль.
        """
```

### Лунный контекст — источник данных

Используем библиотеку **`ephem`** (уже в стеке для астрологии). Не внешний API.

```python
import ephem
from datetime import date, timedelta

def get_moon_context(target_date: date) -> dict:
    try:
        moon = ephem.Moon(target_date.isoformat())
        prev_new = ephem.previous_new_moon(target_date.isoformat())
        lunar_day = int((target_date - prev_new.datetime().date()).days) + 1
        lunar_day = max(1, min(lunar_day, 30))  # clamp 1-30
        phase_pct = float(moon.phase)
        return {
            "lunar_day": lunar_day,
            "phase_pct": round(phase_pct),
            "phase_name": _phase_name(phase_pct),
        }
    except Exception:
        return {"lunar_day": None, "phase_pct": None, "phase_name": "неизвестно"}

def _phase_name(pct: float) -> str:
    if pct < 7:   return "новолуние"
    if pct < 45:  return "растущая луна"
    if pct < 55:  return "полнолуние"
    return "убывающая луна"
```

### Policy §3.8 — точка интеграции

```python
async def handle(self, state: DialogState) -> str:
    uid = UUID(state["user_id"])
    # Проверка policy ДО обработки — кризисные сны перехватываем сразу
    policy_result = await policy_engine.check(uid, state["message"])
    if policy_result.blocked or policy_result.risk_level == "crisis":
        logger.info("dreams.crisis_intercepted", user_id=str(uid))
        return policy_result.crisis_response

    symbols = await self.extract_symbols(state["message"])
    moon_ctx = self.get_moon_context(date.today())
    kb_results = await self.search_dream_kb(symbols)
    patterns = await self.check_patterns(uid, symbols)

    # Собираем контекст для LLM
    interpretation = await self._llm_interpret(state, symbols, moon_ctx, kb_results, patterns)

    # Async сохранение (не блокирует ответ)
    asyncio.create_task(self.save_dream(uid, state["message"], symbols, interpretation, moon_ctx))

    pattern_msg = ""
    if patterns:
        pattern_msg = f"\n\n💭 Замечаю повторяющийся образ: {', '.join(patterns)}. Хочешь разберём?"

    return interpretation + pattern_msg
```

### RAG pipeline для снов

```
dream_text
    ↓ extract_symbols (LLM: dream_extract_symbols)
    → ["вода", "полёт", "дом", ...]  (max 20 символов)
    ↓ embed каждый символ (параллельно через asyncio.gather)
    → Qdrant search: knowledge_dreams (top-3 per symbol, filter: collection)
    + moon_context (лунный день, фаза)
    + transit_context (из AstrologyService если есть натальная карта)
    + user dream_pattern facts (из memory_facts, fact_type='dream_pattern')
    ↓ LLM interpret (task_kind=dream_interpret)
    → ответ пользователю
    ↓ asyncio.create_task: save_dream + check_patterns (не блокирует)
```

### Интеграция в dialog_graph.py

```python
# В generate_response_node:
elif intent == "dream" and dreams_service is not None:
    response = await dreams_service.handle(state)
```

`DreamsService` передаётся в `build_dialog_graph()` как опциональный параметр `dreams_service=None`.

### Команда /dream

Добавить в `telegram/handlers.py`:
```python
@router.message(Command("dream"))
async def handle_dream(message: Message, bot: Bot) -> None:
    unified = await adapter.to_unified(message)
    unified.text = message.text or "/dream"
    async with typing_action(bot, message.chat.id):
        response = await dialog_service.handle(unified)
    await adapter.send(response, bot)
```

---

## Схема БД

Отдельных таблиц не нужно — используются существующие:
- `memory_episodes` с `source_mode='dream'` — хранит текст сна + интерпретацию
- `memory_facts` с `fact_type='dream_pattern'` — хранит повторяющиеся образы

`source_mode` CHECK constraint добавляется в **миграции 020** (см. stage2_overview_spec.md).

Структура факта паттерна:
```python
# fact_type='dream_pattern'
# key = нормализованный символ (лемматизированный), например: "вода"
# value = JSON: {"count": 3, "last_seen": "2026-04-25", "notes": "часто появляется в тревожных снах"}
```

---

## Qdrant коллекция

| Коллекция | Размерность | Метрика | Описание |
|-----------|-------------|---------|---------|
| `knowledge_dreams` | 3072 (text-embedding-3-large) | Cosine | Символы снов с толкованиями |

Создаётся в `mirror/core/memory/qdrant_init.py` (добавить в `COLLECTIONS`).

Формат документа для ingest:
```json
{
  "symbol": "вода",
  "category": "природные стихии",
  "meanings": ["эмоции", "подсознание", "изменения"],
  "interpretation": "Вода во сне символизирует...",
  "lunar_context": "Особенно значимо в полнолуние...",
  "jungian_layer": "Архетип..."
}
```

Материалы: `resourses/knowledge_dreams/` — минимум 300 документов. Загрузка через `mirror/workers/tasks/ingest.py` (KB ingest модуль 12).

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `dream_extract_symbols` | main_chat | Извлечение символов из описания сна (JSON-список) |
| `dream_interpret` | main_chat | Интерпретация сна с moon/transit/KB контекстом |

Примечание: `dream_interpret` сейчас роутируется в `main_chat` (Free tier). При включении монетизации (этап 3) — перевести в `main_chat_premium`.

---

## Файлы к созданию / изменению

| Файл | Действие |
|------|---------|
| `mirror/services/dreams.py` | Создать — DreamsService |
| `mirror/rag/dreams.py` | Создать — search_dream_knowledge |
| `mirror/services/intent_router.py` | Изменить — добавить intent `dream` с примерами фраз |
| `mirror/services/dialog_graph.py` | Изменить — routing на DreamsService, параметр dreams_service |
| `mirror/channels/telegram/handlers.py` | Изменить — добавить `/dream` command handler |
| `mirror/core/memory/qdrant_init.py` | Изменить — добавить knowledge_dreams |
| `mirror/db/seeds/llm_routing_stage2.py` | Дополнить — новые task_kinds |
| `resourses/knowledge_dreams/` | Создать — материалы для ingest |

---

## Definition of Done

- [ ] Smoke-тест: пользователь описывает сон → получает интерпретацию с символами и лунным контекстом
- [ ] Smoke-тест: сон сохраняется в memory_episodes с source_mode='dream'
- [ ] Smoke-тест: 3 сообщения с символом «вода» → бот замечает паттерн и уведомляет
- [ ] Smoke-тест: кризисный сон (суицидальная тема) → policy перехватывает, интерпретация не даётся
- [ ] Коллекция knowledge_dreams создана в Qdrant и заполнена (минимум 300 символов)
- [ ] Команда /dream работает независимо от фразы в тексте
- [ ] Логирование: `dreams.handle`, `dreams.symbols_extracted`, `dreams.pattern_detected`
