import structlog

from mirror.events.nats_client import nats_client

logger = structlog.get_logger()


async def publish_crisis_detected(user_id: str, session_id: str | None) -> None:
    try:
        await nats_client.publish(
            "mirror.safety.crisis_detected",
            {"user_id": user_id, "session_id": session_id},
        )
    except Exception:
        logger.warning("safety.crisis_publish_failed", user_id=user_id)
