import asyncio
import csv as csv_mod
import os
import io
import json
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

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


def _verify_token(x_admin_token: str = Header(...)):
    if x_admin_token != settings.admin_token.get_secret_value():
        raise HTTPException(status_code=403, detail="Forbidden")


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


# ── API keys ──────────────────────────────────────────────────────────────────

_API_KEY_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@router.get("/llm-keys", dependencies=[Depends(_verify_token)])
async def get_llm_keys():
    """Return masked API keys from env + app_config override."""
    result = {}
    for provider, env_var in _API_KEY_VARS.items():
        val = os.environ.get(env_var, "")
        if val:
            result[provider] = val[:8] + "..." + val[-4:] if len(val) > 12 else "****"
        else:
            result[provider] = ""
    return result


@router.put("/llm-keys/{provider}", dependencies=[Depends(_verify_token)])
async def set_llm_key(provider: str, request: Request):
    body = await request.json()
    key = body.get("key", "").strip()
    if provider not in _API_KEY_VARS:
        raise HTTPException(400, f"Unknown provider: {provider!r}")
    if not key:
        raise HTTPException(400, "key must not be empty")
    env_var = _API_KEY_VARS[provider]
    os.environ[env_var] = key
    from mirror.core.llm.router import LLMRouter
    LLMRouter._routing_cache.clear()
    LLMRouter._provider_cache.clear()
    logger.info("admin.llm_key.updated", provider=provider)
    return {"updated": provider, "set": True}


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
    client = AsyncQdrantClient(url=settings.qdrant_url)
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
    client = AsyncQdrantClient(url=settings.qdrant_url)
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
    client = AsyncQdrantClient(url=settings.qdrant_url)
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
    client = AsyncQdrantClient(url=settings.qdrant_url)
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

    from qdrant_client.models import Distance, VectorParams
    client = AsyncQdrantClient(url=settings.qdrant_url)
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

    client = AsyncQdrantClient(url=settings.qdrant_url)
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
    client = AsyncQdrantClient(url=settings.qdrant_url)
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
    count = await _upsert_bilingual_chunks(chunks, body.collection, topic, llm_router, body.source_lang)
    logger.info("admin.kb.ingest_url", collection=body.collection, url=body.url, chunks=count)
    return KBIngestResult(chunks_added=count, collection=body.collection, source=body.url)


@router.post("/kb/ingest-file", response_model=KBIngestResult, dependencies=[Depends(_verify_token)])
async def kb_ingest_file(
    request: Request,
    collection: str = Form(...),
    topic: str = Form(""),
    source_lang: str = Form("auto"),
    file: UploadFile = File(...),
):
    llm_router = getattr(request.app.state, "llm_router", None)
    if llm_router is None:
        raise HTTPException(status_code=503, detail="LLM router not ready")

    content = await file.read()
    filename = file.filename or "upload"
    mime = file.content_type or ""

    file_topic = topic or filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")

    if filename.lower().endswith(".zip"):
        chunks_total = await _ingest_zip(content, collection, file_topic, llm_router, source_lang)
    else:
        text_content = _extract_text_from_bytes(content, filename=filename, mime=mime)
        if not text_content.strip():
            raise HTTPException(status_code=400, detail="Не удалось извлечь текст из файла")
        chunks = _chunk_text(text_content)
        chunks_total = await _upsert_bilingual_chunks(chunks, collection, file_topic, llm_router, source_lang)

    logger.info("admin.kb.ingest_file", collection=collection, filename=filename, chunks=chunks_total)
    return KBIngestResult(chunks_added=chunks_total, collection=collection, source=filename)


# ── text extraction helpers ───────────────────────────────────────────────────

def _extract_text_from_bytes(data: bytes, filename: str, mime: str = "") -> str:
    fname = filename.lower()
    if fname.endswith(".pdf") or "pdf" in mime:
        return _extract_pdf(data)
    if fname.endswith(".docx") or "wordprocessingml" in mime:
        return _extract_docx(data)
    if fname.endswith(".epub") or "epub" in mime:
        return _extract_epub(data)
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


_EMBED_CONCURRENCY = 12   # parallel embed calls
_UPSERT_BATCH = 100       # points per Qdrant batch upsert


