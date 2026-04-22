from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from mirror.channels.telegram.adapter import TelegramAdapter, _split_text

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _make_message(text="/start", user_id="42", lang="ru"):
    msg = MagicMock()
    msg.message_id = 1
    msg.from_user.id = user_id
    msg.from_user.language_code = lang
    msg.chat.id = user_id
    msg.text = text
    msg.date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return msg


@pytest.fixture
def mock_identity():
    svc = AsyncMock()
    svc.get_or_create.return_value = (uuid4(), True)
    return svc


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get.return_value = None
    return r


@pytest.fixture
def adapter(mock_identity, mock_redis):
    return TelegramAdapter(identity_service=mock_identity, redis_client=mock_redis)


async def test_to_unified_basic(adapter, mock_identity):
    msg = _make_message(text="hello")
    unified = await adapter.to_unified(msg)
    assert unified.channel == "telegram"
    assert unified.text == "hello"
    assert unified.is_first_message is False
    mock_identity.get_or_create.assert_awaited_once()


async def test_to_unified_start(adapter):
    msg = _make_message(text="/start")
    unified = await adapter.to_unified(msg, is_new_start=True)
    assert unified.is_first_message is True


async def test_session_created_when_missing(adapter, mock_redis):
    mock_redis.get.return_value = None
    msg = _make_message()
    unified = await adapter.to_unified(msg)
    mock_redis.set.assert_awaited_once()
    assert unified.session_id is not None


async def test_session_reused_when_present(adapter, mock_redis):
    import json
    existing_id = str(uuid4())
    mock_redis.get.return_value = json.dumps({"session_id": existing_id, "created_at": "2026-01-01T00:00:00"})
    msg = _make_message()
    unified = await adapter.to_unified(msg)
    mock_redis.set.assert_not_awaited()
    assert unified.session_id == existing_id


async def test_session_reset_on_start(adapter, mock_redis):
    import json
    old_id = str(uuid4())
    mock_redis.get.return_value = json.dumps({"session_id": old_id, "created_at": "2026-01-01T00:00:00"})
    msg = _make_message(text="/start")
    with patch("mirror.channels.telegram.adapter._publish_session_closed", new_callable=AsyncMock) as mock_pub:
        unified = await adapter.to_unified(msg, is_new_start=True)
    mock_pub.assert_awaited_once()
    assert unified.session_id != old_id


def test_split_text_short():
    assert _split_text("hello") == ["hello"]


def test_split_text_long():
    text = "x" * 9000
    parts = _split_text(text)
    assert len(parts) == 3
    assert all(len(p) <= 4000 for p in parts)
    assert "".join(parts) == text


async def test_split_text_send(adapter, mock_redis):
    bot = AsyncMock()
    from mirror.channels.base import UnifiedResponse
    resp = UnifiedResponse(
        text="a" * 8001,
        chat_id="42",
        channel="telegram",
    )
    await adapter.send(resp, bot)
    assert bot.send_message.await_count == 3
