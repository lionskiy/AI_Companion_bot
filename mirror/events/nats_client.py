import json
from typing import Callable

import nats
import nats.js.errors
import structlog

logger = structlog.get_logger()

MIRROR_STREAM = "MIRROR"
MIRROR_SUBJECTS = ["mirror.>"]


class NATSClient:
    def __init__(self):
        self._nc = None
        self._js = None

    async def connect(self, url: str) -> None:
        self._nc = await nats.connect(url)
        self._js = self._nc.jetstream()
        await self._ensure_stream()
        logger.info("nats.connected", url=url)

    async def _ensure_stream(self) -> None:
        try:
            await self._js.find_stream(MIRROR_SUBJECTS[0])
            logger.info("nats.stream_exists", stream=MIRROR_STREAM)
        except Exception:
            await self._js.add_stream(
                name=MIRROR_STREAM,
                subjects=MIRROR_SUBJECTS,
                retention="limits",
                max_age=7 * 24 * 3600,  # 7 дней
            )
            logger.info("nats.stream_created", stream=MIRROR_STREAM)

    async def publish(self, subject: str, payload: dict) -> None:
        data = json.dumps(payload).encode()
        await self._js.publish(subject, data)

    async def subscribe(self, subject: str, handler: Callable) -> None:
        async def _handler(msg):
            data = json.loads(msg.data.decode())
            await handler(data)
            await msg.ack()

        await self._js.subscribe(subject, cb=_handler, durable=subject.replace(".", "_"))
        logger.info("nats.subscribed", subject=subject)

    async def close(self) -> None:
        if self._nc:
            await self._nc.close()
            logger.info("nats.disconnected")


nats_client = NATSClient()