async def _upsert_chunks(
    chunks: list[str], collection: str, topic: str, llm_router
) -> int:
    if not chunks:
        return 0
    sem = asyncio.Semaphore(_EMBED_CONCURRENCY)

    async def _embed_one(text: str) -> list[float]:
        async with sem:
            return await llm_router.embed(text)

    topics = [
        f"{topic} (часть {i + 1})" if len(chunks) > 1 else topic
        for i in range(len(chunks))
    ]
    texts = [f"{t}\n{c}" for t, c in zip(topics, chunks)]
    embeddings = await asyncio.gather(*[_embed_one(t) for t in texts])

    client = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        points = [
            PointStruct(
                id=str(uuid_module.uuid4()),
                vector=emb,
                payload={"topic": t, "text": c, "collection": collection},
            )
            for t, c, emb in zip(topics, chunks, embeddings)
        ]
        for i in range(0, len(points), _UPSERT_BATCH):
            await client.upsert(collection_name=collection, points=points[i:i + _UPSERT_BATCH])
    finally:
        await client.close()
    return len(chunks)


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
        count = await _upsert_bilingual_entries(entries, body.collection, llm_router, src_lang)
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
                total += await _upsert_bilingual_chunks(chunks, body.collection, file_prefix, llm_router, src_lang)
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

            count = await _upsert_bilingual_entries(entries, body.collection, llm_router, src_lang)
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

    count = await _upsert_bilingual_entries(entries, body.collection, llm_router, body.source_lang)
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


_TRANSLATE_CONCURRENCY = 4  # translation is expensive; keep lower


def _detect_lang(text: str) -> str:
    """Detect language: 'ru' if >20% cyrillic characters, else 'en'."""
    if not text:
        return "en"
    sample = text[:500]
    cyrillic = sum(1 for c in sample if '\u0400' <= c <= '\u04FF')
    return "ru" if cyrillic / max(len(sample), 1) > 0.20 else "en"


async def _llm_translate_to(text: str, target_lang: str, llm_router) -> str:
    """Translate text to target_lang ('ru' or 'en'). Returns original if already in target lang."""
    if _detect_lang(text) == target_lang:
        return text
    if target_lang == "ru":
        system = (
            "Переведи текст на русский язык. Сохрани структуру и психологические термины. "
            "Верни ТОЛЬКО перевод без пояснений."
        )
    else:
        system = (
            "Translate the text to English. Preserve structure and psychological terms. "
            "Return ONLY the translation without explanations."
        )
    try:
        return await llm_router.call(
            task_kind="intent_classify",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text[:3000]},
            ],
            max_tokens=1500,
            temperature=0.1,
        )
    except Exception:
        return text


async def _upsert_bilingual_chunks(
    chunks: list[str], collection: str, topic: str, llm_router, source_lang: str = "auto"
) -> int:
    """Upsert chunks in original language + translated version. Returns original chunk count."""
    if not chunks:
        return 0

    sample = " ".join(chunks[:3])
    lang = source_lang if source_lang in ("ru", "en") else _detect_lang(sample)
    target_lang = "en" if lang == "ru" else "ru"

    topics = [
        f"{topic} (часть {i + 1})" if len(chunks) > 1 else topic
        for i in range(len(chunks))
    ]

    # Translate all chunks concurrently
    sem_tr = asyncio.Semaphore(_TRANSLATE_CONCURRENCY)

    async def _tr(text: str) -> str:
        async with sem_tr:
            return await _llm_translate_to(text, target_lang, llm_router)

    translated_chunks = await asyncio.gather(*[_tr(c) for c in chunks])

    # Embed originals + translations concurrently
    orig_texts = [f"{t}\n{c}" for t, c in zip(topics, chunks)]
    tr_texts   = [f"{t}\n{c}" for t, c in zip(topics, translated_chunks)]

    sem_emb = asyncio.Semaphore(_EMBED_CONCURRENCY)

    async def _emb(text: str) -> list[float]:
        async with sem_emb:
            return await llm_router.embed(text)

    all_embeddings = await asyncio.gather(*[_emb(t) for t in orig_texts + tr_texts])
    orig_embs = all_embeddings[:len(chunks)]
    tr_embs   = all_embeddings[len(chunks):]

    orig_points = [
        PointStruct(
            id=str(uuid_module.uuid4()),
            vector=emb,
            payload={"topic": t, "text": c, "collection": collection, "lang": lang},
        )
        for t, c, emb in zip(topics, chunks, orig_embs)
    ]
    tr_points = [
        PointStruct(
            id=str(uuid_module.uuid4()),
            vector=emb,
            payload={"topic": t, "text": c, "collection": collection, "lang": target_lang},
        )
        for t, c, emb in zip(topics, translated_chunks, tr_embs)
    ]

    client = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        all_points = orig_points + tr_points
        for i in range(0, len(all_points), _UPSERT_BATCH):
            await client.upsert(collection_name=collection, points=all_points[i:i + _UPSERT_BATCH])
    finally:
        await client.close()
    return len(chunks)


