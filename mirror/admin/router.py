import asyncio
import csv as csv_mod
import os
import io
import json
import time
import uuid as uuid_module
import zipfile
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Header, Request, UploadFile
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, PointIdsList
from sqlalchemy import func, select, text, update

import mirror.db.session as db_module
from mirror.admin.schemas import (
    AppConfigEntry,
    KBCreateCollectionRequest,
    AppConfigUpdate,
    KBAddRequest,
    KBDatasetIngestRequest,
    KBEntryPreview,
    KBIngestResult,
    KBIngestURLRequest,
    KBStatsEntry,
    LLMRoutingUpdate,
    LLMRoutingView,
    IngestProgressResponse,
    IngestLogEntry,
    QuotaConfigUpdate,
    QuotaConfigView,
    StatsView,
    UserAdminView,
)
from mirror.config import settings
from mirror.models.billing import QuotaConfig
from mirror.models.user import Subscription
from mirror.models.llm import LLMRouting
from mirror.models.user import UserProfile
from mirror.services.billing import invalidate_quota_cache
from mirror.services.dialog import invalidate_app_config_cache

from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


def _verify_token(x_admin_token: str = Header(...)):
    if x_admin_token != settings.admin_token.get_secret_value():
        raise HTTPException(status_code=403, detail="Forbidden")


class _LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def admin_login(body: _LoginRequest):
    ok = (
        body.username == settings.admin_username
        and body.password == settings.admin_password.get_secret_value()
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return {"token": settings.admin_token.get_secret_value()}


# ── app_config ────────────────────────────────────────────────────────────────

@router.get("/config", response_model=list[AppConfigEntry], dependencies=[Depends(_verify_token)])
async def list_config():
    async with db_module.async_session_factory() as session:
        result = await session.execute(text("SELECT key, value FROM app_config ORDER BY key"))
        return [AppConfigEntry(key=row.key, value=row.value) for row in result]


@router.put("/config/{key}", response_model=AppConfigEntry, dependencies=[Depends(_verify_token)])
async def update_config(key: str, body: AppConfigUpdate):
    async with db_module.async_session_factory() as session:
        existing = await session.execute(
            text("SELECT 1 FROM app_config WHERE key = :key"), {"key": key}
        )
        if not existing.fetchone():
            raise HTTPException(status_code=404, detail="Config key not found")
        await session.execute(
            text("UPDATE app_config SET value = :value WHERE key = :key"),
            {"key": key, "value": body.value},
        )
        await session.commit()
    invalidate_app_config_cache()
    logger.info("admin.config.updated", key=key)
    return AppConfigEntry(key=key, value=body.value)


# ── quota_config ──────────────────────────────────────────────────────────────

@router.get("/quota", response_model=list[QuotaConfigView], dependencies=[Depends(_verify_token)])
async def list_quota():
    async with db_module.async_session_factory() as session:
        result = await session.execute(select(QuotaConfig))
        rows = result.scalars().all()
        return [
            QuotaConfigView(
                tier=r.tier,
                daily_messages=r.daily_messages,
                tarot_per_day=r.tarot_per_day,
                astrology_per_day=r.astrology_per_day,
            )
            for r in rows
        ]


@router.put("/quota/{tier}", response_model=QuotaConfigView, dependencies=[Depends(_verify_token)])
async def update_quota(tier: str, body: QuotaConfigUpdate):
    async with db_module.async_session_factory() as session:
        result = await session.execute(select(QuotaConfig).where(QuotaConfig.tier == tier))
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Tier not found")
        if body.daily_messages is not None:
            row.daily_messages = body.daily_messages
        if body.tarot_per_day is not None:
            row.tarot_per_day = body.tarot_per_day
        if body.astrology_per_day is not None:
            row.astrology_per_day = body.astrology_per_day
        await session.commit()
        await session.refresh(row)
    invalidate_quota_cache()
    logger.info("admin.quota.updated", tier=tier)
    return QuotaConfigView(
        tier=row.tier,
        daily_messages=row.daily_messages,
        tarot_per_day=row.tarot_per_day,
        astrology_per_day=row.astrology_per_day,
    )


# ── llm_routing ───────────────────────────────────────────────────────────────

@router.get("/routing", response_model=list[LLMRoutingView], dependencies=[Depends(_verify_token)])
async def list_routing():
    async with db_module.async_session_factory() as session:
        result = await session.execute(select(LLMRouting).order_by(LLMRouting.task_kind))
        rows = result.scalars().all()
        return [
            LLMRoutingView(
                task_kind=r.task_kind,
                tier=r.tier,
                provider_id=r.provider_id,
                model_id=r.model_id,
                fallback_chain=r.fallback_chain or [],
                max_tokens=r.max_tokens,
                temperature=float(r.temperature),
            )
            for r in rows
        ]


@router.put("/routing/{task_kind}", response_model=LLMRoutingView, dependencies=[Depends(_verify_token)])
async def update_routing(task_kind: str, body: LLMRoutingUpdate):
    async with db_module.async_session_factory() as session:
        result = await session.execute(
            select(LLMRouting).where(LLMRouting.task_kind == task_kind)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="task_kind not found")
        if body.provider_id is not None:
            row.provider_id = body.provider_id
        if body.model_id is not None:
            row.model_id = body.model_id
        if body.fallback_chain is not None:
            row.fallback_chain = body.fallback_chain
        if body.max_tokens is not None:
            row.max_tokens = body.max_tokens
        if body.temperature is not None:
            row.temperature = body.temperature
        await session.commit()
        await session.refresh(row)

    from mirror.core.llm.router import LLMRouter
    LLMRouter._routing_cache.clear()
    logger.info("admin.routing.updated", task_kind=task_kind)
    return LLMRoutingView(
        task_kind=row.task_kind,
        tier=row.tier,
        provider_id=row.provider_id,
        model_id=row.model_id,
        fallback_chain=row.fallback_chain or [],
        max_tokens=row.max_tokens,
        temperature=float(row.temperature),
    )


# ── LLM API keys ──────────────────────────────────────────────────────────────

_LLM_PROVIDERS: dict[str, dict] = {
    "openai":     {"label": "OpenAI",         "env": "OPENAI_API_KEY",       "color": "#10a37f", "placeholder": "sk-..."},
    "anthropic":  {"label": "Anthropic",       "env": "ANTHROPIC_API_KEY",    "color": "#d97706", "placeholder": "sk-ant-..."},
    "google":     {"label": "Google Gemini",   "env": "GOOGLE_API_KEY",       "color": "#4285f4", "placeholder": "AIza..."},
    "mistral":    {"label": "Mistral AI",      "env": "MISTRAL_API_KEY",      "color": "#ff7000", "placeholder": "..."},
    "groq":       {"label": "Groq",            "env": "GROQ_API_KEY",         "color": "#f55036", "placeholder": "gsk_..."},
    "cohere":     {"label": "Cohere",          "env": "COHERE_API_KEY",       "color": "#39594d", "placeholder": "..."},
    "together":   {"label": "Together AI",     "env": "TOGETHER_API_KEY",     "color": "#7c3aed", "placeholder": "..."},
    "perplexity": {"label": "Perplexity",      "env": "PERPLEXITY_API_KEY",   "color": "#20b2aa", "placeholder": "pplx-..."},
    "xai":        {"label": "xAI (Grok)",      "env": "XAI_API_KEY",          "color": "#888888", "placeholder": "xai-..."},
    "deepseek":   {"label": "DeepSeek",        "env": "DEEPSEEK_API_KEY",     "color": "#4169e1", "placeholder": "sk-..."},
    "azure":      {"label": "Azure OpenAI",    "env": "AZURE_OPENAI_API_KEY", "color": "#0089d6", "placeholder": "..."},
    "ollama":     {"label": "Ollama (local)",  "env": "OLLAMA_BASE_URL",      "color": "#666666", "placeholder": "http://localhost:11434"},
}


def _mask_key(val: str) -> str:
    if not val:
        return ""
    return val[:8] + "..." + val[-4:] if len(val) > 12 else "****"


@router.get("/llm-keys", dependencies=[Depends(_verify_token)])
async def get_llm_keys():
    result = {}
    for provider, meta in _LLM_PROVIDERS.items():
        val = os.environ.get(meta["env"], "")
        result[provider] = _mask_key(val) if val else ""
    return {
        "keys": result,
        "providers": {k: {"label": v["label"], "color": v["color"], "placeholder": v["placeholder"]}
                      for k, v in _LLM_PROVIDERS.items()},
    }


@router.put("/llm-keys/{provider}", dependencies=[Depends(_verify_token)])
async def set_llm_key(provider: str, request: Request):
    body = await request.json()
    key = body.get("key", "").strip()
    if provider not in _LLM_PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider!r}")
    if not key:
        raise HTTPException(400, "key must not be empty")
    os.environ[_LLM_PROVIDERS[provider]["env"]] = key
    from mirror.core.llm.router import LLMRouter
    LLMRouter._routing_cache.clear()
    LLMRouter._provider_cache.clear()
    logger.info("admin.llm_key.updated", provider=provider)
    return {"updated": provider}


