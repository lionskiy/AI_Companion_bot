import uuid
from datetime import datetime
from datetime import timezone as dt_timezone
from uuid import UUID

import structlog
from sqlalchemy import select

import mirror.db.session as db_module
from mirror.models.user import ChannelIdentity, Subscription, User, UserProfile

logger = structlog.get_logger()

LANGUAGE_TIMEZONE_MAP = {
    "ru": "Europe/Moscow",
    "uk": "Europe/Kiev",
    "be": "Europe/Minsk",
    "kk": "Asia/Almaty",
    "en": "UTC",
}


class IdentityService:
    async def get_or_create(
        self,
        channel: str,
        channel_user_id: str,
        timezone: str | None = None,
        language_code: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        is_premium: bool = False,
    ) -> tuple[UUID, bool]:
        """
        Возвращает (global_user_id, is_new).
        При создании: users + channel_identities + user_profiles + subscriptions в одной транзакции.
        При повторном вызове — обновляет TG-метаданные если они изменились.
        """
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(ChannelIdentity).where(
                    ChannelIdentity.channel == channel,
                    ChannelIdentity.channel_user_id == channel_user_id,
                )
            )
            identity = result.scalar_one_or_none()
            if identity:
                # Update metadata if changed
                changed = (
                    identity.first_name != first_name
                    or identity.last_name != last_name
                    or identity.username != username
                    or identity.is_premium != is_premium
                )
                if changed:
                    identity.first_name = first_name
                    identity.last_name = last_name
                    identity.username = username
                    identity.is_premium = is_premium
                    identity.meta_updated_at = datetime.now(dt_timezone.utc).replace(tzinfo=None)
                    await session.commit()
                return identity.global_user_id, False

            # Определить timezone
            tz = timezone or LANGUAGE_TIMEZONE_MAP.get(language_code or "", "Europe/Moscow")

            # Создать всё в одной транзакции
            user = User(
                user_id=uuid.uuid4(),
                subscription="free",
                timezone=tz,
                language_code=language_code,
            )
            session.add(user)
            await session.flush()

            session.add(ChannelIdentity(
                channel=channel,
                channel_user_id=channel_user_id,
                global_user_id=user.user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                is_premium=is_premium,
                meta_updated_at=datetime.now(dt_timezone.utc).replace(tzinfo=None),
            ))
            session.add(UserProfile(user_id=user.user_id))
            session.add(Subscription(user_id=user.user_id, tier="free", is_active=True))

            await session.commit()
            logger.info("identity.user_created", user_id=str(user.user_id), channel=channel)
            return user.user_id, True

    async def get_user(self, global_user_id: UUID) -> User | None:
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.user_id == global_user_id)
            )
            return result.scalar_one_or_none()

    async def update_timezone(self, global_user_id: UUID, timezone: str) -> None:
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(User).where(User.user_id == global_user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.timezone = timezone
                await session.commit()
