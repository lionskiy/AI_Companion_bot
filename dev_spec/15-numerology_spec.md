# Module 15: Нумерология — Spec

**Статус:** Ready for development  
**Этап:** 2 · **Ссылка на POD:** §3.5  
**Зависимости:** 01-identity, 07-astrology (паттерн RAG), 12-kb_ingest_v2  
**Дата:** 2026-04-26

---

## Цель

Добавить режим нумерологии. Пользователь получает расчёт числа жизненного пути, числа имени, личного года/месяца/дня с интерпретацией. Расчёты выполняются локально (без LLM), интерпретации берутся из KB через RAG.

---

## Acceptance Criteria

- [ ] Intent Router распознаёт намерение «нумерология» и маршрутизирует в `NumerologyService`
- [ ] Число жизненного пути вычисляется по дате рождения (алгоритм Пифагора — каждая часть сводится отдельно)
- [ ] Число имени вычисляется по имени пользователя (таблица Пифагора, русский + латинский алфавиты)
- [ ] Личный год = `reduce(reduce(day) + reduce(month) + reduce(current_year))`
- [ ] Личный месяц = `reduce(personal_year + reduce(current_month))`
- [ ] Личный день = `reduce(personal_month + reduce(current_day))`
- [ ] Мастер-числа 11, 22, 33 не сводятся дальше (все остальные — до 1-9)
- [ ] RAG поиск по `knowledge_numerology` возвращает интерпретации для каждого числа
- [ ] Если нет даты рождения — бот спрашивает её через OnboardingManager
- [ ] Если нет имени — интерпретируется только по дате рождения (имя опционально)
- [ ] Число жизненного пути сохраняется в `user_profiles.life_path_number`
- [ ] Результат расчёта сохраняется как факт в memory_facts (fact_type='numerology')
- [ ] Команда `/numerology` или фразы «нумерология», «число судьбы», «число жизненного пути» запускают режим

---

## Архитектура

### NumerologyCalculator — алгоритм расчётов

```python
class NumerologyCalculator:
    # Полная таблица русского алфавита (включая ё)
    PYTHAGOREAN_RU = {
        'а':1,'б':2,'в':3,'г':4,'д':5,'е':6,'ё':6,'ж':7,'з':8,'и':9,
        'й':1,'к':2,'л':3,'м':4,'н':5,'о':6,'п':7,'р':8,'с':9,
        'т':1,'у':2,'ф':3,'х':4,'ц':5,'ч':6,'ш':7,'щ':8,'ъ':9,
        'ы':1,'ь':2,'э':3,'ю':4,'я':5,
    }
    # Латинский алфавит (Pythagorean English)
    PYTHAGOREAN_EN = {
        'a':1,'b':2,'c':3,'d':4,'e':5,'f':6,'g':7,'h':8,'i':9,
        'j':1,'k':2,'l':3,'m':4,'n':5,'o':6,'p':7,'q':8,'r':9,
        's':1,'t':2,'u':3,'v':4,'w':5,'x':6,'y':7,'z':8,
    }
    MASTER_NUMBERS = {11, 22, 33}

    def reduce(self, n: int) -> int:
        """Сводит к 1-9 или оставляет мастер-число (11, 22, 33)."""
        while n > 9 and n not in self.MASTER_NUMBERS:
            n = sum(int(d) for d in str(n))
        return n

    def life_path(self, birth_date: date) -> int:
        """
        Стандартный метод Пифагора: каждую часть сводить отдельно, потом суммировать.
        Пример: 15.03.1990
          day=15 → reduce(15)=6, month=3 → 3, year=1990 → 1+9+9+0=19 → 10 → 1
          total=6+3+1=10 → reduce(10)=1
        """
        d = self.reduce(birth_date.day)
        m = self.reduce(birth_date.month)
        y = self.reduce(sum(int(c) for c in str(birth_date.year)))
        return self.reduce(d + m + y)

    def name_number(self, name: str) -> int:
        """
        Суммирует числа всех букв (оба алфавита, case-insensitive).
        Небуквенные символы (пробелы, дефисы) игнорируются.
        Транслитерация не применяется — русские имена считаются по RU-таблице,
        латинские — по EN-таблице.
        """
        table = {**self.PYTHAGOREAN_RU, **self.PYTHAGOREAN_EN}
        total = sum(table.get(c.lower(), 0) for c in name if c.isalpha())
        return self.reduce(total)

    def personal_year(self, birth_date: date, year: int) -> int:
        d = self.reduce(birth_date.day)
        m = self.reduce(birth_date.month)
        y = self.reduce(sum(int(c) for c in str(year)))
        return self.reduce(d + m + y)

    def personal_month(self, birth_date: date, year: int, month: int) -> int:
        return self.reduce(self.personal_year(birth_date, year) + self.reduce(month))

    def personal_day(self, birth_date: date, today: date) -> int:
        pm = self.personal_month(birth_date, today.year, today.month)
        return self.reduce(pm + self.reduce(today.day))
```

