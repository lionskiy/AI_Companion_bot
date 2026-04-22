from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select, text

import mirror.db.session as db_module
from mirror.models.billing import QuotaConfig
from mirror.models.user import Subscription

logger = structlog.get_logger()

_QUOTA_CACHE: dict[str, dict] = {}

_LUA_INCR_QUOTA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local expire_ts = tonumber(ARGV[2])

local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIREAT', key, expire_ts)
end
if current > limit then
    return -1
end
return current
"""


class QuotaExceededError(Exception):
    def __init__(self, tier: str, quota_type: str):
        self.tier = tier
        self.quota_type = quota_type
        super().__init__(f"Quota exceeded: {quota_type} for tier {tier}")


class BillingService:
    def __init__(self, redis) -> None:
        self._redis = redis

    async def get_tier(self, user_id: UUID) -> str:
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(Subscription.tier).where(
                    Subscription.user_id == user_id,
                    Subscription.is_active == True,  # noqa: E712
                )
            )
            row = result.scalar_one_or_none()
            return row or "free"

    async def check_quota(self, user_id: UUID, tier: str, quota_type: str = "messages") -> None:
        quota = await self._get_quota_config(tier)
        limit = self._quota_limit(quota, quota_type)

        key = f"quota:{user_id}:{quota_type}:{_today_str()}"
        expire_ts = _midnight_ts()

        result = await self._redis.eval(_LUA_INCR_QUOTA, 1, key, limit, expire_ts)
        if result == -1:
            raise QuotaExceededError(tier=tier, quota_type=quota_type)

    async def create_free_subscription(self, user_id: UUID) -> Subscription:
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.user_id == user_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing

            sub = Subscription(
                user_id=user_id,
                tier="free",
                is_active=True,
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            return sub

    async def get_remaining_quota(self, user_id: UUID, tier: str, quota_type: str = "messages") -> int:
        quota = await self._get_quota_config(tier)
        limit = self._quota_limit(quota, quota_type)
        key = f"quota:{user_id}:{quota_type}:{_today_str()}"
        used = await self._redis.get(key)
        used_int = int(used) if used else 0
        return max(0, limit - used_int)

    async def _get_quota_config(self, tier: str) -> dict:
        if tier in _QUOTA_CACHE:
            return _QUOTA_CACHE[tier]
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(QuotaConfig).where(QuotaConfig.tier == tier)
            )
            row = result.scalar_one_or_none()
            if row is None:
                cfg = {"daily_messages": 20, "tarot_per_day": 3, "astrology_per_day": 3}
            else:
                cfg = {
                    "daily_messages": row.daily_messages,
                    "tarot_per_day": row.tarot_per_day,
                    "astrology_per_day": row.astrology_per_day,
                }
            _QUOTA_CACHE[tier] = cfg
            return cfg

    @staticmethod
    def _quota_limit(quota: dict, quota_type: str) -> int:
        mapping = {
            "messages": "daily_messages",
            "tarot": "tarot_per_day",
            "astrology": "astrology_per_day",
        }
        return quota.get(mapping.get(quota_type, "daily_messages"), 20)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _midnight_ts() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow.timestamp())


def invalidate_quota_cache() -> None:
    _QUOTA_CACHE.clear()
