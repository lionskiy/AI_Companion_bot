# Module 07: Astrology — Spec

**Статус:** Ready for development  
**Этап:** 1 · **Ссылка на POD:** §6.1, §6.2, §12.4  
**Зависимости:** Module 01 (Identity — нужен user_profiles), Module 05 (LLM Router), Module 03 (Memory)  
**Дата:** 2026-04-20

---

## Цель

Астрологический модуль: натальная карта, транзиты и интерпретации через RAG + LLM. Данные рождения берутся из профиля пользователя. Интерпретации персонализируются через контекст памяти.

---

## Acceptance Criteria

- [ ] `AstrologyService.handle(state: DialogState) → str` — основная точка входа
- [ ] `AstrologyService.get_natal_chart(user_id) → NatalChart` — вычисление через kerykeion
- [ ] `AstrologyService.get_current_transits() → list[Transit]` — текущие планетарные позиции
- [ ] Данные рождения берутся из `user_profiles` (дата + время + место)
- [ ] Если данных рождения нет → собрать через диалог, сохранить в профиль
- [ ] RAG: поиск в `knowledge_astro` по запросу пользователя (Haystack)
- [ ] Интерпретация через LLM (task_kind="astro_interpret") с контекстом RAG + natal chart
- [ ] Результат интерпретации не сохраняется в БД (генерируется каждый раз)
- [ ] Qdrant коллекция `knowledge_astro` создаётся при старте (idempotent)
- [ ] Тест: запрос по натальной карте → ответ содержит планеты

---

## Out of Scope

- Синастрия (совместимость пар) — Этап 2
- Прогнозы на год/месяц — Этап 2
- Уведомления о транзитах (proactive) — Этап 2
- Публикация гороскопов — Этап 2

---

## Схема БД

```sql
-- Расширение таблицы user_profiles (уже создана в Module 01)
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS birth_date    date,
    ADD COLUMN IF NOT EXISTS birth_time    time,
    ADD COLUMN IF NOT EXISTS birth_city    text,
    ADD COLUMN IF NOT EXISTS birth_lat     numeric(9,6),
    ADD COLUMN IF NOT EXISTS birth_lon     numeric(9,6),
    ADD COLUMN IF NOT EXISTS zodiac_sign   text,
    ADD COLUMN IF NOT EXISTS natal_data    jsonb;  -- кэш kerykeion output

-- Кэш натальной карты сбрасывается при изменении birth_*
```

---

## Qdrant коллекции

```python
QDRANT_COLLECTIONS = {
    "knowledge_astro": {
        "size": 3072,            # text-embedding-3-large
        "distance": "Cosine",
        # payload: topic, sign, planet, house, aspect, source, language
    }
}
```

---

## Публичный контракт `AstrologyService`

```python
# mirror/services/astrology.py  ← НЕ ИЗМЕНЯТЬ без явного ТЗ

class NatalChart:
    planets:    dict  # {"Sun": {"sign": "Aries", "degree": 12.5, "house": 1}, ...}
    houses:     dict  # {"ASC": "Aries", "MC": "Capricorn", ...}
    aspects:    list  # [{"planet1": "Sun", "planet2": "Moon", "aspect": "trine"}, ...]

class Transit:
    planet:     str
    sign:       str
    degree:     float
    is_retrograde: bool

class AstrologyService:
    async def handle(self, state: "DialogState") -> str:
        """
        1. Получить natal chart (из кэша или вычислить через kerykeion)
        2. Получить текущие транзиты
        3. RAG поиск в knowledge_astro
        4. LLM интерпретация (task_kind="astro_interpret")
        """

    async def get_natal_chart(self, user_id: UUID) -> NatalChart:
        """Вычислить через kerykeion. Кэшировать в natal_data. """

    async def get_current_transits(self) -> list[Transit]:
        """Текущие позиции планет через kerykeion."""

    async def collect_birth_data(self, state: "DialogState") -> str:
        """Если birth_date/city нет → вернуть вопрос пользователю."""

    async def save_birth_data(
        self, user_id: UUID,
        birth_date: date, birth_time: time | None, birth_city: str
    ) -> None:
        """Геокодировать город → lat/lon, сохранить в user_profiles."""
```

---

## RAG pipeline

