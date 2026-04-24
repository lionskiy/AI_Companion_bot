"""Stage 5: cleanup temp files and staging DB rows after successful ingest."""
import shutil
from pathlib import Path

import structlog
from sqlalchemy import text

import mirror.db.session as db_module

logger = structlog.get_logger()


async def cleanup_job(job_id: str, tmp_path: str | None) -> None:
    """Delete disk files, staging rows, and mark job done-cleanup."""
    # Remove disk files
    if tmp_path:
        try:
            shutil.rmtree(tmp_path, ignore_errors=True)
        except Exception as e:
            logger.warning("cleanup.rmtree_failed", job_id=job_id, error=str(e))

    # Delete staging chunks (they're in Qdrant now)
    async with db_module.async_session_factory() as session:
        await session.execute(
            text("DELETE FROM ingest_chunks WHERE job_id=:jid"),
            {"jid": job_id},
        )
        # Clear text_path from files (keep metadata rows)
        await session.execute(
            text("UPDATE ingest_files SET text_path=NULL, updated_at=now() WHERE job_id=:jid"),
            {"jid": job_id},
        )
        await session.commit()


async def cleanup_stale_dirs() -> None:
    """On startup: remove dirs for jobs that are already done (disk leaked)."""
    ingest_root = Path("/data/ingest")
    if not ingest_root.exists():
        return
    async with db_module.async_session_factory() as session:
        rows = (await session.execute(
            text("SELECT id, tmp_path FROM ingest_jobs WHERE status='done' AND tmp_path IS NOT NULL")
        )).fetchall()
    cleaned_ids = []
    for row in rows:
        job_id, tmp_path = row[0], row[1]
        if tmp_path and Path(tmp_path).exists():
            try:
                shutil.rmtree(tmp_path, ignore_errors=True)
            except Exception:
                pass
        cleaned_ids.append(job_id)

    if cleaned_ids:
        async with db_module.async_session_factory() as session:
            await session.execute(
                text("UPDATE ingest_jobs SET tmp_path=NULL WHERE id = ANY(:ids)"),
                {"ids": cleaned_ids},
            )
            await session.commit()
