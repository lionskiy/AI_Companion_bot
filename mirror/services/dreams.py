"""DreamsService — dream interpretation with symbols, moon context, patterns."""
import asyncio
import json
import re
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import structlog

from mirror.rag.dreams import search_dream_knowledge
from mirror.services.dialog_state import DialogState

logger = structlog.get_logger()


class DreamsService:
    def __init__(self, llm_router, memory_service, astrology_service, policy_engine) -> None:
        self._llm = llm_router
        self._memory = memory_service
        self._astrology = astrology_service
        self._policy = policy_engine

    async def handle(self, state: DialogState) -> str:
        uid = UUID(state["user_id"])

        # Policy check BEFORE any processing
        policy_result = await self._policy.check(user_id=uid, text_=state["message"])
        if policy_result.blocked or policy_result.risk_level.value == "crisis":
            logger.info("dreams.crisis_intercepted", user_id=str(uid))
            return policy_result.crisis_response

        symbols = await self.extract_symbols(state["message"])
        moon_ctx = self.get_moon_context(date.today())
        kb_results = await search_dream_knowledge(symbols, self._llm) if symbols else []
        patterns = await self.check_patterns(uid, symbols) if symbols else []

        interpretation = await self._llm_interpret(state, symbols, moon_ctx, kb_results, patterns)

        asyncio.create_task(
            self.save_dream(uid, state["message"], symbols, interpretation, moon_ctx)
        )

        pattern_msg = ""
        if patterns:
            pattern_msg = f"\n\n💭 Замечаю повторяющийся образ: {', '.join(patterns)}. Хочешь разберём?"

        logger.info("dreams.handle", user_id=str(uid), symbols=len(symbols))
        return interpretation + pattern_msg

    async def extract_symbols(self, dream_text: str) -> list[str]:
        try:
            raw = await self._llm.call(
                task_kind="dream_extract_symbols",
                messages=[{
                    "role": "user",
                    "content": (
                        "Извлеки символы из описания сна. Верни JSON-список строк, максимум 20 символов.\n\n"
                        f"Сон: {dream_text[:1000]}"
                    ),
                }],
                response_format={"type": "json_object"},
            )
            data = json.loads(raw)
            symbols = data.get("symbols", data) if isinstance(data, dict) else data
            if isinstance(symbols, list):
                return [str(s).lower().strip() for s in symbols[:20]]
        except Exception:
            logger.warning("dreams.extract_symbols_failed")
        return []

    def get_moon_context(self, target_date: date) -> dict:
        try:
            import ephem
            date_str = target_date.strftime("%Y/%m/%d")
            moon = ephem.Moon(date_str)
            prev_new = ephem.previous_new_moon(date_str)
            lunar_day = int((target_date - prev_new.datetime().date()).days) + 1
            lunar_day = max(1, min(lunar_day, 30))
            phase_pct = float(moon.phase)
            return {
                "lunar_day": lunar_day,
                "phase_pct": round(phase_pct),
                "phase_name": _phase_name(phase_pct),
            }
        except Exception:
            return {"lunar_day": None, "phase_pct": None, "phase_name": "неизвестно"}

    async def save_dream(
        self,
        user_id: UUID,
        dream_text: str,
        symbols: list[str],
        interpretation: str,
        moon_context: dict,
    ) -> None:
        text = f"Сон: {dream_text}\n\nСимволы: {', '.join(symbols)}\n\nЛунный день: {moon_context.get('lunar_day')}"
        await self._memory.write_episode(
            user_id=user_id,
            session_id=uuid4(),
            text_=text,
            importance=0.6,
            source_mode="dream",
        )

    async def check_patterns(self, user_id: UUID, symbols: list[str]) -> list[str]:
        repeated = []
        for symbol in symbols:
            try:
                results = await self._memory.search(user_id, f"dream_pattern {symbol}", top_k=3)
                for fact in results.get("facts", []):
                    if fact.get("fact_type") == "dream_pattern" and fact.get("key") == symbol:
                        value_data = {}
                        try:
                            value_data = json.loads(fact.get("value", "{}"))
                        except Exception:
                            pass
                        count = value_data.get("count", 1) + 1
                        value_data["count"] = count
                        value_data["last_seen"] = date.today().isoformat()
                        await self._memory.write_fact(
                            user_id=user_id,
                            key=symbol,
                            value=json.dumps(value_data, ensure_ascii=False),
                            fact_type="dream_pattern",
                            importance=min(0.9, 0.5 + count * 0.05),
                        )
                        if count >= 3:
                            repeated.append(symbol)
                        break
                else:
                    # First occurrence
                    await self._memory.write_fact(
                        user_id=user_id,
                        key=symbol,
                        value=json.dumps({"count": 1, "last_seen": date.today().isoformat()}, ensure_ascii=False),
                        fact_type="dream_pattern",
                        importance=0.5,
                    )
            except Exception:
                logger.warning("dreams.check_patterns_failed", symbol=symbol)
        return repeated

    async def _llm_interpret(
        self,
        state: DialogState,
        symbols: list[str],
        moon_ctx: dict,
        kb_results: list[dict],
        patterns: list[str],
    ) -> str:
        uid = UUID(state["user_id"])
        transit_context: dict = {}
        try:
            if self._astrology is not None:
                transits = await self._astrology.get_current_transits() or []
                transit_context = {
                    t.planet: {"sign": t.sign, "retrograde": t.is_retrograde}
                    for t in transits[:5]
                }
        except Exception:
            pass

        return await self._llm.call(
            task_kind="dream_interpret",
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "dream": state["message"][:1000],
                    "symbols": symbols,
                    "moon": moon_ctx,
                    "transits": transit_context,
                    "kb": kb_results[:9],
                    "recurring_patterns": patterns,
                }, ensure_ascii=False),
            }],
        )


def _phase_name(pct: float) -> str:
    if pct < 7:
        return "новолуние"
    if pct < 45:
        return "растущая луна"
    if pct < 55:
        return "полнолуние"
    return "убывающая луна"