Тест-векторы (обязательно проверить):
- `life_path(date(1990, 3, 15))` → `1` (6+3+1=10→1)
- `life_path(date(1985, 11, 29))` → `11` (мастер-число, не сводится: 2+2+7=11)
- `name_number("Анна")` → `1+5+5+1=12 → 3`
- `reduce(22)` → `22` (мастер-число)
- `reduce(33)` → `33` (мастер-число)
- `reduce(44)` → `8` (не мастер-число)

### NumerologyService

```python
class NumerologyService:
    def __init__(self, llm_router, memory_service) -> None: ...

    async def handle(self, state: DialogState) -> str:
        """
        Вызывается из generate_response_node в dialog_graph.py.
        1. Получает дату рождения и имя из user_profiles
        2. Если нет birth_date — возвращает запрос через OnboardingManager
        3. Вычисляет все числа через NumerologyCalculator
        4. RAG поиск интерпретаций по knowledge_numerology
        5. LLM (task_kind='numerology_interpret') собирает связный ответ
        6. Async: сохраняет life_path_number в user_profiles + факт в memory_facts
        """
```

### RAG pipeline

```
запрос пользователя
    ↓ intent = 'numerology'
    → NumerologyService.handle(state)
    ↓ calc: life_path, name_number (если есть имя), personal_year, personal_month, personal_day
    ↓ поиск в knowledge_numerology: embed f"число {n} жизненный путь" → top-3 чанка
      (отдельный запрос для каждого числа: life_path, personal_year)
    ↓ LLM (task_kind='numerology_interpret'): собрать связный ответ из чисел + интерпретаций
    → ответ пользователю + числа
    ↓ asyncio.create_task: save life_path_number + memory_fact
```

### Интеграция в dialog_graph.py

```python
# В build_dialog_graph() — добавить параметр:
def build_dialog_graph(..., numerology_service=None):

# В generate_response_node:
elif intent == "numerology" and numerology_service is not None:
    response = await numerology_service.handle(state)
```

### Команда /numerology

```python
# В telegram/handlers.py:
@router.message(Command("numerology"))
async def handle_numerology(message: Message, bot: Bot) -> None:
    unified = await adapter.to_unified(message)
    unified.text = message.text or "/numerology"
    async with typing_action(bot, message.chat.id):
        response = await dialog_service.handle(unified)
    await adapter.send(response, bot)
```

---

## Схема БД (миграция 022)

```sql
-- Добавить поле в user_profiles:
ALTER TABLE user_profiles
  ADD COLUMN life_path_number SMALLINT
    CHECK (life_path_number IS NULL OR life_path_number IN (
      1,2,3,4,5,6,7,8,9,11,22,33
    ));
```

`life_path_number` заполняется синхронно при первом расчёте нумерологии (в `NumerologyService.handle()`), а не через Celery.

---

## Qdrant коллекция

| Коллекция | Размерность | Метрика | Описание |
|-----------|-------------|---------|---------|
| `knowledge_numerology` | 3072 | Cosine | Толкования чисел 1-9, 11, 22, 33 по аспектам |

Создаётся в `mirror/core/memory/qdrant_init.py` (добавить в `COLLECTIONS`).

Формат документа:
```json
{
  "number": 7,
  "aspect": "жизненный путь",
  "title": "Число 7 — Искатель истины",
  "description": "Люди с числом 7 обладают...",
  "strengths": ["глубина мышления", "интуиция"],
  "challenges": ["замкнутость", "перфекционизм"],
  "personal_year_meaning": "Год 7 — время уединения и поиска...",
  "compatibility": [2, 9]
}
```

Минимальный набор при запуске: числа 1-9 + 11 + 22 + 33, для каждого числа минимум по 3 аспекта (жизненный путь, личный год, общее значение) = минимум 36 документов.

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `numerology_interpret` | main_chat | Сборка интерпретации из RAG-чанков + вычисленных чисел |

---

## Файлы к созданию / изменению

| Файл | Действие |
|------|---------|
| `mirror/services/numerology.py` | Создать — NumerologyService + NumerologyCalculator |
| `mirror/rag/numerology.py` | Создать — search_numerology_knowledge |
| `mirror/services/intent_router.py` | Изменить — добавить intent `numerology` с примерами фраз |
| `mirror/services/dialog_graph.py` | Изменить — параметр numerology_service + routing |
| `mirror/channels/telegram/handlers.py` | Изменить — добавить `/numerology` command |
| `mirror/core/memory/qdrant_init.py` | Изменить — добавить knowledge_numerology |
| `mirror/db/migrations/versions/022_numerology.py` | Создать — миграция |
| `mirror/db/seeds/llm_routing_stage2.py` | Дополнить |
| `resourses/knowledge_numerology/` | Создать — материалы для ingest |

---

## Definition of Done

- [ ] Smoke-тест: `life_path(date(1990,3,15))` → 1
- [ ] Smoke-тест: `life_path(date(1985,11,29))` → 11 (мастер-число)
- [ ] Smoke-тест: пользователь пишет «моё число судьбы» → получает полный расчёт
- [ ] Smoke-тест: без даты рождения → бот спрашивает
- [ ] Коллекция knowledge_numerology создана и заполнена (минимум числа 1-9 + 11, 22, 33)
- [ ] life_path_number записывается в user_profiles
- [ ] Логирование: `numerology.handle`, `numerology.calculated`
