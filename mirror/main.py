import asyncio
from contextlib import asynccontextmanager

import structlog
from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from prometheus_fastapi_instrumentator import Instrumentator

from mirror.config import settings
from mirror.logging_setup import setup_logging

setup_logging(settings.app_env)
logger = structlog.get_logger()

_polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _polling_task
    logger.info("mirror.startup", env=settings.app_env, polling=settings.polling_mode)

    # ── Database ──────────────────────────────────────────────────────────────
    from mirror.db.session import close_db_pool, init_db_pool
    await init_db_pool()

    # ── Ingest job queue ──────────────────────────────────────────────────────
    from sqlalchemy import text as sa_text
    import mirror.db.session as db_module
    ingest_queue: asyncio.Queue = asyncio.Queue()
    app.state.ingest_queue = ingest_queue
    try:
        async with db_module.async_session_factory() as _s:
            _leftover = (await _s.execute(
                sa_text("SELECT id FROM ingest_jobs WHERE status='queued' ORDER BY created_at")
            )).fetchall()
        for _row in _leftover:
            await ingest_queue.put(_row[0])
        if _leftover:
            logger.info("ingest_jobs.requeued_on_start", count=len(_leftover))
    except Exception:
        logger.warning("ingest_jobs.requeue_failed")

    # ── App config cache ──────────────────────────────────────────────────────
    from mirror.services.dialog import load_app_config_cache
    await load_app_config_cache()

    # ── Qdrant collections ────────────────────────────────────────────────────
    try:
        from mirror.core.memory.qdrant_init import init_qdrant_collections
        await init_qdrant_collections()
    except Exception:
        logger.warning("qdrant.init_failed — продолжаем без Qdrant")

    # ── NATS ──────────────────────────────────────────────────────────────────
    nats_ok = False
    try:
        from mirror.events.nats_client import nats_client
        await nats_client.connect(settings.nats_url)
        nats_ok = True
    except Exception:
        logger.warning("nats.connect_failed — NATS недоступен, события отключены")

    if nats_ok:
        try:
            from mirror.events.consumers.memory import start_memory_consumer
            await start_memory_consumer()
        except Exception:
            logger.warning("nats.memory_consumer_failed")

    # ── Services ──────────────────────────────────────────────────────────────
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(settings.redis_url)
    app.state.redis = redis_client

    from mirror.core.llm.router import LLMRouter
    llm_router = LLMRouter()
    app.state.llm_router = llm_router

    # ── Ingest workers (3 concurrent) ─────────────────────────────────────────
    from mirror.admin.router import _ingest_worker
    for _ in range(3):
        asyncio.create_task(_ingest_worker(ingest_queue, llm_router))

    from mirror.core.memory.service import MemoryService
    memory_service = MemoryService(redis_client=redis_client, llm_router=llm_router)

    from mirror.services.billing import BillingService
    billing_service = BillingService(redis=redis_client)

    from mirror.core.identity.service import IdentityService
    identity_service = IdentityService()

    from mirror.core.policy.safety import PolicyEngine
    policy_engine = PolicyEngine(llm_router=llm_router)

    from mirror.services.intent_router import IntentRouter
    intent_router_svc = IntentRouter(llm_router=llm_router)

    from mirror.services.tarot import TarotService
    tarot_service = TarotService(llm_router=llm_router)

    from mirror.services.astrology import AstrologyService
    astro_service = AstrologyService(llm_router=llm_router, redis_client=redis_client)

    from mirror.services.daily_ritual import DailyRitualService
    ritual_service = DailyRitualService(
        tarot_service=tarot_service,
        astrology_service=astro_service,
        llm_router=llm_router,
    )

    from mirror.services.dialog_graph import build_dialog_graph
    graph = build_dialog_graph(
        intent_router=intent_router_svc,
        policy_engine=policy_engine,
        memory_service=memory_service,
        llm_router=llm_router,
        astrology_service=astro_service,
        tarot_service=tarot_service,
        daily_ritual_service=ritual_service,
    )

    from mirror.services.dialog import DialogService
    dialog_service = DialogService(
        graph=graph,
        memory_service=memory_service,
        billing_service=billing_service,
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    from mirror.channels.telegram.adapter import TelegramAdapter
    from mirror.channels.telegram.handlers import make_handlers_router
    from mirror.admin.router import _bot_polling_loop

    storage = RedisStorage(redis=redis_client)
    dp = Dispatcher(storage=storage)
    adapter = TelegramAdapter(
        identity_service=identity_service,
        redis_client=redis_client,
    )
    dp.include_router(make_handlers_router(adapter, dialog_service))
    app.state.bot = None  # set to first connected bot below
    app.state.dp = dp

    # ── Load all TG bots from DB and connect them ─────────────────────────────
    _secret = settings.telegram_webhook_secret.get_secret_value()

    async def _connect_bot(entry_bot, entry_name, entry_tg_id):
        """Set webhook or start polling for one bot. Returns polling task or None."""
        if settings.polling_mode:
            return asyncio.create_task(_bot_polling_loop(entry_bot, dp))
        else:
            wh_url = f"{settings.base_url}/webhook/telegram/{entry_tg_id}/{_secret}"
            try:
                await entry_bot.set_webhook(wh_url, secret_token=_secret)
            except Exception as e:
                logger.warning("telegram.set_webhook_failed", name=entry_name, error=str(e))
            return None

    app.state.tg_bots = []
    async with db_module.async_session_factory() as _s:
        _db_bots = (await _s.execute(
            sa_text("SELECT name, token, username, tg_id FROM tg_bots ORDER BY created_at")
        )).fetchall()

    for _row in _db_bots:
        _bname, _btoken, _busername, _btg_id = _row
        try:
            from aiogram import Bot as _ABot
            from aiogram.client.default import DefaultBotProperties as _DBP
            _bobj = _ABot(token=_btoken, default=_DBP(parse_mode=None))
            _bme = await _bobj.get_me()
            _busername = _bme.username
            _btg_id = _bme.id
        except Exception as _e:
            logger.warning("telegram.bot_connect_failed", name=_bname, error=str(_e))
            continue

        _ptask = await _connect_bot(_bobj, _bname, _btg_id)
        app.state.tg_bots.append({
            "name": _bname, "token": _btoken, "username": _busername,
            "tg_id": _btg_id, "bot_obj": _bobj, "active": True,
            "polling_task": _ptask,
        })
        if app.state.bot is None:
            app.state.bot = _bobj
        logger.info("telegram.bot_connected", name=_bname, username=_busername)

    if not app.state.tg_bots:
        logger.warning("telegram.no_bots — add a bot via admin panel")

    if settings.polling_mode:
        logger.info("telegram.polling_started", bots=len(app.state.tg_bots))
    else:
        from mirror.channels.telegram.webhook import make_webhook_router
        app.include_router(make_webhook_router(dp))
        logger.info("telegram.webhook_ready", bots=len(app.state.tg_bots))

    # ── Reset zombie ingest jobs from previous run ────────────────────────────
    try:
        async with db_module.async_session_factory() as session:
            await session.execute(
                sa_text("UPDATE ingest_jobs SET status='error', error='Прервано: сервер перезапущен', "
                        "updated_at=now() WHERE status='running'")
            )
            await session.commit()
    except Exception:
        logger.warning("ingest_jobs.reset_failed")

    # ── Cleanup stale ingest disk dirs ────────────────────────────────────────
    try:
        from mirror.services.ingest.cleanup import cleanup_stale_dirs
        await cleanup_stale_dirs()
    except Exception:
        logger.warning("ingest.cleanup_stale_dirs_failed")

    logger.info("mirror.startup.complete")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("mirror.shutdown")
    # Cancel all per-bot polling tasks
    for _entry in getattr(app.state, "tg_bots", []):
        _t = _entry.get("polling_task")
        if _t:
            _t.cancel()
            try:
                await _t
            except (asyncio.CancelledError, Exception):
                pass
    # Close all bot sessions
    for _entry in getattr(app.state, "tg_bots", []):
        _b = _entry.get("bot_obj")
        if _b:
            if not settings.polling_mode:
                try:
                    await _b.delete_webhook()
                except Exception:
                    pass
            try:
                await _b.session.close()
            except Exception:
                pass

    await redis_client.aclose()
    if nats_ok:
        try:
            from mirror.events.nats_client import nats_client
            await nats_client.close()
        except Exception:
            pass
    await close_db_pool()
    logger.info("mirror.shutdown.complete")


app = FastAPI(title="Mirror", version="0.1.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)

from mirror.admin.router import router as admin_router  # noqa: E402
from mirror.admin.ui import ui_router as admin_ui_router  # noqa: E402
app.include_router(admin_router)
app.include_router(admin_ui_router)


@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/admin/ui/")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


@app.get("/ready")
async def ready():
    return JSONResponse({"status": "ready"})
