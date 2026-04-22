import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from uuid import UUID

import structlog
from sqlalchemy import select

import mirror.db.session as db_module
from mirror.config import settings
from mirror.core.llm.router import sanitize_input
from mirror.models.user import UserProfile

logger = structlog.get_logger()

BIRTH_DATA_QUESTION = (
    "Чтобы составить твою натальную карту, мне нужны данные рождения.\n\n"
    "Напиши в одном сообщении:\n"
    "• Дату рождения (например: 15.03.1990)\n"
    "• Время рождения (например: 14:30) — если знаешь\n"
    "• Город рождения"
)


@dataclass
class NatalChart:
    planets: dict = field(default_factory=dict)
    houses: dict = field(default_factory=dict)
    aspects: list = field(default_factory=list)


@dataclass
class Transit:
    planet: str
    sign: str
    degree: float
    is_retrograde: bool


class AstrologyService:
    def __init__(self, llm_router, redis_client) -> None:
        self._llm = llm_router
        self._redis = redis_client

    async def handle(self, state) -> str:
        from mirror.rag.astrology import search_astro_knowledge
        uid = UUID(state["user_id"])

        profile = await self._get_profile(uid)
        if not profile or not profile.birth_date:
            # Try to parse birth data from the current message
            parsed = await self._try_parse_birth_data(state["message"])
            if parsed:
                await self.save_birth_data(
                    uid,
                    parsed["birth_date"],
                    parsed.get("birth_time"),
                    parsed.get("birth_city", ""),
                    lat=parsed.get("lat"),
                    lon=parsed.get("lon"),
                )
                profile = await self._get_profile(uid)
                if not profile or not profile.birth_date:
                    return "Не удалось сохранить данные. Попробуй ещё раз."
            else:
                return BIRTH_DATA_QUESTION

        return await self._generate_astro_response(state, uid)

    async def _generate_astro_response(self, state, uid: UUID) -> str:
        from mirror.rag.astrology import search_astro_knowledge
        natal_chart = await self.get_natal_chart(uid)
        transits = await self.get_current_transits()
        knowledge_chunks = await search_astro_knowledge(
            query=state["message"],
            natal_context=format_natal_chart(natal_chart),
            llm_router=self._llm,
        )
        messages = build_astro_prompt(
            natal_chart=natal_chart,
            transits=transits,
            knowledge_chunks=knowledge_chunks,
            user_question=state["message"],
            facts=state.get("memory_context", {}).get("facts", []),
            sales_allowed=state.get("sales_allowed", True),
        )
        return await self._llm.call(
            task_kind="astro_interpret",
            messages=messages,
            tier=state.get("tier", "free"),
        )

    async def _try_parse_birth_data(self, message: str) -> dict | None:
        import re as _re
        # Quick pre-filter: must contain a date-like pattern
        if not _re.search(r'\d{1,2}[.,/\-]\d{1,2}[.,/\-]\d{4}', message):
            return None
        try:
            prompt = [
                {
                    "role": "system",
                    "content": (
                        "Extract birth data from the user message. "
                        "Return ONLY valid JSON, no other text:\n"
                        '{"birth_date":"YYYY-MM-DD","birth_time":"HH:MM or null","birth_city":"city name","lat":float_or_null,"lon":float_or_null}\n'
                        "If coordinates are provided in the message use them. "
                        "If birth_time is unknown use null."
                    ),
                },
                {"role": "user", "content": message},
            ]
            raw = await self._llm.call(
                task_kind="intent_classify",
                messages=prompt,
                max_tokens=150,
                temperature=0.0,
            )
            import json as _json, re as _re2
            m = _re2.search(r'\{.*\}', raw, _re2.DOTALL)
            if not m:
                return None
            data = _json.loads(m.group())
            birth_date = datetime.strptime(data["birth_date"], "%Y-%m-%d").date()
            birth_time = None
            if data.get("birth_time") and data["birth_time"] != "null":
                try:
                    birth_time = datetime.strptime(data["birth_time"], "%H:%M").time()
                except ValueError:
                    pass
            return {
                "birth_date": birth_date,
                "birth_time": birth_time,
                "birth_city": data.get("birth_city") or "",
                "lat": data.get("lat"),
                "lon": data.get("lon"),
            }
        except Exception:
            logger.warning("astrology.parse_birth_data_failed", message=message[:80])
            return None

    async def get_natal_chart(self, user_id: UUID) -> NatalChart:
        profile = await self._get_profile(user_id)
        if not profile or not profile.birth_date:
            return NatalChart()

        # Try cache
        if profile.natal_data:
            return _parse_natal_data(profile.natal_data)

        raw = await asyncio.to_thread(
            self._compute_natal_chart_sync,
            profile.birth_date,
            profile.birth_time,
            float(profile.birth_lat or 55.75),
            float(profile.birth_lon or 37.62),
        )
        natal_chart = self._parse_kerykeion_output(raw)

        # Cache in DB
        await self._save_natal_cache(user_id, natal_chart)
        return natal_chart

    async def get_current_transits(self) -> list[Transit]:
        now = datetime.now(timezone.utc)
        raw = await asyncio.to_thread(
            self._compute_transits_sync, now
        )
        return raw

    async def collect_birth_data(self, state) -> str:
        return BIRTH_DATA_QUESTION

    async def save_birth_data(
        self,
        user_id: UUID,
        birth_date: date,
        birth_time: time | None,
        birth_city: str,
        lat: float | None = None,
        lon: float | None = None,
    ) -> None:
        if lat is None or lon is None:
            coords = await geocode_city(birth_city, self._redis) if birth_city else None
            lat, lon = coords or (None, None)
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                profile.birth_date = birth_date
                profile.birth_time = birth_time
                profile.birth_city = birth_city
                profile.birth_lat = lat
                profile.birth_lon = lon
                profile.natal_data = None  # invalidate cache
                await session.commit()

    # ── internals ─────────────────────────────────────────────────────────

    def _compute_natal_chart_sync(self, birth_date, birth_time, lat, lon):
        from kerykeion import AstrologicalSubject
        subject = AstrologicalSubject(
            "user",
            birth_date.year, birth_date.month, birth_date.day,
            birth_time.hour if birth_time else 12,
            birth_time.minute if birth_time else 0,
            lng=lon, lat=lat,
            tz_str="UTC",
        )
        return subject

    def _parse_kerykeion_output(self, subject) -> NatalChart:
        planets = {}
        planet_names = [
            "sun", "moon", "mercury", "venus", "mars",
            "jupiter", "saturn", "uranus", "neptune", "pluto",
        ]
        for name in planet_names:
            obj = getattr(subject, name, None)
            if obj:
                planets[name.capitalize()] = {
                    "sign": obj.sign,
                    "degree": round(obj.position, 2),
                    "house": obj.house,
                }
        _HOUSE_ATTRS = [
            "first_house", "second_house", "third_house", "fourth_house",
            "fifth_house", "sixth_house", "seventh_house", "eighth_house",
            "ninth_house", "tenth_house", "eleventh_house", "twelfth_house",
        ]
        houses = {}
        for i, attr in enumerate(_HOUSE_ATTRS, start=1):
            h = getattr(subject, attr, None)
            if h:
                houses[f"House {i}"] = h.sign if hasattr(h, "sign") else str(h)

        return NatalChart(planets=planets, houses=houses, aspects=[])

    def _compute_transits_sync(self, dt: datetime) -> list[Transit]:
        from kerykeion import AstrologicalSubject
        subject = AstrologicalSubject(
            "transits",
            dt.year, dt.month, dt.day,
            dt.hour, dt.minute,
            lng=0.0, lat=51.5,
            tz_str="UTC",
        )
        planet_names = [
            "sun", "moon", "mercury", "venus", "mars",
            "jupiter", "saturn", "uranus", "neptune", "pluto",
        ]
        transits = []
        for name in planet_names:
            obj = getattr(subject, name, None)
            if obj:
                transits.append(Transit(
                    planet=name.capitalize(),
                    sign=obj.sign,
                    degree=round(obj.position, 2),
                    is_retrograde=getattr(obj, "retrograde", False),
                ))
        return transits

    async def _get_profile(self, user_id: UUID) -> UserProfile | None:
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            return result.scalar_one_or_none()

    async def _save_natal_cache(self, user_id: UUID, chart: NatalChart) -> None:
        data = {"planets": chart.planets, "houses": chart.houses, "aspects": chart.aspects}
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                profile.natal_data = data
                await session.commit()


