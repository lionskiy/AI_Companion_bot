from aiogram import Router
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request

from mirror.config import settings

router = APIRouter()


def make_webhook_router(dp, bot) -> APIRouter:
    @router.post("/webhook/telegram/{secret}")
    async def telegram_webhook(
        secret: str,
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(None),
    ):
        if (
            x_telegram_bot_api_secret_token
            != settings.telegram_webhook_secret.get_secret_value()
        ):
            raise HTTPException(status_code=403)
        data = await request.json()
        update = Update(**data)
        await dp.feed_update(bot, update)
        return {"ok": True}

    return router
