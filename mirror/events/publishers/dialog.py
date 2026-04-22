import json

import structlog

from mirror.events.nats_client import nats_client

logger = structlog.get_logger()


async def publish_session_closed(user_id: str, session_id: str) -> None:
    try:
        await nats_client.publish(
            "mirror.dialog.session.closed",
            {"user_id": user_id, "session_id": session_id},
        )
    except Exception:
        logger.warning("dialog.session_closed_publish_failed", user_id=user_id)