@router.delete("/llm-keys/{provider}", dependencies=[Depends(_verify_token)])
async def delete_llm_key(provider: str):
    if provider not in _LLM_PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider!r}")
    env_var = _LLM_PROVIDERS[provider]["env"]
    os.environ.pop(env_var, None)
    from mirror.core.llm.router import LLMRouter
    LLMRouter._routing_cache.clear()
    LLMRouter._provider_cache.clear()
    logger.info("admin.llm_key.deleted", provider=provider)
    return {"deleted": provider}


# ── Telegram bots ─────────────────────────────────────────────────────────────

def _mask_tg_token(token: str) -> str:
    if not token:
        return ""
    colon = token.find(":")
    return (token[:colon + 5] + "..." + token[-4:]) if colon > 0 else _mask_key(token)


def _ensure_tg_bots(app_state) -> list:
    if not hasattr(app_state, "tg_bots"):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "") or settings.telegram_bot_token.get_secret_value()
        if token:
            from aiogram import Bot as AiogramBot
            from aiogram.client.default import DefaultBotProperties
            bot_obj = AiogramBot(token=token, default=DefaultBotProperties(parse_mode=None))
            app_state.tg_bots = [{"name": "Основной", "token": token, "username": None,
                                   "tg_id": None, "bot_obj": bot_obj, "active": True}]
        else:
            app_state.tg_bots = []
    return app_state.tg_bots


async def _do_register_bot(request: Request, name: str, token: str) -> dict:
    """Validate token, set per-bot webhook, add/update entry in tg_bots list."""
    from aiogram import Bot as AiogramBot
    from aiogram.client.default import DefaultBotProperties
    try:
        new_bot = AiogramBot(token=token, default=DefaultBotProperties(parse_mode=None))
        me = await new_bot.get_me()
    except Exception as e:
        raise HTTPException(400, f"Telegram отверг токен: {e}")

    if not settings.polling_mode:
        _secret = settings.telegram_webhook_secret.get_secret_value()
        webhook_url = f"{settings.base_url}/webhook/telegram/{me.id}/{_secret}"
        await new_bot.set_webhook(webhook_url, secret_token=_secret)

    bots = _ensure_tg_bots(request.app.state)
    # Remove any stale entry with same name or same tg_id
    request.app.state.tg_bots = [
        b for b in bots if b["name"] != name and b.get("tg_id") != me.id
    ]
    request.app.state.tg_bots.append({
        "name": name, "token": token, "username": me.username,
        "tg_id": me.id, "bot_obj": new_bot, "active": True,
    })
    # Keep app.state.bot pointing to most recently registered bot
    request.app.state.bot = new_bot
    return {"username": me.username, "id": me.id}


@router.get("/tg-bots", dependencies=[Depends(_verify_token)])
async def list_tg_bots(request: Request):
    bots = _ensure_tg_bots(request.app.state)
    return {"bots": [
        {"name": b["name"], "masked": _mask_tg_token(b["token"]),
         "username": b.get("username"), "active": b.get("active", True),
         "tg_id": b.get("tg_id")}
        for b in bots
    ]}


@router.post("/tg-bots", dependencies=[Depends(_verify_token)])
async def add_tg_bot(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    token = body.get("token", "").strip()
    if not name:
        raise HTTPException(400, "Укажи название бота")
    if not token or ":" not in token:
        raise HTTPException(400, "Некорректный токен")
    bots = _ensure_tg_bots(request.app.state)
    if any(b["name"] == name for b in bots):
        raise HTTPException(400, f"Бот '{name}' уже существует")
    info = await _do_register_bot(request, name, token)
    logger.info("admin.tg_bot.added", name=name, username=info["username"])
    return {"added": True, "activated": True, "username": info["username"]}


@router.put("/tg-bots/{name}/activate", dependencies=[Depends(_verify_token)])
async def activate_tg_bot(name: str, request: Request):
    """Re-register webhook for a bot (useful if webhook was lost)."""
    bots = _ensure_tg_bots(request.app.state)
    entry = next((b for b in bots if b["name"] == name), None)
    if not entry:
        raise HTTPException(404, "Бот не найден")
    info = await _do_register_bot(request, name, entry["token"])
    logger.info("admin.tg_bot.reactivated", name=name, username=info["username"])
    return {"activated": True, "username": info["username"]}


@router.delete("/tg-bots/{name}", dependencies=[Depends(_verify_token)])
async def remove_tg_bot(name: str, request: Request):
    bots = _ensure_tg_bots(request.app.state)
    entry = next((b for b in bots if b["name"] == name), None)
    if not entry:
        raise HTTPException(404, "Бот не найден")
    bot_obj = entry.get("bot_obj")
    if bot_obj:
        try:
            await bot_obj.delete_webhook(drop_pending_updates=False)
        except Exception:
            pass
        try:
            await bot_obj.session.close()
        except Exception:
            pass
    request.app.state.tg_bots = [b for b in bots if b["name"] != name]
    # If deleted bot was app.state.bot, switch to next available
    if bot_obj and bot_obj is getattr(request.app.state, "bot", None):
        remaining = request.app.state.tg_bots
        if remaining:
            request.app.state.bot = remaining[-1].get("bot_obj") or request.app.state.bot
    logger.info("admin.tg_bot.removed", name=name)
    return {"removed": True}


# ── LLM model lists ───────────────────────────────────────────────────────────

# Static Anthropic models — no public list API
_ANTHROPIC_MODELS = [
    {"id": "claude-opus-4-7",              "label": "Claude Opus 4.7 (latest)"},
    {"id": "claude-sonnet-4-6",            "label": "Claude Sonnet 4.6"},
    {"id": "claude-haiku-4-5-20251001",    "label": "Claude Haiku 4.5"},
    {"id": "claude-3-5-sonnet-20241022",   "label": "Claude 3.5 Sonnet"},
    {"id": "claude-3-5-haiku-20241022",    "label": "Claude 3.5 Haiku"},
    {"id": "claude-3-opus-20240229",       "label": "Claude 3 Opus"},
]

_OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "text-embedding-")


@router.get("/llm-models", dependencies=[Depends(_verify_token)])
async def list_llm_models(provider: str = "openai"):
    if provider == "anthropic":
        return {"provider": "anthropic", "models": _ANTHROPIC_MODELS}

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return {"provider": "openai", "models": [], "error": "Ключ не задан"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return {"provider": "openai", "models": [], "error": str(e)}

        models = sorted(
            [
                {"id": m["id"], "label": m["id"]}
                for m in data.get("data", [])
                if any(m["id"].startswith(p) for p in _OPENAI_MODEL_PREFIXES)
            ],
            key=lambda x: x["id"],
        )
        return {"provider": "openai", "models": models}

    raise HTTPException(400, f"Unknown provider: {provider!r}")


# ── users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserAdminView], dependencies=[Depends(_verify_token)])
async def list_users(limit: int = 50, offset: int = 0):
    async with db_module.async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT u.user_id, "
                "COALESCE(s.tier,'free') as tier, "
                "COALESCE(p.daily_ritual_enabled, true) as daily_ritual_enabled, "
                "u.created_at, "
                "ci.first_name, ci.last_name, ci.username as tg_username, "
                "COALESCE(ci.is_premium, false) as is_premium "
                "FROM users u "
                "LEFT JOIN subscriptions s ON s.user_id = u.user_id AND s.is_active "
                "LEFT JOIN user_profiles p ON p.user_id = u.user_id "
                "LEFT JOIN channel_identities ci ON ci.global_user_id = u.user_id AND ci.channel = 'telegram' "
                "ORDER BY u.created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"limit": limit, "offset": offset},
        )
        rows = result.fetchall()
        return [
            UserAdminView(
                user_id=row.user_id,
                username=row.tg_username,
                full_name=" ".join(filter(None, [row.first_name, row.last_name])) or None,
                tg_username=row.tg_username,
                is_premium=row.is_premium,
                tier=row.tier,
                daily_ritual_enabled=row.daily_ritual_enabled,
                created_at=str(row.created_at),
            )
            for row in rows
        ]


