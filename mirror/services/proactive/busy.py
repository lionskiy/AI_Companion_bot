"""BusyBehavior — bot occasionally pretends to be busy."""
import random
from datetime import datetime
from uuid import UUID

import structlog

logger = structlog.get_logger()

_BUSY_ACTIVITIES = [
    "была на прогулке", "читала кое-что интересное",
    "занималась медитацией", "помогала подруге",
    "смотрела закат", "немного задремала",
]


class BusyBehavior:
    def __init__(self, redis_client, policy_engine) -> None:
        self._redis = redis_client
        self._policy = policy_engine

    async def maybe_intercept(self, user_id: UUID, message_text: str, bot, chat_id: int) -> bool:
        from mirror.services.proactive.helpers import _get_last_user_message_time, _get_profile

        profile = await _get_profile(user_id)
        if profile is None:
            return False
        tier = getattr(profile, "tier", "free")
        if tier not in ("plus", "pro"):
            return False

        last_msg_time = await _get_last_user_message_time(user_id)
        if last_msg_time and (datetime.utcnow() - last_msg_time).total_seconds() > 86400:
            return False

        try:
            policy_result = await self._policy.check(user_id=user_id, text_=message_text)
            if policy_result.risk_level.value in ("crisis", "risk_signal"):
                return False
        except Exception:
            return False

        busy_prob = getattr(profile, "busy_probability", 0.03) or 0.03
        if random.random() >= busy_prob:
            return False

        activity = random.choice(_BUSY_ACTIVITIES)
        await bot.send_message(chat_id, f"Сори, {activity}! Скоро вернусь 😊")
        await self._redis.setex(f"busy_pending:{user_id}", 2400, message_text)

        delay = random.randint(300, 2400)
        from mirror.workers.tasks.proactive import schedule_return
        schedule_return.apply_async(
            args=[str(user_id), str(chat_id), message_text, activity],
            countdown=delay,
        )
        logger.info("proactive.busy_triggered", user_id=str(user_id), activity=activity)
        return True