```python
# mirror/rag/astrology.py

async def search_astro_knowledge(query: str, natal_context: str, top_k: int = 5) -> list[str]:
    """
    1. Embed query через LLMRouter.embed()
    2. Поиск в knowledge_astro Qdrant (без фильтра user_id — KB общая)
    3. Вернуть список текстовых чанков
    """
```

---

## Промпт для astro_interpret

```python
def build_astro_prompt(
    natal_chart: NatalChart,
    transits: list[Transit],
    knowledge_chunks: list[str],
    user_question: str,
    facts: list[dict],
    sales_allowed: bool,
) -> list[dict]:
    system = f"""Ты астролог-интерпретатор. Отвечай тепло, лично и конкретно.
Натальная карта пользователя:
{format_natal_chart(natal_chart)}

Текущие транзиты:
{format_transits(transits)}

Контекст из базы знаний:
{chr(10).join(knowledge_chunks)}
"""
    if facts:
        system += f"\nИзвестно о пользователе:\n{format_facts(facts)}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": sanitize_input(user_question)},
    ]
```

---

## Геокодирование городов

```python
# Nominatim имеет rate limit: 1 req/s. Результаты кэшируются в Redis.

async def geocode_city(city: str) -> tuple[float, float] | None:
    cache_key = f"geocode:{city.lower().strip()}"
    cached = await redis.get(cache_key)
    if cached:
        data = json.loads(cached)
        return data["lat"], data["lon"]

    # Nominatim — синхронная, запускать в executor
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="mirror_app/1.0")
    location = await asyncio.to_thread(geolocator.geocode, city)
    if location:
        result = {"lat": location.latitude, "lon": location.longitude}
        await redis.set(cache_key, json.dumps(result), ex=86400 * 30)  # кэш 30 дней
        return location.latitude, location.longitude
    return None
```

---

## Вспомогательные форматтеры

```python
# mirror/services/astrology.py

def format_natal_chart(chart: NatalChart) -> str:
    lines = []
    for planet, data in chart.planets.items():
        lines.append(f"{planet}: {data['sign']} (дом {data['house']}, {data['degree']:.1f}°)")
    return "\n".join(lines)

def format_transits(transits: list[Transit]) -> str:
    lines = []
    for t in transits[:5]:  # топ-5 самых значимых
        retro = " (ретроград)" if t.is_retrograde else ""
        lines.append(f"{t.planet}: {t.sign}{retro}")
    return "\n".join(lines)

def format_facts(facts: list[dict]) -> str:
    return "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:10])
```

---

## kerykeion — sync в async контексте

kerykeion 4.x — синхронная библиотека (CPU-bound вычисления).
Запускать через `asyncio.to_thread()`:

```python
async def get_natal_chart(self, user_id: UUID) -> NatalChart:
    profile = await self._get_profile(user_id)
    # kerykeion синхронный — запуск в отдельном потоке
    raw = await asyncio.to_thread(
        self._compute_natal_chart_sync,
        profile.birth_date, profile.birth_time,
        profile.birth_lat, profile.birth_lon
    )
    return self._parse_kerykeion_output(raw)

def _compute_natal_chart_sync(self, birth_date, birth_time, lat, lon) -> dict:
    from kerykeion import AstrologicalSubject
    subject = AstrologicalSubject(
        "user", birth_date.year, birth_date.month, birth_date.day,
        birth_time.hour if birth_time else 12,
        birth_time.minute if birth_time else 0,
        lng=lon, lat=lat
    )
    return subject  # kerykeion объект
```

---

## Hard Constraints

- kerykeion — единственная библиотека для астрологических вычислений
- Natal chart кэшируется в `user_profiles.natal_data` (invalidate при изменении birth_*)
- Геолокация через geopy, не через платный API
- RAG поиск в `knowledge_astro` без фильтра `user_id` (KB общая для всех)
- Фильтр `user_id` — ТОЛЬКО для `user_episodes` и `user_facts`
- `task_kind="astro_interpret"` для всех LLM-вызовов модуля

---

## DoD

- `AstrologyService.get_natal_chart()` возвращает объект с планетами и домами
- RAG поиск возвращает релевантные чанки по знаку/планете
- Интерпретация персонализирована (содержит данные из natal chart)
- Если birth_date отсутствует → пользователю задаётся вопрос
- `pytest tests/astrology/` зелёный
