from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

VALID_SECRET = "test-secret-token"
VALID_UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "date": 0,
        "chat": {"id": 1, "type": "private"},
        "from": {"id": 1, "is_bot": False, "first_name": "Test"},
    },
}


@pytest.fixture
def webhook_app():
    from mirror.channels.telegram.webhook import make_webhook_router

    dp = AsyncMock()
    bot = MagicMock()
    app = FastAPI()
    with patch("mirror.channels.telegram.webhook.settings") as mock_settings:
        mock_settings.telegram_webhook_secret.get_secret_value.return_value = VALID_SECRET
        router = make_webhook_router(dp, bot)
        app.include_router(router)
    # store mock on app so tests can re-patch per-request if needed
    app.state.dp = dp
    return app, dp, mock_settings


async def test_webhook_valid_secret(webhook_app):
    app, dp, mock_settings = webhook_app
    with patch("mirror.channels.telegram.webhook.settings", mock_settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/webhook/telegram/{VALID_SECRET}",
                json=VALID_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_SECRET},
            )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_webhook_missing_header(webhook_app):
    app, _, mock_settings = webhook_app
    with patch("mirror.channels.telegram.webhook.settings", mock_settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/webhook/telegram/{VALID_SECRET}",
                json=VALID_UPDATE,
            )
    assert resp.status_code == 403


async def test_webhook_wrong_secret(webhook_app):
    app, _, mock_settings = webhook_app
    with patch("mirror.channels.telegram.webhook.settings", mock_settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/webhook/telegram/{VALID_SECRET}",
                json=VALID_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-token"},
            )
    assert resp.status_code == 403