@router.put("/users/{user_id}/ritual", dependencies=[Depends(_verify_token)])
async def toggle_ritual(user_id: str, enabled: bool):
    from uuid import UUID
    uid = UUID(user_id)
    async with db_module.async_session_factory() as session:
        await session.execute(
            text("UPDATE user_profiles SET daily_ritual_enabled = :val WHERE user_id = :uid"),
            {"val": enabled, "uid": str(uid)},
        )
        await session.commit()
    return {"user_id": user_id, "daily_ritual_enabled": enabled}


# ── stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsView, dependencies=[Depends(_verify_token)])
async def get_stats(request: Request):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async with db_module.async_session_factory() as session:
        total = (await session.execute(text("SELECT COUNT(*) FROM users"))).scalar()
        rituals_today = (
            await session.execute(
                text("SELECT COUNT(*) FROM daily_ritual_log WHERE ritual_date = CURRENT_DATE")
            )
        ).scalar()
        intent_rows = (await session.execute(
            text("""
                SELECT intent, COUNT(*) as cnt
                FROM intent_log
                WHERE created_at::date = CURRENT_DATE
                GROUP BY intent
            """)
        )).fetchall()

    intent_counts = {row[0]: row[1] for row in intent_rows}

    # Count messages and active users from Redis quota keys: quota:{user_id}:messages:{date}
    messages_today = 0
    active_users: set = set()
    try:
        redis = getattr(request.app.state, "redis", None)
        if redis:
            pattern = f"quota:*:messages:{today}"
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=200)
                for key in keys:
                    val = await redis.get(key)
                    if val:
                        messages_today += int(val)
                        parts = (key.decode() if isinstance(key, bytes) else key)
                        active_users.add(parts.split(":")[1])
                if cursor == 0:
                    break
    except Exception:
        pass

    tarot_today = intent_counts.get("tarot", 0)
    astrology_today = intent_counts.get("astrology", 0)
    rituals_today_int = rituals_today or 0
    # chat = all messages minus specific modes (more accurate than counting only "chat" intent)
    specific_today = tarot_today + astrology_today + rituals_today_int
    chat_today = max(0, messages_today - specific_today)

    return StatsView(
        total_users=total or 0,
        active_today=len(active_users),
        messages_today=messages_today,
        rituals_sent_today=rituals_today_int,
        tarot_today=tarot_today,
        astrology_today=astrology_today,
        chat_today=chat_today,
    )


# ── knowledge base ─────────────────────────────────────────────────────────────

_SYSTEM_COLLECTIONS = {"user_episodes", "user_facts"}


async def _qdrant_kb_names(client) -> list[str]:
    """All Qdrant collections excluding system memory collections, sorted."""
    all_cols = {c.name for c in (await client.get_collections()).collections}
    return sorted(all_cols - _SYSTEM_COLLECTIONS)


async def _qdrant_collection_exists(client, name: str) -> bool:
    all_cols = {c.name for c in (await client.get_collections()).collections}
    return name in all_cols


@router.get("/kb/stats", response_model=list[KBStatsEntry], dependencies=[Depends(_verify_token)])
async def kb_stats():
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        result = []
        for col in await _qdrant_kb_names(client):
            try:
                info = await client.get_collection(col)
                result.append(KBStatsEntry(collection=col, count=info.points_count or 0))
            except Exception:
                result.append(KBStatsEntry(collection=col, count=0))
        return result
    finally:
        await client.close()


@router.get("/kb/entries/{collection}", response_model=list[KBEntryPreview], dependencies=[Depends(_verify_token)])
async def kb_entries(collection: str, limit: int = 30):
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    if not await _qdrant_collection_exists(client, collection):
        await client.close()
        raise HTTPException(status_code=400, detail="Unknown collection")
    try:
        records, _ = await client.scroll(
            collection_name=collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [
            KBEntryPreview(
                point_id=str(r.id),
                topic=r.payload.get("topic", ""),
                text_preview=(r.payload.get("text", ""))[:200],
            )
            for r in records
        ]
    except Exception:
        return []
    finally:
        await client.close()


@router.post("/kb/add", dependencies=[Depends(_verify_token)])
async def kb_add(body: KBAddRequest, request: Request):
    llm_router = getattr(request.app.state, "llm_router", None)
    if llm_router is None:
        raise HTTPException(status_code=503, detail="LLM router not ready")
    embedding = await llm_router.embed(f"{body.topic}\n{body.text}")
    point_id = str(uuid_module.uuid4())
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        await client.upsert(
            collection_name=body.collection,
            points=[PointStruct(
                id=point_id,
                vector=embedding,
                payload={"topic": body.topic, "text": body.text, "collection": body.collection},
            )],
        )
    finally:
        await client.close()
    logger.info("admin.kb.added", collection=body.collection, topic=body.topic)
    return {"point_id": point_id, "collection": body.collection, "topic": body.topic}


@router.delete("/kb/entry/{collection}/{point_id}", dependencies=[Depends(_verify_token)])
async def kb_delete(collection: str, point_id: str):
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        await client.delete(
            collection_name=collection,
            points_selector=PointIdsList(points=[point_id]),
        )
    finally:
        await client.close()
    logger.info("admin.kb.deleted", collection=collection, point_id=point_id)
    return {"deleted": point_id}


@router.post("/kb/collections", dependencies=[Depends(_verify_token)])
async def kb_create_collection(body: KBCreateCollectionRequest):
    """Create a new Qdrant collection and register it in the active list."""
    import re
    name = body.name.strip().lower()
    if not re.match(r"^[a-z][a-z0-9_]{2,49}$", name):
        raise HTTPException(400, "Имя коллекции: только латиница, цифры, _, длина 3–50 символов")
    if name in _SYSTEM_COLLECTIONS:
        raise HTTPException(400, f"Имя {name!r} зарезервировано системой")

    from qdrant_client.models import Distance, VectorParams
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        existing = {c.name for c in (await client.get_collections()).collections}
        if name in existing:
            raise HTTPException(400, f"Коллекция {name!r} уже существует")
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
        )
        logger.info("admin.kb.collection_created", name=name)
    finally:
        await client.close()

    return {"created": name, "registered": True}


@router.delete("/kb/collections/{collection}", dependencies=[Depends(_verify_token)])
async def kb_delete_collection(collection: str, confirm: str = ""):
    """Delete all points in a collection (confirm='yes') or delete the collection entirely (confirm='drop')."""
    if collection in _SYSTEM_COLLECTIONS:
        raise HTTPException(403, "Нельзя удалять системные коллекции памяти пользователей")

    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        if not await _qdrant_collection_exists(client, collection):
            raise HTTPException(404, f"Коллекция {collection!r} не найдена")
        if confirm == "drop":
            await client.delete_collection(collection)
            logger.info("admin.kb.collection_dropped", name=collection)
            return {"dropped": collection}
        elif confirm == "yes":
            # Clear all points but keep collection
            from qdrant_client.models import Filter
            await client.delete(collection_name=collection, points_selector=Filter(must=[]))
            logger.info("admin.kb.collection_cleared", name=collection)
            return {"cleared": collection}
        else:
            raise HTTPException(400, "Передай ?confirm=yes для очистки или ?confirm=drop для удаления коллекции")
    finally:
        await client.close()


