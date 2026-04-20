from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from mirror.config import settings
from mirror.logging_setup import setup_logging

setup_logging(settings.app_env)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("mirror.startup", env=settings.app_env)

    # Database
    from mirror.db.session import init_db_pool, close_db_pool
    await init_db_pool()

    # Qdrant collections (idempotent)
    from mirror.core.memory.qdrant_init import init_qdrant_collections
    await init_qdrant_collections()

    # NATS
    from mirror.events.nats_client import nats_client
    await nats_client.connect(settings.nats_url)

    logger.info("mirror.startup.complete")
    yield

    # Shutdown
    logger.info("mirror.shutdown")
    await nats_client.close()
    await close_db_pool()
    logger.info("mirror.shutdown.complete")


app = FastAPI(title="Mirror", version="0.1.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


@app.get("/ready")
async def ready():
    return JSONResponse({"status": "ready"})
