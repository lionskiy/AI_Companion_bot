"""PsychologyService — CBT, life wheel, ACT values, narrative practice."""
import json
from datetime import datetime, timezone
from uuid import UUID

import structlog

from mirror.services.dialog_state import DialogState

logger = structlog.get_logger()

_PRACTICE_TTL = 3600  # 1 hour


def _practice_key(user_id: UUID) -> str:
    return f"practice_state:{user_id}"


class PsychologyService:
    def __init__(self, llm_router, memory_service, redis_client, policy_engine) -> None:
        self._llm = llm_router
        self._memory = memory_service
        self._redis = redis_client
        self._policy = policy_engine

    async def handle(self, state: DialogState) -> str:
        uid = UUID(state["user_id"])

        # Policy check — crisis interrupts any ongoing practice
        policy_result = await self._policy.check(
            user_id=uid, text_=state["message"]
        )
        if policy_result.blocked or policy_result.risk_level.value == "crisis":
            await self.cancel(uid)
            logger.info("psychology.crisis_interrupted", user_id=str(uid))
            return policy_result.crisis_response

        # Continue existing practice from Redis
        raw = await self._redis.get(_practice_key(uid))
        if raw:
            data = json.loads(raw)
            practice = data.get("practice")
            if practice == "cbt":
                return await self.handle_cbt(state)
            if practice == "wheel":
                return await self.handle_wheel(state)
            if practice == "values":
                return await self.handle_values(state)
            if practice == "narrative":
                return await self.handle_narrative(state)

        # Route to new practice by message keywords
        msg = state.get("message", "").lower()
        if any(k in msg for k in ["колесо", "баланс", "сферы жизни", "life wheel"]):
            return await self.handle_wheel(state)
        if any(k in msg for k in ["ценности", "важно для меня", "act практика"]):
            return await self.handle_values(state)
        if any(k in msg for k in ["нарратив", "переписать историю", "переосмыслить"]):
            return await self.handle_narrative(state)
        return await self.handle_cbt(state)

    async def handle_cbt(self, state: DialogState) -> str:
        uid = UUID(state["user_id"])
        raw = await self._redis.get(_practice_key(uid))
        data = json.loads(raw) if raw else {"practice": "cbt", "step": 0, "data": {}}

        step = data.get("step", 0)
        step_data = data.get("data", {})

        steps = [
            ("situation",        "Расскажи что произошло — только факты, без оценок."),
            ("auto_thought",     "Какая мысль возникла первой?"),
            ("emotion",          "Что почувствовал(а)? Насколько сильно (1–10)?"),
            ("challenge",        "Какие есть доказательства ЗА и ПРОТИВ этой мысли?"),
            ("alt_thought",      "Как ещё можно посмотреть на эту ситуацию?"),
        ]

        if step == 0:
            # First call — start practice
            data = {"practice": "cbt", "step": 1, "data": {}}
            await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
            return f"Давай разберём эту ситуацию по шагам. {steps[0][1]}"

        # Save current answer
        field, _ = steps[step - 1]
        step_data[field] = state["message"]
        data["data"] = step_data

        if step >= len(steps):
            # Practice complete
            await self.cancel(uid)
            await self.save_practice_result(uid, "cbt", step_data)
            result = await self._llm.call(
                task_kind="psychology_cbt",
                messages=[{"role": "user", "content": json.dumps(step_data, ensure_ascii=False)}],
            )
            return result

        # Move to next step
        data["step"] = step + 1
        await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
        return steps[step][1]

    async def handle_wheel(self, state: DialogState) -> str:
        uid = UUID(state["user_id"])
        raw = await self._redis.get(_practice_key(uid))
        data = json.loads(raw) if raw else {"practice": "wheel", "step": 0, "data": {}}

        spheres = [
            ("work",          "Насколько доволен(а) своей работой/карьерой? (1–10)"),
            ("finances",      "Насколько удовлетворён(а) финансовой ситуацией? (1–10)"),
            ("health",        "Как оцениваешь физическое состояние? (1–10)"),
            ("relationships", "Насколько наполнены близкие отношения? (1–10)"),
            ("growth",        "Чувствуешь ли развитие и движение вперёд? (1–10)"),
            ("leisure",       "Есть ли время на то, что любишь? (1–10)"),
            ("social",        "Как себя чувствуешь в своём окружении? (1–10)"),
            ("spirituality",  "Насколько есть ощущение смысла и цели? (1–10)"),
        ]

        step = data.get("step", 0)
        step_data = data.get("data", {})

        if step == 0:
            data = {"practice": "wheel", "step": 1, "data": {}}
            await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
            return f"Колесо жизненного баланса — 8 сфер. {spheres[0][1]}"

        # Parse score from message
        import re
        numbers = re.findall(r"\b([1-9]|10)\b", state["message"])
        score = int(numbers[0]) if numbers else 5
        field, _ = spheres[step - 1]
        step_data[field] = score
        data["data"] = step_data

        if step >= len(spheres):
            await self.cancel(uid)
            ascii_map = _render_wheel(step_data)
            # Save snapshot to DB
            await _save_wheel_snapshot(uid, step_data)
            await self.save_practice_result(uid, "wheel", step_data)
            return f"Вот твоё колесо:\n\n{ascii_map}\n\nСредний балл: {sum(step_data.values()) / len(step_data):.1f}"

        data["step"] = step + 1
        await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
        return spheres[step][1]

    async def handle_values(self, state: DialogState) -> str:
        uid = UUID(state["user_id"])
        raw = await self._redis.get(_practice_key(uid))
        data = json.loads(raw) if raw else {"practice": "values", "step": 0, "data": {}}

        questions = [
            "Что для тебя важнее всего в жизни?",
            "Когда ты чувствуешь себя по-настоящему живым(ой)?",
            "Какими качествами ты хочешь обладать?",
            "Что бы ты делал(а), если бы не было ограничений?",
        ]

        step = data.get("step", 0)
        answers = data.get("data", {})

        if step == 0:
            data = {"practice": "values", "step": 1, "data": {}}
            await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
            return f"Практика ценностей (ACT). {questions[0]}"

        answers[f"q{step}"] = state["message"]
        data["data"] = answers

        if step >= len(questions):
            await self.cancel(uid)
            result = await self._llm.call(
                task_kind="psychology_values",
                messages=[{"role": "user", "content": json.dumps(answers, ensure_ascii=False)}],
            )
            # Save extracted values as facts
            await self.save_practice_result(uid, "values", answers)
            return result

        data["step"] = step + 1
        await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
        return questions[step]

    async def handle_narrative(self, state: DialogState) -> str:
        uid = UUID(state["user_id"])
        raw = await self._redis.get(_practice_key(uid))
        data = json.loads(raw) if raw else {"practice": "narrative", "step": 0, "data": {}}

        step = data.get("step", 0)
        story_data = data.get("data", {})

        if step == 0:
            data = {"practice": "narrative", "step": 1, "data": {}}
            await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
            return "Расскажи историю, которая до сих пор причиняет боль или ощущается как поражение."

        if step == 1:
            story_data["original"] = state["message"]
            data["data"] = story_data
            data["step"] = 2
            await self._redis.setex(_practice_key(uid), _PRACTICE_TTL, json.dumps(data))
            return "Что ты приобрёл(а) или чему научился(ась) из этой ситуации?"

        story_data["lesson"] = state["message"]
        await self.cancel(uid)
        result = await self._llm.call(
            task_kind="psychology_narrative",
            messages=[{"role": "user", "content": json.dumps(story_data, ensure_ascii=False)}],
        )
        await self.save_practice_result(uid, "narrative", story_data)
        return result

    async def cancel(self, user_id: UUID) -> None:
        await self._redis.delete(_practice_key(user_id))

    async def save_practice_result(
        self,
        user_id: UUID,
        practice_type: str,
        data: dict,
    ) -> None:
        fact_type_map = {
            "cbt": "cbt_pattern",
            "wheel": "life_wheel_score",
            "values": "value",
            "narrative": "narrative_reframe",
        }
        fact_type = fact_type_map.get(practice_type, "observed")
        summary = json.dumps(data, ensure_ascii=False)[:500]
        await self._memory.write_fact(
            user_id=user_id,
            key=f"{practice_type}_session_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            value=summary,
            fact_type=fact_type,
            importance=0.7,
        )
        logger.info("psychology.practice_saved", user_id=str(user_id), practice=practice_type)


def _render_wheel(scores: dict) -> str:
    labels = {
        "work": "   Работа/карьера",
        "finances": "        Финансы",
        "health": "  Здоровье/тело",
        "relationships": " Отношения/семья",
        "growth": "  Личн. развитие",
        "leisure": "          Отдых",
        "social": "      Окружение",
        "spirituality": "    Духовность",
    }
    lines = []
    for key, label in labels.items():
        score = scores.get(key, 0)
        bar = "█" * score + "░" * (10 - score)
        lines.append(f"{label}: {score:2d}  {bar}")
    return "\n".join(lines)


async def _save_wheel_snapshot(user_id: UUID, scores: dict) -> None:
    try:
        import mirror.db.session as db_module
        from mirror.models.journal import LifeWheelSnapshot
        async with db_module.async_session_factory() as session:
            snapshot = LifeWheelSnapshot(user_id=user_id, scores=scores)
            session.add(snapshot)
            await session.commit()
    except Exception:
        logger.warning("psychology.wheel_snapshot_failed", user_id=str(user_id))