@router.get("/kb/collections", dependencies=[Depends(_verify_token)])
async def kb_list_collections():
    """List all Qdrant KB collections (excluding system) with enriched stats."""
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        names = await _qdrant_kb_names(client)
        result = []
        for name in names:
            try:
                info = await client.get_collection(name)
                points = info.points_count or 0
                indexed = info.indexed_vectors_count or 0
                result.append({
                    "name": name,
                    "count": points,
                    "status": str(info.status.value) if info.status else "unknown",
                    "indexed": indexed,
                    "segments": info.segments_count or 0,
                })
            except Exception:
                result.append({"name": name, "count": 0, "status": "unknown", "indexed": 0, "segments": 0})
        return result
    finally:
        await client.close()


@router.get("/kb/hf-search", dependencies=[Depends(_verify_token)])
async def hf_search_datasets(q: str = "", tag: str = "", limit: int = 20):
    """Search HuggingFace dataset catalog."""
    params: dict = {"limit": min(limit, 50), "full": "false"}
    if q:
        params["search"] = q
    if tag:
        params["filter"] = f"tags:{tag}"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(f"{_HF_API}/datasets", params=params)
        r.raise_for_status()
        return [
            {
                "id": d["id"],
                "downloads": d.get("downloads", 0),
                "likes": d.get("likes", 0),
                "tags": [t for t in d.get("tags", []) if not any(t.startswith(p) for p in
                         ("size_", "format:", "library:", "region:", "modality:", "arxiv:"))][:6],
            }
            for d in r.json()
        ]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"HuggingFace API error: {e}")


@router.get("/kb/hf-splits/{repo_owner}/{repo_name}", dependencies=[Depends(_verify_token)])
async def hf_dataset_splits(repo_owner: str, repo_name: str):
    """List all configs/splits for a HuggingFace dataset."""
    repo_id = f"{repo_owner}/{repo_name}"
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(f"{_HF_DS_SERVER}/splits", params={"dataset": repo_id})
        r.raise_for_status()
        splits = r.json().get("splits", [])
        configs = {}
        for s in splits:
            cfg = s.get("config", "default")
            configs.setdefault(cfg, []).append(s.get("split", "train"))
        return {"repo_id": repo_id, "configs": configs, "total_splits": len(splits)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"HuggingFace API error: {e}")


@router.post("/kb/ingest-url", response_model=KBIngestResult, dependencies=[Depends(_verify_token)])
async def kb_ingest_url(body: KBIngestURLRequest, request: Request):
    llm_router = getattr(request.app.state, "llm_router", None)
    if llm_router is None:
        raise HTTPException(status_code=503, detail="LLM router not ready")

    # HuggingFace dataset page → route through HF datasets-server
    if _is_hf_dataset_url(body.url):
        repo_id = _hf_repo_id(body.url)
        from types import SimpleNamespace
        fake = SimpleNamespace(
            collection=body.collection, topic_prefix=body.topic or "",
            question_field="", answer_field="", source_lang=body.source_lang, limit=0,
        )
        total = await _ingest_hf_dataset(repo_id, fake, llm_router)
        return KBIngestResult(chunks_added=total, collection=body.collection, source=body.url)

    # GitHub repo URL → route through full repo ingestion instead of HTML scraping
    if _is_git_repo_url(body.url):
        zip_url_tpl, _ = _github_zip_url(body.url)
        zip_bytes = None
        for branch in ["main", "master"]:
            try_url = zip_url_tpl.replace("{branch}", branch) if "{branch}" in zip_url_tpl else zip_url_tpl
            try:
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
                    resp = await http.get(try_url, headers={"User-Agent": "MirrorBot/1.0"})
                if resp.status_code == 200 and resp.content[:2] == b"PK":
                    zip_bytes = resp.content
                    break
            except Exception:
                continue
        if not zip_bytes:
            raise HTTPException(status_code=400, detail="Не удалось скачать репозиторий (main/master)")
        from types import SimpleNamespace
        fake = SimpleNamespace(
            collection=body.collection, topic_prefix=body.topic or "",
            question_field="", answer_field="", source_lang=body.source_lang, limit=0,
        )
        repo_name = body.url.rstrip("/").split("/")[-1].removesuffix(".git")
        total = await _ingest_repo_zip(zip_bytes, fake, llm_router, repo_name)
        logger.info("admin.kb.ingest_url_repo", collection=body.collection, url=body.url, total=total)
        return KBIngestResult(chunks_added=total, collection=body.collection, source=body.url)

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            resp = await http.get(body.url, headers={"User-Agent": "MirrorBot/1.0"})
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось загрузить URL: {e}")

    text_content = _extract_text_from_bytes(resp.content, filename="page.html", mime=resp.headers.get("content-type", ""))
    if not text_content.strip():
        raise HTTPException(status_code=400, detail="Не удалось извлечь текст со страницы")

    topic = body.topic or _url_to_topic(body.url)
    chunks = _chunk_text(text_content)
    count = await _upsert_chunks_simple(chunks, body.collection, topic, llm_router, body.source_lang)
    logger.info("admin.kb.ingest_url", collection=body.collection, url=body.url, chunks=count)
    return KBIngestResult(chunks_added=count, collection=body.collection, source=body.url)


_RU_TRANSLIT: dict[str, str] = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
    'и':'i','й':'j','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
    'щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}


def _derive_collection_name(filename: str) -> str:
    """Slugify filename (minus extension) into a valid Qdrant collection name."""
    import re
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    s = base.lower()
    s = "".join(_RU_TRANSLIT.get(c, c) for c in s)
    s = re.sub(r"[^a-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if len(s) < 3:
        s = "kb_" + s
    return s[:50]


@router.post("/kb/ingest-file", dependencies=[Depends(_verify_token)])
async def kb_ingest_file(
    request: Request,
    collection: str = Form(""),   # empty → auto-derived from filename
    topic: str = Form(""),
    source_lang: str = Form("auto"),
    file: UploadFile = File(...),
):
    import shutil
    from pathlib import Path

    queue = getattr(request.app.state, "ingest_queue", None)
    if queue is None:
        raise HTTPException(status_code=503, detail="Очередь загрузок не инициализирована")

    filename = file.filename or "upload"
    mime = file.content_type or ""

    # Auto-derive collection from filename if not provided
    if not collection:
        collection = _derive_collection_name(filename)

    # Validate collection name
    import re as _re
    if not _re.match(r"^[a-z][a-z0-9_]{2,49}$", collection):
        raise HTTPException(status_code=400,
                            detail=f"Некорректное имя коллекции: {collection!r} — только латиница, цифры, _")

    # Auto-create collection in Qdrant if it doesn't exist yet
    await _ensure_collection(collection)

    file_topic = topic or filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")

    # Check file size limit before reading
    max_mb = 500
    try:
        async with db_module.async_session_factory() as s:
            row = (await s.execute(text("SELECT value FROM app_config WHERE key='kb_max_zip_size_mb'"))).fetchone()
            if row:
                max_mb = int(row[0])
    except Exception:
        pass

    content = await file.read()
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Файл превышает лимит {max_mb} MB")

    job_id = str(uuid_module.uuid4())

    # Save to disk volume (survives container restart)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    job_dir = Path("/data/ingest") / job_id
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: job_dir.mkdir(parents=True, exist_ok=True))
    orig_name = "original.zip" if filename.lower().endswith(".zip") else f"original.{ext}"
    await loop.run_in_executor(None, (job_dir / orig_name).write_bytes, content)
    tmp_path = str(job_dir)

    async with db_module.async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO ingest_jobs (id, status, stage, filename, collection, "
                "file_mime, file_topic, source_lang, tmp_path, job_type) "
                "VALUES (:id, 'queued', 'upload', :fn, :col, :fm, :ft, :sl, :tp, 'file')"
            ),
            {"id": job_id, "fn": filename, "col": collection,
             "fm": mime, "ft": file_topic, "sl": source_lang, "tp": tmp_path},
        )
        await session.commit()

    await queue.put(job_id)
    logger.info("admin.kb.ingest_job_queued", job_id=job_id, filename=filename, collection=collection)
    return {"job_id": job_id, "status": "queued", "filename": filename, "collection": collection}


