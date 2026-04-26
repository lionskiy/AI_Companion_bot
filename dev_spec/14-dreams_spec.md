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
- [ ] RAG поиск по коллекции `knowledge_dreams` возвращает толкования символов
- [ ] Интерпретация учитывает: лунный день, текущие транзиты (интеграция с AstrologyService), эмоцию сна
- [ ] Сон сохраняется в `memory_episodes` с `source_mode='dream'`
- [ ] Факты из снов (повторяющиеся образы, темы) сохраняются в `memory_facts` с `fact_type='dream_pattern'`
- [ ] При 3+ повторениях одного образа — бот уведомляет об этом паттерне
- [ ] База символов: минимум **300 символов** в `knowledge_dreams` при запуске (загружается через KB ingest)
- [ ] Команда `/dream` или фраза «расскажу сон» запускает режим
- [ ] Работает без даты рождения (лунный контекст — без транзитов); с датой рождения — полный контекст
- [ ] Policy §3.8 применяется: тревожные/кризисные сны обрабатываются корректно

---

## Архитектура

### Лунный контекст — источник данных

Используем библиотеку **`ephem`** (уже в стеке для астрологии) или **`kerykeion`**. Не внешний API.

```python
import ephem

def get_moon_context(target_date: date) -> dict:
    moon = ephem.Moon(target_date.isoformat())
    # Лунный день: 1-30, считается от новолуния
    new_moon = ephem.next_new_moon(target_date - timedelta(days=30))
    lunar_day = int((target_date - new_moon.datetime().date()).days) + 1
    phase_pct = moon.phase  # 0-100, процент освещённости
    return {
        "lunar_day": lunar_day,
        "phase_pct": round(phase_pct),
        "phase_name": _phase_name(phase_pct),  # новолуние/растущая/полнолуние/убывающая
    }
```

### Символы — извлечение и дедупликация

LLM возвращает JSON-список: `["вода", "дом", "полёт"]`  
Нормализация: lowercase + strip + лемматизация (через pymorphy2 для русского).  
Паттерны: в `memory_facts` хранятся лемматизированные формы — сравнение идёт по нормализованному ключу.

### Компоненты

```
DreamsService
├── handle(state: DialogState) → str          # основной обработчик
├── extract_symbols(dream_text) → list[str]   # LLM extraction → JSON list → нормализация
├── get_moon_context(date) → dict             # ephem, без внешних API
├── search_dream_kb(symbols) → list[str]      # RAG по knowledge_dreams (embed каждый символ, batch)
├── save_dream(user_id, text, symbols, context) → None  # → memory_episodes, source_mode='dream'
└── check_patterns(user_id, symbols) → list[str]  # поиск по memory_facts fact_type='dream_pattern'
```

### RAG pipeline для снов

```
dream_text
    ↓ extract_symbols (LLM)
    → ["вода", "полёт", "дом", ...]
    ↓ embed каждый символ
    → Qdrant search: knowledge_dreams (top-3 per symbol)
    + moon_context (лунный день, фаза)
    + transit_context (если есть натальная карта)
    + user dream_pattern facts (из memory_facts)
    ↓ LLM interpret (task_kind=dream_interpret)
    → ответ пользователю
    ↓ async: save_dream + check_patterns
```

### Intent Router — новые интенты

Добавить в `IntentRouter`:
- `dream` — пользователь рассказывает сон или просит толковать сон

---

## Схема БД

Отдельных таблиц не нужно — используются существующие:
- `memory_episodes` с `source_mode='dream'` — хранит текст сна + интерпретацию
- `memory_facts` с `fact_type='dream_pattern'` — хранит повторяющиеся образы

```sql
-- Миграция не требует новых таблиц.
-- Проверить что source_mode VARCHAR достаточно длинный (есть в migration 002).
-- Добавить 'dream' в enum/check если используется.
```

---

## Qdrant коллекция

| Коллекция | Размерность | Описание |
|-----------|-------------|---------|
| `knowledge_dreams` | 3072 (text-embedding-3-large) | Символы снов с толкованиями |

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

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `dream_extract_symbols` | main_chat | Извлечение символов из описания сна |
| `dream_interpret` | main_chat_premium | Интерпретация сна с контекстом |

---

## Файлы к созданию / изменению

- `mirror/services/dreams.py` — DreamsService (новый)
- `mirror/rag/dreams.py` — search_dream_knowledge (новый, по аналогии с rag/psych.py)
- `mirror/services/intent_router.py` — добавить intent `dream`
- `mirror/services/dialog_graph.py` — routing на DreamsService
- `mirror/db/seeds/llm_routing_stage2.py` — новые task_kinds
- `resourses/knowledge_dreams/` — папка с материалами для ingest (создать)

---

## Definition of Done

- [ ] Smoke-тест: пользователь описывает сон → получает интерпретацию с символами
- [ ] Smoke-тест: сон сохраняется в memory_episodes с source_mode='dream'
- [ ] Smoke-тест: 3 сообщения с символом «вода» → бот замечает паттерн
- [ ] Коллекция knowledge_dreams создана в Qdrant и заполнена (минимум 300 символов)
- [ ] Логирование: `dreams.handle`, `dreams.symbols_extracted`, `dreams.pattern_detected`