# ── helpers ───────────────────────────────────────────────────────────────

def _parse_natal_data(data: dict) -> NatalChart:
    return NatalChart(
        planets=data.get("planets", {}),
        houses=data.get("houses", {}),
        aspects=data.get("aspects", []),
    )


def format_natal_chart(chart: NatalChart) -> str:
    if not chart.planets:
        return "Данные натальной карты отсутствуют."
    lines = [
        f"{planet}: {data['sign']} (дом {data.get('house', '?')}, {data.get('degree', 0):.1f}°)"
        for planet, data in chart.planets.items()
    ]
    return "\n".join(lines)


def format_transits(transits: list[Transit]) -> str:
    lines = []
    for t in transits[:5]:
        retro = " (ретроград)" if t.is_retrograde else ""
        lines.append(f"{t.planet}: {t.sign}{retro}")
    return "\n".join(lines)


def format_facts(facts: list[dict]) -> str:
    return "\n".join(f"- {f['key']}: {f['value']}" for f in facts[:10])


def build_astro_prompt(
    natal_chart: NatalChart,
    transits: list[Transit],
    knowledge_chunks: list[str],
    user_question: str,
    facts: list[dict],
    sales_allowed: bool,
) -> list[dict]:
    system = (
        "Ты астролог-интерпретатор. Отвечай тепло, лично и конкретно.\n"
        f"Натальная карта пользователя:\n{format_natal_chart(natal_chart)}\n\n"
        f"Текущие транзиты:\n{format_transits(transits)}"
    )
    if knowledge_chunks:
        system += f"\n\nКонтекст из базы знаний:\n{chr(10).join(knowledge_chunks)}"
    if facts:
        system += f"\n\nИзвестно о пользователе:\n{format_facts(facts)}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": sanitize_input(user_question)},
    ]


async def geocode_city(city: str, redis) -> tuple[float, float] | None:
    import json as _json
    cache_key = f"geocode:{city.lower().strip()}"
    cached = await redis.get(cache_key)
    if cached:
        data = _json.loads(cached)
        return data["lat"], data["lon"]
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="mirror_app/1.0")
        location = await asyncio.to_thread(geolocator.geocode, city, timeout=10)
        if location:
            result = {"lat": location.latitude, "lon": location.longitude}
            await redis.set(cache_key, _json.dumps(result), ex=86400 * 30)
            return location.latitude, location.longitude
    except Exception:
        logger.warning("astrology.geocode_failed", city=city)
    return None