async def _ingest_worker(queue: asyncio.Queue, llm_router) -> None:
    """Pull job IDs from queue and process them. Worker loop never dies silently."""
    from mirror.services.ingest.pipeline import run_embed_stage_only, run_ingest_job_v2

    while True:
        job_id: str | None = None
        try:
            job_id = await queue.get()
        except asyncio.CancelledError:
            return

        try:
            async with db_module.async_session_factory() as session:
                row = (await session.execute(
                    text("SELECT filename, collection, file_topic, tmp_path, stage "
                         "FROM ingest_jobs WHERE id=:id AND status='queued'"),
                    {"id": job_id},
                )).fetchone()

            if not row:
                queue.task_done()
                continue

            async with db_module.async_session_factory() as session:
                await session.execute(
                    text("UPDATE ingest_jobs SET status='running', updated_at=now() WHERE id=:id"),
                    {"id": job_id},
                )
                await session.commit()

            if row.stage == "embed":
                # Smart resume: only re-embed pending chunks, skip extraction and chunking
                total = await run_embed_stage_only(job_id=job_id, llm_router=llm_router)
            else:
                total = await run_ingest_job_v2(
                    job_id=job_id,
                    filename=row.filename,
                    collection=row.collection,
                    file_topic=row.file_topic or "",
                    llm_router=llm_router,
                )
            async with db_module.async_session_factory() as session:
                await session.execute(
                    text("UPDATE ingest_jobs SET status='done', stage='done', "
                         "chunks_added=:n, tmp_path=NULL, file_data=NULL, updated_at=now() "
                         "WHERE id=:id AND status='running'"),
                    {"n": total, "id": job_id},
                )
                await session.commit()
            logger.info("admin.kb.ingest_job_done", job_id=job_id, chunks=total)

        except asyncio.CancelledError:
            return
        except Exception as exc:
            err = str(exc)[:500]
            logger.error("ingest_worker.job_failed", job_id=job_id, error=err)
            try:
                async with db_module.async_session_factory() as s:
                    await s.execute(
                        text("UPDATE ingest_jobs SET status='error', error=:e, updated_at=now() "
                             "WHERE id=:id AND status='running'"),
                        {"e": err, "id": job_id},
                    )
                    await s.commit()
            except Exception:
                pass
        finally:
            try:
                queue.task_done()
            except ValueError:
                pass


