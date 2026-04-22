import asyncio
from datetime import date, timezone, datetime
from uuid import UUID

import structlog
from sqlalchemy import select, text

import mirror.db.session as db_module
from mirror.db.session import ensure_db_pool, get_session
from mirror.models.user import UserProfile
from mirror.workers.celery_app import celery_app

logger = structlog.get_logger()


def _get_services():
    from mirror.core.llm.router import LLMRouter
    from mirror.services.astrology import AstrologyService
    from mirror.services.daily_ritual import DailyRitualService
    from mirror.services.tarot import TarotService
    llm = LLMRouter()
    tarot = TarotService(llm_router=llm)
    astro = AstrologyService(llm_router=llm)
    return DailyRitualService(tarot_service=tarot, astrology_service=astro, llm_router=llm)


@celery_app.task(name="mirror.workers.tasks.daily_ritual.send_daily_rituals", bind=True, max_retries=3)
def send_daily_rituals(self):
    asyncio.run(_dispatch_all_rituals())


async def _dispatch_all_rituals():
    await ensure_db_pool()
    now_utc = datetime.now(timezone.utc)
    current_hour = now_utc.hour

    async with get_session() as session:
        result = await session.execute(
            select(UserProfile.user_id, UserProfile.timezone).where(
                UserProfile.daily_ritual_enabled == True  # noqa: E712
            )
        )
        profiles = result.all()

    for user_id, tz_name in profiles:
        send_ritual_to_user.delay(str(user_id), current_hour, tz_name or "Europe/Moscow")


@celery_app.task(
    name="mirror.workers.tasks.daily_ritual.send_ritual_to_user",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_ritual_to_user(self, user_id_str: str, dispatch_hour: int, tz_name: str):
    asyncio.run(_send_ritual(user_id_str, dispatch_hour, tz_name))


async def _send_ritual(user_id_str: str, dispatch_hour: int, tz_name: str):
    await ensure_db_pool()
    import zoneinfo

    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("Europe/Moscow")

    local_now = datetime.now(tz)
    if local_now.hour != 7:
        return

    user_id = UUID(user_id_str)
    ritual_date = local_now.date()

    already_sent = await _check_already_sent(user_id, ritual_date)
    if already_sent:
        return

    svc = _get_services()
    ritual = await svc.build_ritual(user_id, state=None)
    message = svc.format_ritual_message(ritual)

    await _log_ritual(user_id, ritual_date, ritual)
    await _deliver(user_id, message)


async def _check_already_sent(user_id: UUID, ritual_date: date) -> bool:
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM daily_ritual_log "
                "WHERE user_id = :uid AND ritual_date = :d LIMIT 1"
            ),
            {"uid": str(user_id), "d": ritual_date},
        )
        return result.fetchone() is not None


async def _log_ritual(user_id: UUID, ritual_date: date, ritual) -> None:
    transit_info = None
    if ritual.transit:
        transit_info = f"{ritual.transit.planet} в {ritual.transit.sign}"

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO daily_ritual_log (user_id, ritual_date, card_name, transit_info, status) "
                "VALUES (:uid, :d, :card, :transit, 'sent') "
                "ON CONFLICT (user_id, ritual_date) DO NOTHING"
            ),
            {
                "uid": str(user_id),
                "d": ritual_date,
                "card": ritual.card.name,
                "transit": transit_info,
            },
        )
        await session.commit()


async def _deliver(user_id: UUID, message: str) -> None:
    try:
        import httpx
        from mirror.config import settings

        tg_id = await _get_telegram_id(user_id)
        if tg_id is None:
            return
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token.get_secret_value()}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as http:
            await http.post(url, json={"chat_id": tg_id, "text": message, "parse_mode": "Markdown"})
    except Exception:
        logger.warning("daily_ritual.deliver_failed", user_id=str(user_id))


async def _get_telegram_id(user_id: UUID) -> int | None:
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT channel_user_id FROM channel_identities "
                "WHERE global_user_id = :uid AND channel = 'telegram' LIMIT 1"
            ),
            {"uid": str(user_id)},
        )
        row = result.fetchone()
        return int(row[0]) if row else None
