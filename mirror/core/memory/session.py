import json
import time
from uuid import UUID

SESSION_TTL = 172800  # 48 hours
MAX_MESSAGES = 20
KEY_PREFIX = "mem_l1"
META_PREFIX = "mem_l1_meta"
SESSION_IDLE_SECONDS = 10800  # 3 hours — session boundary


def _key(user_id: UUID) -> str:
    return f"{KEY_PREFIX}:{user_id}"


def _meta_key(user_id: UUID) -> str:
    return f"{META_PREFIX}:{user_id}"


async def get_session_history(redis, user_id: UUID, max_messages: int = MAX_MESSAGES) -> list[dict]:
    raw = await redis.lrange(_key(user_id), -max_messages, -1)
    return [json.loads(item) for item in raw]


async def get_session_meta(redis, user_id: UUID) -> dict | None:
    raw = await redis.get(_meta_key(user_id))
    if raw:
        return json.loads(raw)
    return None


async def set_session_meta(redis, user_id: UUID, session_id: str) -> None:
    meta = {"session_id": session_id, "last_active_at": time.time()}
    await redis.set(_meta_key(user_id), json.dumps(meta), ex=SESSION_TTL)


async def add_to_session(redis, user_id: UUID, role: str, text: str) -> None:
    key = _key(user_id)
    entry = json.dumps({"role": role, "content": text})
    # pipeline() is sync in redis.asyncio; commands are sync, execute() is async
    async with redis.pipeline() as pipe:
        pipe.rpush(key, entry)
        pipe.ltrim(key, -MAX_MESSAGES, -1)
        pipe.expire(key, SESSION_TTL)
        await pipe.execute()