@router.post("/kb/jobs/{job_id}/cancel", dependencies=[Depends(_verify_token)])
async def cancel_ingest_job(job_id: str):
    async with db_module.async_session_factory() as session:
        result = await session.execute(
            text("UPDATE ingest_jobs SET status='error', error='Отменено пользователем', "
                 "updated_at=now() WHERE id=:id AND status IN ('running', 'queued') RETURNING id"),
            {"id": job_id},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Задача не найдена или уже завершена")
        await session.commit()
    return {"ok": True}


@router.delete("/kb/jobs/{job_id}", dependencies=[Depends(_verify_token)])
async def delete_ingest_job(job_id: str):
    async with db_module.async_session_factory() as session:
        result = await session.execute(
            text("DELETE FROM ingest_jobs WHERE id=:id AND status != 'running' RETURNING id"),
            {"id": job_id},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Задача не найдена или ещё выполняется")
        await session.commit()
    return {"ok": True}


@router.post("/kb/jobs/{job_id}/retry", dependencies=[Depends(_verify_token)])
async def retry_ingest_job(job_id: str, request: Request):
    import os
    queue = getattr(request.app.state, "ingest_queue", None)
    if queue is None:
        raise HTTPException(503, "Очередь загрузок не инициализирована")

    async with db_module.async_session_factory() as session:
        row = (await session.execute(
            text("SELECT tmp_path, status FROM ingest_jobs WHERE id=:id"),
            {"id": job_id},
        )).fetchone()
        if not row:
            raise HTTPException(404, "Задача не найдена")
        if row.status == "running":
            raise HTTPException(409, "Задача выполняется")
        if row.status == "done":
            raise HTTPException(409, "Задача уже завершена")

        # Check for pending chunks — smart embed-only resume
        pending_count = (await session.execute(
            text("SELECT COUNT(*) FROM ingest_chunks WHERE job_id=:jid AND chunk_status='pending'"),
            {"jid": job_id},
        )).scalar() or 0

        if pending_count > 0:
            # Resume from embed stage: keep all chunks and files intact, only re-embed pending ones.
            # Already-done chunks are already in Qdrant — no duplication, no wasted tokens.
            await session.execute(
                text(
                    "UPDATE ingest_jobs SET status='queued', stage='embed', error=NULL, "
                    "updated_at=now() WHERE id=:id"
                ),
                {"id": job_id},
            )
            await session.commit()
        else:
            # No pending chunks: full retry from scratch (re-extract, re-chunk, re-embed)
            tmp_path = row.tmp_path
            if not tmp_path or not os.path.exists(tmp_path):
                raise HTTPException(
                    409,
                    "Файл удалён после завершения задачи. Загрузите файл заново."
                )
            await session.execute(
                text("DELETE FROM ingest_chunks WHERE job_id=:jid"),
                {"jid": job_id},
            )
            await session.execute(
                text("DELETE FROM ingest_files WHERE job_id=:jid"),
                {"jid": job_id},
            )
            await session.execute(
                text(
                    "UPDATE ingest_jobs SET status='queued', stage='upload', error=NULL, "
                    "chunks_done=0, chunks_total=0, files_total=0, files_extracted=0, "
                    "files_chunked=0, enrichment_total=0, enrichment_done=0, qdrant_upserted=0, "
                    "updated_at=now() WHERE id=:id"
                ),
                {"id": job_id},
            )
            await session.commit()

    await queue.put(job_id)
    mode = "embed_resume" if pending_count > 0 else "full_retry"
    return {"ok": True, "status": "queued", "mode": mode, "pending_chunks": pending_count}


def _calc_percent(status: str, stage: str, files_total: int, files_extracted: int,
                  files_chunked: int, chunks_total: int, chunks_done: int) -> int:
    """Multi-stage progress: extract 0-30%, chunk 30-60%, embed 60-100%."""
    if status == "done":
        return 100
    if stage in ("cleanup",):
        return 98
    ft = max(files_total, 1)
    if stage == "extract":
        return 5 + int(files_extracted / ft * 25)
    if stage == "chunk":
        return 30 + int(files_chunked / ft * 30)
    if stage == "embed":
        ct = max(chunks_total, 1)
        return 60 + int(chunks_done / ct * 39)
    return 2  # upload / queued


@router.get("/kb/jobs", dependencies=[Depends(_verify_token)])
async def get_ingest_jobs():
    async with db_module.async_session_factory() as session:
        rows = (await session.execute(
            text(
                "SELECT id, status, stage, filename, collection, chunks_added, error, "
                "created_at, updated_at, chunks_done, chunks_total, "
                "files_total, files_extracted, files_chunked, "
                "enrichment_total, enrichment_done, qdrant_upserted, tier "
                "FROM ingest_jobs "
                "WHERE status != 'done' OR updated_at > now() - interval '10 minutes' "
                "ORDER BY created_at DESC LIMIT 50"
            )
        )).fetchall()
    return [
        {
            "id": r[0], "status": r[1], "stage": r[2] or "upload",
            "filename": r[3], "collection": r[4],
            "chunks_added": r[5], "error": r[6],
            "created_at": r[7].isoformat() if r[7] else "",
            "updated_at": r[8].isoformat() if r[8] else "",
            "chunks_done": r[9] or 0, "chunks_total": r[10] or 0,
            "files_total": r[11] or 0, "files_extracted": r[12] or 0,
            "files_chunked": r[13] or 0,
            "enrichment_total": r[14] or 0, "enrichment_done": r[15] or 0,
            "qdrant_upserted": r[16] or 0, "tier": r[17],
            "percent": _calc_percent(
                r[1], r[2] or "upload",
                r[11] or 0, r[12] or 0, r[13] or 0,
                r[10] or 0, r[9] or 0,
            ),
        }
        for r in rows
    ]


@router.get("/kb/jobs/{job_id}/progress", dependencies=[Depends(_verify_token)])
async def get_ingest_job_progress(job_id: str):
    async with db_module.async_session_factory() as session:
        row = (await session.execute(
            text(
                "SELECT id, status, stage, filename, collection, chunks_added, error, "
                "created_at, updated_at, chunks_done, chunks_total, "
                "files_total, files_extracted, files_chunked, "
                "enrichment_total, enrichment_done, qdrant_upserted, tier "
                "FROM ingest_jobs WHERE id=:jid"
            ),
            {"jid": job_id},
        )).fetchone()
    if not row:
        raise HTTPException(404, "Задача не найдена")

    chunks_done = row[9] or 0
    chunks_total = row[10] or 0

    # Compute speed from recent DB history (simple: chunks_done / elapsed_s)
    speed_cps = 0.0
    eta_seconds = None
    if row[7] and chunks_done > 0 and chunks_total > 0:
        elapsed = (row[8] - row[7]).total_seconds() if row[8] and row[7] else 1
        if elapsed > 0:
            speed_cps = round(chunks_done / elapsed, 1)
            remaining = chunks_total - chunks_done
            if speed_cps > 0:
                eta_seconds = int(remaining / speed_cps)

    return {
        "job_id": row[0],
        "status": row[1],
        "stage": row[2] or "upload",
        "filename": row[3],
        "collection": row[4],
        "files_total": row[11] or 0,
        "files_extracted": row[12] or 0,
        "files_chunked": row[13] or 0,
        "enrichment_total": row[14] or 0,
        "enrichment_done": row[15] or 0,
        "chunks_total": chunks_total,
        "chunks_done": chunks_done,
        "qdrant_upserted": row[16] or 0,
        "tier": row[17],
        "speed_cps": speed_cps,
        "eta_seconds": eta_seconds,
        "error": row[6],
        "percent": _calc_percent(
            row[1], row[2] or "upload",
            row[11] or 0, row[12] or 0, row[13] or 0,
            chunks_total, chunks_done,
        ),
    }


@router.get("/kb/jobs/{job_id}/logs", dependencies=[Depends(_verify_token)])
async def get_ingest_job_logs(job_id: str, limit: int = 100, level: str = "all"):
    async with db_module.async_session_factory() as session:
        q = "SELECT id, level, stage, message, details, created_at FROM ingest_logs WHERE job_id=:jid"
        params: dict = {"jid": job_id}
        if level != "all":
            q += " AND level=:lv"
            params["lv"] = level
        q += " ORDER BY created_at DESC LIMIT :lim"
        params["lim"] = limit
        rows = (await session.execute(text(q), params)).fetchall()
    return [
        {
            "id": r[0], "level": r[1], "stage": r[2], "message": r[3],
            "details": r[4], "created_at": r[5].isoformat() if r[5] else "",
        }
        for r in rows
    ]


# ── text extraction helpers ───────────────────────────────────────────────────

def _extract_text_from_bytes(data: bytes, filename: str, mime: str = "") -> str:
    fname = filename.lower()
    if fname.endswith(".pdf") or "pdf" in mime:
        return _extract_pdf(data)
    if fname.endswith(".docx") or "wordprocessingml" in mime:
        return _extract_docx(data)
    if fname.endswith(".epub") or "epub" in mime:
        return _extract_epub(data)
    if fname.endswith(".fb2") or "fb2" in mime:
        return _extract_fb2(data)
    if fname.endswith((".html", ".htm")) or "html" in mime:
        return _extract_html(data)
    if fname.endswith((".txt", ".md", ".rst", ".csv", ".tsv", ".log")):
        return _safe_decode(data)
    if fname.endswith(".json"):
        try:
            obj = json.loads(data)
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return _safe_decode(data)
    # generic fallback — try UTF-8
    return _safe_decode(data)


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        raise HTTPException(status_code=501, detail="pypdf не установлен")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка PDF: {e}")


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise HTTPException(status_code=501, detail="python-docx не установлен")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка DOCX: {e}")


def _extract_epub(data: bytes) -> str:
    """Extract text from EPUB: it's a ZIP of XHTML files ordered by spine."""
    try:
        from bs4 import BeautifulSoup
        texts = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # Find reading order from OPF spine, fallback to all xhtml files
            opf_path = None
            if "META-INF/container.xml" in zf.namelist():
                container = BeautifulSoup(zf.read("META-INF/container.xml"), "xml")
                rootfile = container.find("rootfile")
                if rootfile:
                    opf_path = rootfile.get("full-path")

            ordered_items: list[str] = []
            if opf_path:
                try:
                    opf = BeautifulSoup(zf.read(opf_path), "xml")
                    manifest = {item["id"]: item["href"] for item in opf.find_all("item")}
                    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
                    for itemref in opf.find_all("itemref"):
                        href = manifest.get(itemref.get("idref", ""), "")
                        if href:
                            ordered_items.append(base + href)
                except Exception:
                    pass

            if not ordered_items:
                ordered_items = [n for n in zf.namelist() if n.endswith((".xhtml", ".html", ".htm"))]

            for item in ordered_items:
                if item not in zf.namelist():
                    continue
                soup = BeautifulSoup(zf.read(item), "lxml")
                for tag in soup(["script", "style", "nav"]):
                    tag.decompose()
                chunk = soup.get_text(separator="\n", strip=True)
                if chunk:
                    texts.append(chunk)

        return "\n\n".join(texts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка EPUB: {e}")


def _extract_fb2(data: bytes) -> str:
    """Extract text from FB2 (FictionBook2): XML with <body><section><p> structure."""
    try:
        from bs4 import BeautifulSoup
        text = _safe_decode(data)
        soup = BeautifulSoup(text, "xml")
        parts = []
        for body in soup.find_all("body"):
            for tag in body.find_all(["binary", "image"]):
                tag.decompose()
            parts.append(body.get_text(separator="\n", strip=True))
        return "\n\n".join(p for p in parts if p)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка FB2: {e}")


def _extract_html(data: bytes) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        return _safe_decode(data)


def _safe_decode(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _chunk_text(text: str, max_chars: int = 900, overlap: int = 100) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
                # overlap: carry last sentence of current into next chunk
                tail = current[-overlap:] if len(current) > overlap else current
                current = tail + "\n\n" + para if para else tail
            else:
                # single paragraph bigger than max — split by sentences
                for sent in _split_sentences(para, max_chars):
                    chunks.append(sent)
                current = ""
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= 30]


def _split_sentences(text: str, max_chars: int) -> list[str]:
    import re
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) + 1 <= max_chars:
            buf = (buf + " " + s).strip() if buf else s
        else:
            if buf:
                chunks.append(buf)
            buf = s
    if buf:
        chunks.append(buf)
    return chunks or [text[:max_chars]]


def _url_to_topic(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    path = p.path.rstrip("/").split("/")[-1] or p.netloc
    return path.replace("-", " ").replace("_", " ")[:80]


_UPSERT_BATCH = 200          # Qdrant points per upsert call (used by URL/dataset ingest)


_DATA_EXTENSIONS = {".json", ".jsonl", ".csv", ".txt", ".md"}
_SKIP_FILENAMES = {"readme.md", "license", "license.md", "contributing.md", "changelog.md", ".gitignore"}
_REPO_MAX_FILES = 200
_REPO_MAX_RECORDS = 15_000
_HF_DS_SERVER = "https://datasets-server.huggingface.co"
_HF_API = "https://huggingface.co/api"


def _is_hf_dataset_url(url: str) -> bool:
    import re
    return bool(re.match(r"https?://huggingface\.co/datasets/[^/]+/[^/]+/?$", url.strip()))


def _hf_repo_id(url: str) -> str:
    import re
    m = re.match(r"https?://huggingface\.co/datasets/([^/]+/[^/]+)/?", url.strip())
    return m.group(1) if m else ""


async def _ingest_hf_dataset(repo_id: str, body, llm_router) -> int:
    """Ingest a HuggingFace dataset using datasets-server API (no parquet needed)."""
    HF_MAX_SPLITS = 5       # process at most 5 configs by default
    HF_PAGE = 500           # rows per API call
    HF_MAX_PER_SPLIT = 3000 # max rows per config/split

    # List all splits
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            r = await http.get(f"{_HF_DS_SERVER}/splits", params={"dataset": repo_id})
        r.raise_for_status()
        splits = r.json().get("splits", [])
    except Exception as e:
        raise HTTPException(400, f"HuggingFace datasets-server недоступен для {repo_id}: {e}")

    if not splits:
        raise HTTPException(400, f"Датасет {repo_id} не найден в datasets-server")

    limit_rows = body.limit if body.limit else HF_MAX_PER_SPLIT
    max_splits = HF_MAX_SPLITS if not body.limit else len(splits)
    process_splits = splits[:max_splits]

    total = 0
    for split_info in process_splits:
        config = split_info.get("config", "default")
        split = split_info.get("split", "train")
        prefix = f"{body.topic_prefix.strip() or repo_id}/{config}"

        rows_collected: list[dict] = []
        offset = 0
        while len(rows_collected) < limit_rows:
            fetch = min(HF_PAGE, limit_rows - len(rows_collected))
            try:
                async with httpx.AsyncClient(timeout=30) as http:
                    r = await http.get(
                        f"{_HF_DS_SERVER}/rows",
                        params={"dataset": repo_id, "config": config, "split": split,
                                "offset": offset, "length": fetch},
                    )
                r.raise_for_status()
                data = r.json()
            except Exception:
                break

            batch = [item["row"] for item in data.get("rows", []) if isinstance(item.get("row"), dict)]
            if not batch:
                break
            rows_collected.extend(batch)
            offset += len(batch)
            if offset >= min(data.get("num_rows_total", 0), limit_rows):
                break

        if not rows_collected:
            continue

        entries = _records_to_entries(rows_collected, prefix, body.question_field, body.answer_field)
        src_lang = getattr(body, "source_lang", "auto")
        count = await _upsert_entries_simple(entries, body.collection, llm_router, src_lang)
        total += count
        logger.info("admin.kb.hf_split", repo=repo_id, config=config, split=split, added=count)

    return total


def _is_git_repo_url(url: str) -> bool:
    import re
    url = url.strip()
    if url.rstrip("/").endswith(".git"):
        return True
    if re.match(r"https?://github\.com/[^/]+/[^/]+/?$", url):
        return True
    if re.match(r"https?://github\.com/[^/]+/[^/]+/tree/", url):
        return True
    return False


def _github_zip_url(url: str) -> tuple[str, str]:
    """Return (zip_url_template, subpath_filter). zip_url_template has {branch} placeholder."""
    import re
    url = url.strip().rstrip("/").removesuffix(".git")

    # github.com/user/repo/tree/branch/subpath
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(/(.*))?$", url)
    if m:
        user, repo, branch, _, subpath = m.group(1), m.group(2), m.group(3), m.group(4), (m.group(5) or "")
        return f"https://github.com/{user}/{repo}/archive/refs/heads/{branch}.zip", subpath

    # github.com/user/repo
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)$", url)
    if m:
        user, repo = m.group(1), m.group(2)
        return f"https://github.com/{user}/{repo}/archive/refs/heads/{{branch}}.zip", ""

    raise HTTPException(status_code=400, detail=f"Не удалось определить URL репозитория: {url}")


def _normalize_dataset_url(url: str) -> str:
    """Convert GitHub blob URLs to raw download URLs."""
    import re
    url = url.strip()
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/blob/(.+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}"
    return url


def _parse_records_from_bytes(raw: bytes, filename: str) -> list[dict]:
    """Parse JSON/JSONL/CSV bytes into a list of dicts."""
    fname = filename.lower()
    try:
        if fname.endswith(".jsonl"):
            text = _safe_decode(raw)
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        if fname.endswith(".csv"):
            text = _safe_decode(raw)
            return list(csv_mod.DictReader(io.StringIO(text)))
        if fname.endswith(".json"):
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [r for r in parsed if isinstance(r, dict)]
            if isinstance(parsed, dict):
                # Array under common wrapper keys
                for key in ("data", "train", "test", "validation", "dev", "examples", "items", "rows", "dialogs"):
                    val = parsed.get(key)
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        return val
                # Dict of dicts (e.g. RECCON format: {"conv_001": {...}, ...})
                first_val = next(iter(parsed.values()), None)
                if isinstance(first_val, dict):
                    return [{"_id": k, **v} for k, v in parsed.items()]
                return [parsed]
    except Exception:
        pass
    return []


def _records_to_entries(records: list[dict], prefix: str, q_hint: str, a_hint: str) -> list[dict]:
    """Convert parsed records to KB entries. Tries Q&A mode first; falls back to rich free-text."""
    if not records:
        return []

    q_field, a_field = _detect_qa_fields(records[0], q_hint, a_hint)

    # Try Q&A extraction
    qa_entries = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        q = str(rec.get(q_field, "")).strip()
        a = str(rec.get(a_field, "")).strip()
        if q and a and a != q and len(q) >= 10 and len(a) >= 20:
            qa_entries.append({"topic": f"{prefix}: {q[:70]}", "text": f"Вопрос: {q}\n\nОтвет: {a}"})

    # Use Q&A if it covers ≥15% of records — otherwise the field detection was wrong
    if len(qa_entries) >= max(3, len(records) * 0.15):
        return qa_entries

    # Free-text fallback: combine all meaningful columns per record into one rich entry
    # Find a "category" column to use as sub-topic
    CATEGORY_NAMES = ("dimension", "category", "topic", "type", "domain", "class", "theme")
    cat_field = next(
        (k for k in records[0].keys() if any(c in k.lower() for c in CATEGORY_NAMES)),
        None,
    )

    text_entries = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        parts = []
        for k, v in rec.items():
            val = str(v).strip()
            # Skip short values, pure numbers, and coding labels
            if not val or len(val) < 10:
                continue
            if val.replace(".", "").replace("-", "").replace("_", "").isdigit():
                continue
            key_low = k.lower()
            if key_low.endswith(("label", "_id", " id", "score", "index")):
                continue
            parts.append(f"{k}: {val}")
        text = "\n".join(parts[:8])
        if len(text) < 50:
            continue
        cat = str(rec.get(cat_field, "")).strip() if cat_field else ""
        topic = f"{prefix}/{cat[:50]}" if cat and len(cat) > 3 else prefix
        text_entries.append({"topic": topic, "text": text})

    # Return whichever mode produced more entries
    return text_entries if len(text_entries) >= len(qa_entries) else qa_entries


async def _ingest_repo_zip(zip_bytes: bytes, body, llm_router, repo_name: str) -> int:
    """Walk a downloaded zip archive, process all data files, return total KB entries added."""
    total = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        all_names = zf.namelist()

        # Determine subpath filter from body.topic_prefix or empty
        subpath_filter = ""  # could be set if user entered a tree URL with subfolder

        data_files = []
        for name in all_names:
            if name.endswith("/"):
                continue
            basename = name.rsplit("/", 1)[-1].lower()
            if basename in _SKIP_FILENAMES or basename.startswith("."):
                continue
            ext = "." + basename.rsplit(".", 1)[-1] if "." in basename else ""
            if ext not in _DATA_EXTENSIONS:
                continue
            if subpath_filter and subpath_filter not in name:
                continue
            data_files.append(name)

        logger.info("admin.kb.repo_files_found", repo=repo_name, count=len(data_files))
        data_files = data_files[:_REPO_MAX_FILES]

        for filepath in data_files:
            basename = filepath.rsplit("/", 1)[-1]
            # Use file path as topic prefix, stripping the top-level repo-branch/ directory
            parts = filepath.split("/")
            rel_path = "/".join(parts[1:]) if len(parts) > 1 else filepath
            file_prefix = (body.topic_prefix.strip() + "/" if body.topic_prefix.strip() else "") + rel_path.rsplit(".", 1)[0]

            try:
                raw_data = zf.read(filepath)
            except Exception:
                continue

            src_lang = getattr(body, "source_lang", "auto")

            # Plain text files → chunk and ingest as text
            if basename.lower().endswith((".txt", ".md")):
                text = _safe_decode(raw_data)
                if len(text.strip()) < 100:
                    continue
                chunks = _chunk_text(text)
                if body.limit:
                    chunks = chunks[:body.limit]
                total += await _upsert_chunks_simple(chunks, body.collection, file_prefix, llm_router, src_lang)
                continue

            records = _parse_records_from_bytes(raw_data, basename)
            if not records:
                continue
            if body.limit:
                records = records[:body.limit]
            if total + len(records) > _REPO_MAX_RECORDS:
                records = records[:max(0, _REPO_MAX_RECORDS - total)]

            entries = _records_to_entries(records, file_prefix, body.question_field, body.answer_field)
            if not entries:
                continue

            count = await _upsert_entries_simple(entries, body.collection, llm_router, src_lang)
            total += count
            logger.info("admin.kb.repo_file_ingested", file=rel_path, added=count)

            if total >= _REPO_MAX_RECORDS:
                break

    return total


@router.post("/kb/ingest-dataset", response_model=KBIngestResult, dependencies=[Depends(_verify_token)])
async def kb_ingest_dataset(body: KBDatasetIngestRequest, request: Request):
    """
    Ingest a dataset from a URL: single file (JSON/JSONL/CSV) or entire GitHub repository.
    Automatically detects Q&A fields, optionally translates EN→RU.
    """
    llm_router = getattr(request.app.state, "llm_router", None)
    if llm_router is None:
        raise HTTPException(status_code=503, detail="LLM router not ready")

    url = body.dataset_url.strip()

    # ── HuggingFace dataset page ──────────────────────────────────────────────
    if _is_hf_dataset_url(url):
        repo_id = _hf_repo_id(url)
        total = await _ingest_hf_dataset(repo_id, body, llm_router)
        logger.info("admin.kb.ingest_hf", repo=repo_id, collection=body.collection, total=total)
        return KBIngestResult(chunks_added=total, collection=body.collection, source=url)

    # ── GitHub repository ─────────────────────────────────────────────────────
    if _is_git_repo_url(url):
        zip_url_tpl, _ = _github_zip_url(url)
        zip_bytes = None
        tried: list[str] = []

        branches = ["main", "master"] if "{branch}" in zip_url_tpl else [None]
        for branch in branches:
            try_url = zip_url_tpl.replace("{branch}", branch) if branch else zip_url_tpl
            tried.append(try_url)
            try:
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
                    resp = await http.get(try_url, headers={"User-Agent": "MirrorBot/1.0"})
                if resp.status_code == 200 and b"PK" in resp.content[:4]:
                    zip_bytes = resp.content
                    break
            except Exception:
                continue

        if not zip_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Не удалось скачать репозиторий. Попробованы ветки: main, master. "
                       f"Проверь что репозиторий публичный.",
            )

        repo_name = url.rstrip("/").split("/")[-1].removesuffix(".git")
        total = await _ingest_repo_zip(zip_bytes, body, llm_router, repo_name)
        logger.info("admin.kb.ingest_repo", url=url, total=total)
        return KBIngestResult(chunks_added=total, collection=body.collection, source=url)

    # ── Single file ───────────────────────────────────────────────────────────
    dataset_url = _normalize_dataset_url(url)

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            resp = await http.get(dataset_url, headers={"User-Agent": "MirrorBot/1.0"})
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось загрузить файл: {e}")

    content_type = resp.headers.get("content-type", "")
    raw = resp.content

    if "text/html" in content_type or raw[:100].lstrip().startswith(b"<"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Ссылка ведёт на HTML-страницу, а не файл данных. "
                "Для одного файла: открой на GitHub → кнопка Raw → скопируй URL. "
                "Для целого репозитория: вставь URL репозитория (github.com/user/repo)."
            ),
        )

    filename = dataset_url.split("?")[0].split("/")[-1] or "data"
    records = _parse_records_from_bytes(raw, filename)

    if not records:
        raise HTTPException(status_code=400, detail="Файл не содержит распознанных записей (JSON/JSONL/CSV)")

    if body.limit:
        records = records[:body.limit]

    prefix = body.topic_prefix.strip() or _url_to_topic(url)
    entries = _records_to_entries(records, prefix, body.question_field, body.answer_field)

    if not entries:
        sample_keys = list(records[0].keys()) if records else []
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось сформировать записи. Поля в файле: {sample_keys}. "
                   f"Укажи вручную ПОЛЕ ВОПРОСА и ПОЛЕ ОТВЕТА.",
        )

    count = await _upsert_entries_simple(entries, body.collection, llm_router, body.source_lang)
    logger.info("admin.kb.ingest_dataset", collection=body.collection, url=url, count=count)
    return KBIngestResult(chunks_added=count, collection=body.collection, source=url)


