import json
from typing import Callable

import nats
import structlog

logger = structlog.get_logger()


class NATSClient:
    def __init__(self):
        self._nc = None
        self._js = None

    async def connect(self, url: str) -> None:
        self._nc = await nats.connect(url)
        self._js = self._nc.jetstream()
        logger.info("nats.connected", url=url)

    async def publish(self, subject: str, payload: dict) -> None:
        data = json.dumps(payload).encode()
        await self._js.publish(subject, data)

    async def subscribe(self, subject: str, handler: Callable) -> None:
        async def _handler(msg):
            data = json.loads(msg.data.decode())
            await handler(data)
            await msg.ack()

        await self._js.subscribe(subject, cb=_handler)
        logger.info("nats.subscribed", subject=subject)

    async def close(self) -> None:
        if self._nc:
            await self._nc.close()
            logger.info("nats.disconnected")


nats_client = NATSClient()
