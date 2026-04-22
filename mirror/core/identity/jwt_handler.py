from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordBearer

from mirror.config import settings

ALGORITHM = "HS256"
TTL_HOURS = 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def create_token(global_user_id: UUID) -> str:
    payload = {
        "sub": str(global_user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TTL_HOURS),
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=ALGORITHM)


def verify_token(token: str) -> UUID:
    try:
        payload = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=[ALGORITHM])
        return UUID(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user_id(token: str = oauth2_scheme) -> UUID:
    """FastAPI dependency — для будущих Web-эндпоинтов (Stage 2)."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_token(token)