def _detect_qa_fields(sample: dict, q_hint: str, a_hint: str) -> tuple[str, str]:
    Q_ALIASES = [
        "question", "q", "input", "context", "prompt", "instruction", "query", "human",
        "statement", "situation", "problem", "text", "utterance", "message",
        "patient", "user", "request", "scenario", "concern", "original",
    ]
    A_ALIASES = [
        "answer", "a", "output", "response", "reply", "assistant", "completion", "gpt",
        "challenge", "reframe", "solution", "advice", "feedback", "followup",
        "follow_up", "therapist", "counselor", "expert", "annotation", "target",
        "another", "alternative", "corrected",
    ]
    original_keys = list(sample.keys())

    def find(aliases, hint):
        if hint and hint in sample:
            return hint
        # 1. Exact match
        for alias in aliases:
            for orig in original_keys:
                if orig.lower().strip() == alias:
                    return orig
        # 2. Alias as substring of field name (skip single/double-char aliases to avoid false matches)
        for alias in aliases:
            if len(alias) <= 2:
                continue
            for orig in original_keys:
                if alias in orig.lower():
                    return orig
        return original_keys[0] if original_keys else ""

    q = find(Q_ALIASES, q_hint)
    a = find(A_ALIASES, a_hint)
    if q == a and len(original_keys) >= 2:
        a = next((k for k in original_keys if k != q), original_keys[-1])
    return q, a


