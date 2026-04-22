import structlog

from mirror.events.nats_client import nats_client

logger = structlog.get_logger()


async def start_memory_consumer() -> None:
    await nats_client.subscribe(
        subject="mirror.dialog.session.closed",
        handler=_on_session_closed,
    )
    logger.info("memory.consumer_started")


async def _on_session_closed(data: dict) -> None:
    try:
        user_id = data["user_id"]
        session_id = data["session_id"]
    except Exception:
        logger.warning("memory.consumer.bad_message")
        return

    from mirror.workers.tasks.memory import summarize_episode
    summarize_episode.delay(user_id, session_id)
    logger.info("memory.consumer.session_closed", user_id=user_id, session_id=session_id)
