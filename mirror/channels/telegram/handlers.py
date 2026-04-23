import asyncio
from contextlib import asynccontextmanager

import structlog
from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from mirror.channels.base import UnifiedResponse
from mirror.core.llm.exceptions import AllModelsUnavailableError
from mirror.services.billing import QuotaExceededError

logger = structlog.get_logger()

COMMANDS = {
    "/start": "Начать",
    "/help": "Что я умею",
    "/quiet": "Не писать первой",
    "/active": "Писать активнее",
}

HELP_TEXT = (
    "Я Mirror — твой персональный AI-компаньон.\n\n"
    "Умею:\n"
    "• Составить натальную карту и разобрать транзиты\n"
    "• Сделать расклад Таро\n"
    "• Провести утренний ритуал\n\n"
    "/quiet — не пишу первой\n"
    "/active — возвращаю активный режим"
)


@asynccontextmanager
async def typing_action(bot: Bot, chat_id: int):
    """Continuously sends 'typing' action until the context exits."""
    async def _keep_typing():
        while True:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass
            await asyncio.sleep(4)

    task = asyncio.create_task(_keep_typing())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def make_handlers_router(adapter, dialog_service, bot: Bot) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def handle_start(message: Message) -> None:
        unified = await adapter.to_unified(message, is_new_start=True)
        async with typing_action(bot, message.chat.id):
            response = await dialog_service.handle(unified)
        await adapter.send(response, bot)

    @router.message(Command("help"))
    async def handle_help(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("quiet"))
    async def handle_quiet(message: Message) -> None:
        unified = await adapter.to_unified(message)
        unified.text = "/quiet"
        async with typing_action(bot, message.chat.id):
            response = await dialog_service.handle(unified)
        await adapter.send(response, bot)

    @router.message(Command("active"))
    async def handle_active(message: Message) -> None:
        unified = await adapter.to_unified(message)
        unified.text = "/active"
        async with typing_action(bot, message.chat.id):
            response = await dialog_service.handle(unified)
        await adapter.send(response, bot)

    @router.message()
    async def handle_message(message: Message) -> None:
        try:
            unified = await adapter.to_unified(message)
            async with typing_action(bot, message.chat.id):
                response = await dialog_service.handle(unified)
            await adapter.send(response, bot)
        except AllModelsUnavailableError:
            await message.answer("Сейчас немного занята, вернусь через минуту ✨")
        except QuotaExceededError:
            await message.answer("Достигла дневного лимита. Приходи завтра 💫")
        except Exception:
            logger.exception(
                "handle_message.error",
                user_id=str(message.from_user.id),
            )
            await message.answer("Что-то пошло не так, попробуй ещё раз 🙏")

    @router.callback_query(lambda c: c.data and c.data.startswith("action:"))
    async def handle_callback(callback: CallbackQuery) -> None:
        action = callback.data.removeprefix("action:")
        unified = await adapter.callback_to_unified(callback, action)
        async with typing_action(bot, callback.message.chat.id):
            response = await dialog_service.handle(unified)
        await callback.answer()
        await adapter.send(response, bot)

    return router
