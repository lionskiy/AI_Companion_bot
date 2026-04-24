"""Periodic maintenance tasks for KB ingest pipeline."""
import asyncio

import structlog
from celery import shared_task
from sqlalchemy import text

import mirror.db.session as db_module

logger = structlog.get_logger()

_LOG_RETENTION_DAYS = 7
_STALE_MINUTES = 60


@shared_task(name="mirror.workers.tasks.ingest.cleanup_ingest_logs")
def cleanup_ingest_logs() -> dict:
    """Delete ingest_logs older than retention period."""
    return asyncio.run(_cleanup_ingest_logs_async())


async def _cleanup_ingest_logs_async() -> dict:
    async with db_module.async_session_factory() as session:
        result = await session.execute(
            text(
                "DELETE FROM ingest_logs "
                "WHERE created_at < now() - :days * interval '1 day'"
            ),
            {"days": _LOG_RETENTION_DAYS},
        )
        await session.commit()
    deleted = result.rowcount
    logger.info("ingest.cleanup_logs", deleted=deleted, retention_days=_LOG_RETENTION_DAYS)
    return {"deleted": deleted}


@shared_task(name="mirror.workers.tasks.ingest.reset_stale_ingest_jobs")
def reset_stale_ingest_jobs() -> dict:
    """Mark jobs stuck in 'running' for too long as 'error'."""
    return asyncio.run(_reset_stale_async())


async def _reset_stale_async() -> dict:
    async with db_module.async_session_factory() as session:
        result = await session.execute(
            text(
                "UPDATE ingest_jobs SET status='error', error='Зависший процесс: сброс при старте' "
                "WHERE status='running' "
                "AND updated_at < now() - :mins * interval '1 minute'"
            ),
            {"mins": _STALE_MINUTES},
        )
        await session.commit()
    reset = result.rowcount
    if reset:
        logger.warning("ingest.stale_reset", count=reset, stale_minutes=_STALE_MINUTES)
    return {"reset": reset}
