import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from mirror.channels.base import UnifiedMessage, UnifiedResponse
from mirror.core.identity.service import IdentityService
from mirror.events.nats_client import nats_client

logger = structlog.get_logger()

SESSION_TTL = 172800  # 48 hours


class TelegramAdapter:
    def __init__(self, identity_service: IdentityService, redis_client) -> None:
        self._identity = identity_service
        self._redis = redis_client

    async def to_unified(
        self, message: Message, is_new_start: bool = False
    ) -> UnifiedMessage:
        u = message.from_user
        channel_user_id = str(u.id)
        global_user_id, _ = await self._identity.get_or_create(
            channel="telegram",
            channel_user_id=channel_user_id,
            language_code=u.language_code,
            first_name=u.first_name,
            last_name=u.last_name,
            username=u.username,
            is_premium=bool(getattr(u, "is_premium", False)),
        )
        session_id = await self._get_or_create_session(global_user_id, is_new_start)
        return UnifiedMessage(
            message_id=str(message.message_id),
            channel="telegram",
            chat_id=str(message.chat.id),
            channel_user_id=channel_user_id,
            global_user_id=str(global_user_id),
            text=message.text or "",
            timestamp=message.date or datetime.now(timezone.utc),
            is_first_message=is_new_start,
            session_id=session_id,
            metadata={
                "language_code": u.language_code,
                "platform": "telegram",
            },
            raw_payload={},  # intentionally empty — contains PII
        )

    async def callback_to_unified(
        self, callback: CallbackQuery, action: str
    ) -> UnifiedMessage:
        u = callback.from_user
        channel_user_id = str(u.id)
        global_user_id, _ = await self._identity.get_or_create(
            channel="telegram",
            channel_user_id=channel_user_id,
            language_code=u.language_code,
            first_name=u.first_name,
            last_name=u.last_name,
            username=u.username,
            is_premium=bool(getattr(u, "is_premium", False)),
        )
        session_id = await self._get_or_create_session(global_user_id)
        return UnifiedMessage(
            message_id=str(callback.id),
            channel="telegram",
            chat_id=str(callback.message.chat.id),
            channel_user_id=channel_user_id,
            global_user_id=str(global_user_id),
            text=action,
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
            metadata={
                "language_code": u.language_code,
                "platform": "telegram",
                "callback_data": callback.data,
            },
            raw_payload={},
        )

    async def send(self, response: UnifiedResponse, bot) -> None:
        keyboard = _build_keyboard(response.buttons) if response.buttons else None
        parts = _split_text(response.text)
        for i, part in enumerate(parts):
            await bot.send_message(
                chat_id=response.chat_id,
                text=part,
                parse_mode=response.parse_mode,
                reply_markup=keyboard if i == len(parts) - 1 else None,
            )

    async def _get_or_create_session(
        self, global_user_id: UUID, is_new_start: bool = False
    ) -> str:
        key = f"session:{global_user_id}"
        existing = await self._redis.get(key)
        if existing and is_new_start:
            old_data = json.loads(existing)
            await _publish_session_closed(str(global_user_id), old_data["session_id"])
        if not existing or is_new_start:
            session_id = str(uuid4())
            await self._redis.set(
                key,
                json.dumps(
                    {
                        "session_id": session_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                ex=SESSION_TTL,
            )
            return session_id
        return json.loads(existing)["session_id"]


def _split_text(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts = []
    while text:
        parts.append(text[:max_len])
        text = text[max_len:]
    return parts


def _build_keyboard(buttons: list[dict]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"])]
            for b in buttons
        ]
    )


async def _publish_session_closed(user_id: str, session_id: str) -> None:
    try:
        await nats_client.publish(
            "mirror.dialog.session.closed",
            {"user_id": user_id, "session_id": session_id},
        )
    except Exception:
        logger.warning("session_closed.publish_failed", user_id=user_id)
