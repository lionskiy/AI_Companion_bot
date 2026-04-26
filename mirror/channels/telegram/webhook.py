from aiogram import Router
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request

from mirror.config import settings

router = APIRouter()


def make_webhook_router(dp, bot) -> APIRouter:
    # Per-bot route: /webhook/telegram/{tg_bot_id}/{secret}
    # Used by all bots added via admin panel.
    @router.post("/webhook/telegram/{bot_id}/{secret}")
    async def telegram_webhook_per_bot(
        bot_id: str,
        secret: str,
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(None),
    ):
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret.get_secret_value():
            raise HTTPException(status_code=403)
        bots = getattr(request.app.state, "tg_bots", [])
        entry = next((b for b in bots if str(b.get("tg_id")) == bot_id), None)
        if entry is None or not entry.get("bot_obj"):
            # Bot deleted or not yet registered — acknowledge but don't process.
            # Telegram may keep retrying for a few seconds after delete_webhook().
            return {"ok": True}
        data = await request.json()
        update = Update(**data)
        await dp.feed_update(entry["bot_obj"], update)
        return {"ok": True}

    # Legacy single-segment route kept for backward compat / polling-mode fallback.
    @router.post("/webhook/telegram/{secret}")
    async def telegram_webhook_legacy(
        secret: str,
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(None),
    ):
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret.get_secret_value():
            raise HTTPException(status_code=403)
        data = await request.json()
        update = Update(**data)
        active_bot = getattr(request.app.state, "bot", bot)
        await dp.feed_update(active_bot, update)
        return {"ok": True}

    return router
