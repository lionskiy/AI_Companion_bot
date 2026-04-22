import pytest
from sqlalchemy import select

from mirror.core.identity.jwt_handler import create_token, verify_token
from mirror.core.identity.service import IdentityService
from mirror.models.user import Subscription, UserProfile

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def service():
    return IdentityService()


async def test_get_or_create_new_user(service):
    user_id, is_new = await service.get_or_create("telegram", "tg_test_001")
    assert is_new is True
    assert user_id is not None


async def test_get_or_create_idempotent(service):
    uid1, _ = await service.get_or_create("telegram", "tg_test_002")
    uid2, is_new = await service.get_or_create("telegram", "tg_test_002")
    assert uid1 == uid2
    assert is_new is False


async def test_user_profile_created(service, db_session):
    user_id, _ = await service.get_or_create("telegram", "tg_test_003")
    result = await db_session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    assert profile is not None


async def test_subscription_created(service, db_session):
    user_id, _ = await service.get_or_create("telegram", "tg_test_004")
    result = await db_session.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.is_active == True,
        )
    )
    sub = result.scalar_one_or_none()
    assert sub is not None
    assert sub.tier == "free"


async def test_jwt_roundtrip(service):
    user_id, _ = await service.get_or_create("telegram", "tg_test_005")
    token = create_token(user_id)
    decoded = verify_token(token)
    assert decoded == user_id


async def test_get_user(service):
    user_id, _ = await service.get_or_create("telegram", "tg_test_006")
    user = await service.get_user(user_id)
    assert user is not None
    assert user.subscription == "free"
    assert user.timezone == "Europe/Moscow"