async def _upsert_bilingual_entries(
    entries: list[dict], collection: str, llm_router, source_lang: str = "auto"
) -> int:
    """Upsert entries in both original and translated form. Returns original entry count."""
    if not entries:
        return 0

    sample = " ".join(e["text"][:200] for e in entries[:3])
    lang = source_lang if source_lang in ("ru", "en") else _detect_lang(sample)
    target_lang = "en" if lang == "ru" else "ru"

    topics = [e["topic"] for e in entries]
    orig_texts = [e["text"] for e in entries]

    sem_tr = asyncio.Semaphore(_TRANSLATE_CONCURRENCY)

    async def _tr(text: str) -> str:
        async with sem_tr:
            return await _llm_translate_to(text, target_lang, llm_router)

    translated_texts = await asyncio.gather(*[_tr(t) for t in orig_texts])

    # Embed both sets concurrently
    all_topics = topics + topics
    all_texts  = orig_texts + translated_texts
    all_langs  = [lang] * len(entries) + [target_lang] * len(entries)

    sem_emb = asyncio.Semaphore(_EMBED_CONCURRENCY)

    async def _emb(topic: str, text: str) -> list[float]:
        async with sem_emb:
            return await llm_router.embed(f"{topic}\n{text}")

    all_embeddings = await asyncio.gather(*[_emb(t, tx) for t, tx in zip(all_topics, all_texts)])

    all_points = [
        PointStruct(
            id=str(uuid_module.uuid4()),
            vector=emb,
            payload={"topic": t, "text": tx, "collection": collection, "lang": l},
        )
        for t, tx, emb, l in zip(all_topics, all_texts, all_embeddings, all_langs)
    ]

    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        for i in range(0, len(all_points), _UPSERT_BATCH):
            await qdrant.upsert(collection_name=collection, points=all_points[i:i + _UPSERT_BATCH])
    finally:
        await qdrant.close()
    return len(entries)


async def _ensure_collection(name: str) -> None:
    """Create Qdrant collection if it does not exist yet."""
    from qdrant_client.models import Distance, VectorParams
    client = AsyncQdrantClient(url=settings.qdrant_url)
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


async def _ingest_zip(data: bytes, collection: str, base_topic: str, llm_router, source_lang: str = "auto") -> int:
    """Ingest all files from a ZIP archive.

    If the ZIP contains top-level folders whose names start with ``knowledge_``,
    each folder is treated as a separate collection and files are routed there
    automatically.  Files at the root level (or inside non-knowledge folders)
    fall back to the ``collection`` parameter.
    """
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # Pre-create any collections referenced by folder names so upserts don't fail.
            folder_collections = {
                parts[0]
                for name in zf.namelist()
                if not name.endswith("/") and not name.startswith("__MACOSX")
                for parts in [name.split("/")]
                if len(parts) > 1 and parts[0].startswith("knowledge_")
            }
            for col in folder_collections:
                await _ensure_collection(col)

            for name in zf.namelist():
                if name.endswith("/") or name.startswith("__MACOSX"):
                    continue
                parts = name.split("/")
                filename = parts[-1]
                if not filename:
                    continue

                # Route to folder-named collection when folder looks like a collection.
                if len(parts) > 1 and parts[0].startswith("knowledge_"):
                    target_collection = parts[0]
                else:
                    target_collection = collection

                file_bytes = zf.read(name)
                text_content = _extract_text_from_bytes(file_bytes, filename=filename)
                if not text_content.strip():
                    continue
                book_name = filename.rsplit(".", 1)[0]
                file_topic = f"{base_topic} / {book_name}" if base_topic else book_name
                chunks = _chunk_text(text_content)
                total += await _upsert_bilingual_chunks(chunks, target_collection, file_topic, llm_router, source_lang)
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=400, detail=f"Некорректный ZIP: {e}")
    return total