def _detect_lang(text: str) -> str:
    """Detect language: 'ru' if >20% cyrillic characters, else 'en'."""
    if not text:
        return "en"
    sample = text[:500]
    cyrillic = sum(1 for c in sample if '\u0400' <= c <= '\u04FF')
    return "ru" if cyrillic / max(len(sample), 1) > 0.20 else "en"


async def _upsert_chunks_simple(
    chunks: list[str], collection: str, topic: str, llm_router, source_lang: str = "auto",
) -> int:
    """Embed and upsert chunks without translation (v2 URL/dataset ingest)."""
    if not chunks:
        return 0
    await _ensure_collection(collection)
    from mirror.services.ingest.extractor import detect_lang as _det_lang
    lang = source_lang if source_lang in ("ru", "en") else _det_lang(" ".join(chunks[:3]))
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    total = 0
    try:
        texts = [f"{topic}\n{c}" for c in chunks]
        all_embs = await llm_router.embed_batch(texts, batch_size=500)
        points = [
            PointStruct(id=str(uuid_module.uuid4()), vector=emb,
                        payload={"topic": topic, "text": c, "collection": collection, "lang": lang})
            for c, emb in zip(chunks, all_embs)
        ]
        for i in range(0, len(points), _UPSERT_BATCH):
            await client.upsert(collection_name=collection, points=points[i:i + _UPSERT_BATCH])
        total = len(chunks)
    finally:
        await client.close()
    return total




async def _upsert_entries_simple(
    entries: list[dict], collection: str, llm_router, source_lang: str = "auto",
) -> int:
    """Embed and upsert KB entries (with per-entry topics) without translation."""
    if not entries:
        return 0
    await _ensure_collection(collection)
    from mirror.services.ingest.extractor import detect_lang as _det_lang
    sample = " ".join(e["text"][:200] for e in entries[:3])
    lang = source_lang if source_lang in ("ru", "en") else _det_lang(sample)
    topics = [e["topic"] for e in entries]
    texts = [e["text"] for e in entries]
    embed_inputs = [f"{t}\n{tx}" for t, tx in zip(topics, texts)]
    all_embs = await llm_router.embed_batch(embed_inputs, batch_size=500)
    points = [
        PointStruct(id=str(uuid_module.uuid4()), vector=emb,
                    payload={"topic": t, "text": tx, "collection": collection, "lang": lang})
        for t, tx, emb in zip(topics, texts, all_embs)
    ]
    qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        for i in range(0, len(points), _UPSERT_BATCH):
            await qdrant.upsert(collection_name=collection, points=points[i:i + _UPSERT_BATCH])
    finally:
        await qdrant.close()
    return len(entries)


async def _ensure_collection(name: str) -> None:
    """Create Qdrant collection if it does not exist yet."""
    from qdrant_client.models import Distance, VectorParams
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        existing = {c.name for c in (await client.get_collections()).collections}
        if name not in existing:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
            )
            logger.info("admin.kb.collection_autocreated", collection=name)
    finally:
        await client.close()


