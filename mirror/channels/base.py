from datetime import datetime

from pydantic import BaseModel


class UnifiedMessage(BaseModel):
    message_id: str
    channel: str
    chat_id: str
    channel_user_id: str
    global_user_id: str
    text: str
    media_url: str | None = None
    timestamp: datetime
    is_first_message: bool = False
    session_id: str
    metadata: dict
    raw_payload: dict


class UnifiedResponse(BaseModel):
    text: str
    chat_id: str
    channel: str
    buttons: list[dict] | None = None
    media_url: str | None = None
    parse_mode: str | None = None
