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
- [ ] Число жизненного пути вычисляется по дате рождения (алгоритм Пифагора)
- [ ] Число имени вычисляется по имени пользователя (таблица Пифагора, русский + латинский алфавиты)
- [ ] Личный год = (день рожд. + месяц рожд. + текущий год) → сведение к 1-9 или 11/22/33
- [ ] Личный месяц = личный год + текущий месяц → сведение
- [ ] Личный день = личный месяц + текущий день → сведение
- [ ] RAG поиск по `knowledge_numerology` возвращает интерпретации для каждого числа
- [ ] Если нет даты рождения — бот спрашивает её (через OnboardingManager)
- [ ] Если нет имени — интерпретируется только по дате рождения
- [ ] Число жизненного пути сохраняется в `user_profiles.life_path_number`
- [ ] Результат расчёта сохраняется как факт в memory_facts (fact_type='numerology')
- [ ] Команда `/numerology` или фразы «нумерология», «число судьбы» запускают режим

---

## Архитектура

### Алгоритм расчётов

```python
class NumerologyCalculator:
    # Полная таблица русского алфавита (включая ё)
    PYTHAGOREAN_RU = {
        'а':1,'б':2,'в':3,'г':4,'д':5,'е':6,'ё':6,'ж':7,'з':8,'и':9,
        'й':1,'к':2,'л':3,'м':4,'н':5,'о':6,'п':7,'р':8,'с':9,
        'т':1,'у':2,'ф':3,'х':4,'ц':5,'ч':6,'ш':7,'щ':8,'ъ':9,
        'ы':1,'ь':2,'э':3,'ю':4,'я':5,
    }
    # Латинский алфавит (английский Пифагора)
    PYTHAGOREAN_EN = {
        'a':1,'b':2,'c':3,'d':4,'e':5,'f':6,'g':7,'h':8,'i':9,
        'j':1,'k':2,'l':3,'m':4,'n':5,'o':6,'p':7,'q':8,'r':9,
        's':1,'t':2,'u':3,'v':4,'w':5,'x':6,'y':7,'z':8,
    }
    MASTER_NUMBERS = {11, 22, 33}

    def reduce(self, n: int) -> int:
        """Сводит к 1-9 или мастер-числу (11, 22, 33 не сводятся)."""
        while n > 9 and n not in self.MASTER_NUMBERS:
            n = sum(int(d) for d in str(n))
        return n

    def life_path(self, birth_date: date) -> int:
        # Стандартный метод: сводить каждую часть отдельно, потом суммировать
        d = self.reduce(birth_date.day)
        m = self.reduce(birth_date.month)
        y = self.reduce(sum(int(c) for c in str(birth_date.year)))
        return self.reduce(d + m + y)

    def name_number(self, name: str) -> int:
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
        # Личный день = личный месяц + число дня (reduce каждого)
        pm = self.personal_month(birth_date, today.year, today.month)
        return self.reduce(pm + self.reduce(today.day))
```

### RAG pipeline

```
запрос пользователя
    ↓ intent = 'numerology'
    → NumerologyService.handle(state)
    ↓ calculate: life_path, personal_year, personal_month, personal_day
    ↓ search knowledge_numerology: интерпретации для каждого числа
    ↓ LLM (task_kind=numerology_interpret): сборка связного ответа
    → ответ + числа
    ↓ async: save fact life_path_number
```

---

## Схема БД

```sql
-- Добавить поле в user_profiles:
ALTER TABLE user_profiles
  ADD COLUMN life_path_number SMALLINT;
```

---

## Qdrant коллекция

| Коллекция | Описание |
|-----------|---------|
| `knowledge_numerology` | Толкования чисел 1-9, 11, 22, 33 по аспектам |

Формат документа:
```json
{
  "number": 7,
  "aspect": "жизненный путь",
  "title": "Число 7 — Искатель истины",
  "description": "Люди с числом 7 обладают...",
  "strengths": ["глубина мышления", "интуиция", ...],
  "challenges": ["замкнутость", "перфекционизм", ...],
  "personal_year_meaning": "Год 7 — время уединения и поиска...",
  "compatibility": [2, 9]
}
```

---

## Новые task_kinds

| task_kind | Модель | Описание |
|-----------|--------|---------|
| `numerology_interpret` | main_chat | Сборка интерпретации из RAG-чанков + чисел |

---

## Файлы к созданию / изменению

- `mirror/services/numerology.py` — NumerologyService + NumerologyCalculator (новый)
- `mirror/rag/numerology.py` — search_numerology_knowledge (новый)
- `mirror/services/intent_router.py` — добавить intent `numerology`
- `mirror/services/dialog_graph.py` — routing на NumerologyService
- `mirror/db/migrations/versions/021_user_profiles_numerology.py` — миграция
- `mirror/db/seeds/llm_routing_stage2.py` — новые task_kinds
- `resourses/knowledge_numerology/` — материалы для ingest

---

## Definition of Done

- [ ] Smoke-тест: дата рождения 15.03.1990 → число жизненного пути = 1 (1+5+0+3+1+9+9+0=28→10→1)
- [ ] Smoke-тест: пользователь пишет «моё число судьбы» → получает полный расчёт
- [ ] Smoke-тест: без даты рождения → бот спрашивает
- [ ] Коллекция knowledge_numerology заполнена (минимум числа 1-9 + 11, 22)
- [ ] Логирование: `numerology.handle`, `numerology.calculated`
