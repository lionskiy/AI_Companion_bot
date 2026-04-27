import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

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
    "/cancel": "Отменить практику",
    "/quiet": "Не писать первой",
    "/active": "Писать активнее",
    "/dream": "Интерпретация сна",
    "/numerology": "Нумерология",
}

HELP_TEXT = (
    "Я Mirror — твой персональный AI-компаньон.\n\n"
    "Умею:\n"
    "• Составить натальную карту и разобрать транзиты\n"
    "• Сделать расклад Таро\n"
    "• Провести утренний ритуал\n"
    "• Интерпретировать сны\n"
    "• Рассчитать нумерологию\n"
    "• Психологические практики (CBT, колесо жизни, ценности)\n"
    "• Вести дневник и вечерние рефлексии\n\n"
    "/cancel — отменить текущую практику\n"
    "/quiet — не пишу первой\n"
    "/active — возвращаю активный режим"
)


@asynccontextmanager
async def typing_action(bot: Bot, chat_id: int):
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


def make_handlers_router(
    adapter,
    dialog_service,
    redis_client=None,
    golden_moment_service=None,
    busy_behavior=None,
    psychology_service=None,
) -> Router:
    router = Router()

    async def _get_uid(message: Message) -> UUID | None:
        try:
            unified = await adapter.to_unified(message)
            return UUID(unified.global_user_id)
        except Exception:
            return None

    async def _update_user_presence(uid: UUID) -> None:
        if redis_client is None:
            return
        try:
            await redis_client.setex(
                f"user:last_message_time:{uid}",
                2592000,
                datetime.utcnow().isoformat(),
            )
            from mirror.services.proactive.orchestrator import _update_ignored_streak
            await _update_ignored_streak(uid)
        except Exception:
            pass

    @router.message(CommandStart())
    async def handle_start(message: Message, bot: Bot) -> None:
        unified = await adapter.to_unified(message, is_new_start=True)
        if redis_client:
            try:
                await _update_user_presence(UUID(unified.global_user_id))
            except Exception:
                pass
        async with typing_action(bot, message.chat.id):
            response = await dialog_service.handle(unified)
        await adapter.send(response, bot)

    @router.message(Command("help"))
    async def handle_help(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("cancel"))
    async def handle_cancel(message: Message, bot: Bot) -> None:
        uid = await _get_uid(message)
        if uid and psychology_service is not None:
            try:
                await psychology_service.cancel(uid)
            except Exception:
                pass
        await message.answer("Хорошо, практика отменена. Чем могу помочь?")

    @router.message(Command("quiet"))
    async def handle_quiet(message: Message, bot: Bot) -> None:
        uid = await _get_uid(message)
        if uid:
            try:
                from sqlalchemy import update
                import mirror.db.session as db_module
                from mirror.models.user import UserProfile
                async with db_module.async_session_factory() as session:
                    await session.execute(
                        update(UserProfile)
                        .where(UserProfile.user_id == uid)
                        .values(proactive_mode="quiet", journal_notifications_enabled=False)
                    )
                    await session.commit()
            except Exception:
                logger.warning("handlers.quiet_failed", user_id=str(uid))
        await message.answer("Понял, буду тише. Напиши /active чтобы включить снова.")

    @router.message(Command("active"))
    async def handle_active(message: Message, bot: Bot) -> None:
        uid = await _get_uid(message)
        if uid:
            try:
                from sqlalchemy import update
                import mirror.db.session as db_module
                from mirror.models.user import UserProfile
                async with db_module.async_session_factory() as session:
                    await session.execute(
                        update(UserProfile)
                        .where(UserProfile.user_id == uid)
                        .values(proactive_mode="active", journal_notifications_enabled=True)
                    )
                    await session.commit()
            except Exception:
                logger.warning("handlers.active_failed", user_id=str(uid))
        await message.answer("Отлично! Буду на связи активнее 😊")

    @router.message(Command("dream"))
    async def handle_dream(message: Message, bot: Bot) -> None:
        unified = await adapter.to_unified(message)
        if not unified.text or unified.text.strip() == "/dream":
            await message.answer("Расскажи свой сон — я помогу разобраться в символах и смысле.")
            return
        async with typing_action(bot, message.chat.id):
            response = await dialog_service.handle(unified)
        await adapter.send(response, bot)

    @router.message(Command("numerology"))
    async def handle_numerology(message: Message, bot: Bot) -> None:
        unified = await adapter.to_unified(message)
        unified.text = message.text or "/numerology"
        async with typing_action(bot, message.chat.id):
            response = await dialog_service.handle(unified)
        await adapter.send(response, bot)

    @router.message()
    async def handle_message(message: Message, bot: Bot) -> None:
        try:
            unified = await adapter.to_unified(message)
            uid = UUID(unified.global_user_id)

            await _update_user_presence(uid)

            # BusyBehavior intercept (Plus/Pro only)
            if busy_behavior is not None:
                if await busy_behavior.maybe_intercept(uid, unified.text, bot, message.chat.id):
                    return

            async with typing_action(bot, message.chat.id):
                response = await dialog_service.handle(unified)
            await adapter.send(response, bot)

            # Golden moment — send as second message if pending
            if golden_moment_service is not None:
                try:
                    if await golden_moment_service.is_pending(uid):
                        insight = await golden_moment_service.build_insight(uid)
                        if await golden_moment_service.mark_shown(uid):
                            from mirror.services.dialog import get_app_config
                            cta = get_app_config(
                                "golden_moment_cta",
                                "Ты удивительный человек. Хочешь, я буду лучше тебя понимать?",
                            )
                            await bot.send_message(message.chat.id, f"{insight}\n\n{cta}")
                except Exception:
                    logger.warning("golden_moment.delivery_failed", user_id=str(uid))

        except AllModelsUnavailableError:
            await message.answer("Сейчас немного занята, вернусь через минуту ✨")
        except QuotaExceededError:
            await message.answer("Достигла дневного лимита. Приходи завтра 💫")
        except Exception:
            logger.exception("handle_message.error", user_id=str(message.from_user.id))
            await message.answer("Что-то пошло не так, попробуй ещё раз 🙏")

    @router.callback_query(lambda c: c.data and c.data.startswith("action:"))
    async def handle_callback(callback: CallbackQuery, bot: Bot) -> None:
        action = callback.data.removeprefix("action:")
        unified = await adapter.callback_to_unified(callback, action)
        async with typing_action(bot, callback.message.chat.id):
            response = await dialog_service.handle(unified)
        await callback.answer()
        await adapter.send(response, bot)

    return router
