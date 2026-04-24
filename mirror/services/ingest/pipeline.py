"""KB Ingest v2 pipeline: stages 1-5 for ZIP and single-file ingest."""
import asyncio
import json
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import structlog
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import text

import mirror.db.session as db_module
from mirror.config import settings
from mirror.services.ingest.chunker import chunk_text
from mirror.services.ingest.cleanup import cleanup_job
from mirror.services.ingest.embedder import EmbeddingRateLimiter, get_embedding_tier
from mirror.services.ingest.enricher import enrich_context, enrich_metadata_batch, get_category_list
from mirror.services.ingest.extractor import _THREAD_POOL, detect_lang, extract_text_sync

logger = structlog.get_logger()

_EXTRACT_SEM = asyncio.Semaphore(10)
_CHUNK_SEM = asyncio.Semaphore(10)
_INGEST_DATA_ROOT = "/data/ingest"

# ── helpers ───────────────────────────────────────────────────────────────────


async def _log(job_id: str, level: str, stage: str, message: str, details: dict | None = None) -> None:
    try:
        async with db_module.async_session_factory() as s:
            await s.execute(
                text(
                    "INSERT INTO ingest_logs (job_id, level, stage, message, details) "
                    "VALUES (:jid, :lv, :st, :msg, CAST(:det AS json))"
                ),
                {"jid": job_id, "lv": level, "st": stage, "msg": message,
                 "det": json.dumps(details or {})},
            )
            await s.commit()
    except Exception as e:
        logger.warning("ingest.db_log_failed", job_id=job_id, stage=stage, message=message, error=str(e))


async def _update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{k}=:{k}" for k in fields)
    async with db_module.async_session_factory() as s:
        await s.execute(
            text(f"UPDATE ingest_jobs SET {set_clause}, updated_at=now() WHERE id=:job_id"),
            {"job_id": job_id, **fields},
        )
        await s.commit()


async def _increment_job(job_id: str, **counters) -> None:
    if not counters:
        return
    set_clause = ", ".join(f"{k}={k}+:{k}" for k in counters)
    async with db_module.async_session_factory() as s:
        await s.execute(
            text(f"UPDATE ingest_jobs SET {set_clause}, updated_at=now() WHERE id=:job_id"),
            {"job_id": job_id, **counters},
        )
        await s.commit()


async def _get_app_config(key: str, default: str = "") -> str:
    try:
        async with db_module.async_session_factory() as s:
            row = (await s.execute(
                text("SELECT value FROM app_config WHERE key=:k"), {"k": key}
            )).fetchone()
        return row[0] if row else default
    except Exception:
        return default


async def _ensure_collection(name: str) -> None:
    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    try:
        existing = {c.name for c in (await client.get_collections()).collections}
        if name not in existing:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
            )
            logger.info("pipeline.collection_created", collection=name)
    finally:
        await client.close()


# ── Stage 2: Extract ──────────────────────────────────────────────────────────


async def _extract_one_file(
    job_id: str, file_bytes: bytes, filename: str, collection: str, topic: str,
) -> Optional[str]:
    """Extract text from one file, write to disk, insert ingest_files row. Returns file_id or None."""
    file_id = str(uuid.uuid4())
    async with _EXTRACT_SEM:
        loop = asyncio.get_running_loop()
        try:
            raw_text = await loop.run_in_executor(
                _THREAD_POOL, extract_text_sync, file_bytes, filename
            )
        except Exception as e:
            # Record error but don't abort the whole job
            async with db_module.async_session_factory() as s:
                await s.execute(
                    text(
                        "INSERT INTO ingest_files (id, job_id, filename, collection, topic, "
                        "file_status, error, created_at, updated_at) "
                        "VALUES (:id, :jid, :fn, :col, :tp, 'error', :err, now(), now())"
                    ),
                    {"id": file_id, "jid": job_id, "fn": filename,
                     "col": collection, "tp": topic, "err": str(e)[:500]},
                )
                await s.commit()
            await _log(job_id, "warning", "extract", "file_extract_failed",
                       {"filename": filename, "error": str(e)})
            return None

    if not raw_text or not raw_text.strip():
        return None

    # Detect language
    source_lang = detect_lang(raw_text)

    # Write text to disk (off the event loop — can be large)
    text_dir = Path(_INGEST_DATA_ROOT) / job_id / "texts"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = str(text_dir / f"{file_id}.txt")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, Path(text_path).write_text, raw_text, "utf-8")

    char_count = len(raw_text)
    async with db_module.async_session_factory() as s:
        await s.execute(
            text(
                "INSERT INTO ingest_files (id, job_id, filename, collection, topic, source_lang, "
                "text_path, char_count, file_status, created_at, updated_at) "
                "VALUES (:id, :jid, :fn, :col, :tp, :sl, :tp2, :cc, 'extracted', now(), now())"
            ),
            {"id": file_id, "jid": job_id, "fn": filename, "col": collection,
             "tp": topic, "sl": source_lang, "tp2": text_path, "cc": char_count},
        )
        await s.commit()

    await _increment_job(job_id, files_extracted=1)
    await _log(job_id, "info", "extract", "file_extracted",
               {"filename": filename, "char_count": char_count, "source_lang": source_lang, "file_id": file_id})
    return file_id


# ── Stage 3: Chunk + Enrich ───────────────────────────────────────────────────


async def _chunk_and_enrich_file(
    job_id: str, file_id: str, filename: str,
    enrichment_context: bool, enrichment_metadata: bool,
    llm_router, category_list: list[str], enrich_sem: asyncio.Semaphore,
) -> int:
    """Chunk file text, enrich, insert ingest_chunks. Returns count of chunks inserted.

    _CHUNK_SEM is held only during disk I/O + text splitting.
    LLM enrichment runs outside the semaphore so all files can enrich concurrently,
    limited only by enrich_sem (one shared semaphore per job).
    """
    # ── Phase 1: read + chunk (hold _CHUNK_SEM only here) ────────────────────
    async with _CHUNK_SEM:
        async with db_module.async_session_factory() as s:
            row = (await s.execute(
                text("SELECT text_path, source_lang FROM ingest_files WHERE id=:fid"),
                {"fid": file_id},
            )).fetchone()
            if not row or not row[0]:
                return 0
            text_path, source_lang = row[0], row[1]

        try:
            loop = asyncio.get_running_loop()
            raw_text = await loop.run_in_executor(None, Path(text_path).read_text, "utf-8")
        except Exception as e:
            await _log(job_id, "warning", "chunk", "text_read_failed",
                       {"file_id": file_id, "error": str(e)})
            return 0

        async with db_module.async_session_factory() as s:
            await s.execute(
                text("UPDATE ingest_files SET file_status='chunking', updated_at=now() WHERE id=:fid"),
                {"fid": file_id},
            )
            await s.commit()

        chunks = chunk_text(raw_text)
        if not chunks:
            return 0
    # _CHUNK_SEM released — LLM enrichment runs concurrently across all files

    # ── Phase 2: LLM enrichment — context + metadata run in parallel ─────────
    async def _get_context() -> Optional[str]:
        if not enrichment_context:
            return None
        return await enrich_context(raw_text[:2000], llm_router, enrich_sem)

    async def _get_metadata() -> list[dict]:
        if not enrichment_metadata:
            return [{"keywords": None, "category": None}] * len(chunks)
        return await enrich_metadata_batch(chunks, llm_router, category_list, enrich_sem)

    doc_context, metadata_list = await asyncio.gather(_get_context(), _get_metadata())

    if doc_context:
        async with db_module.async_session_factory() as s:
            await s.execute(
                text("UPDATE ingest_files SET document_context=:dc, updated_at=now() WHERE id=:fid"),
                {"dc": doc_context, "fid": file_id},
            )
            await s.commit()
        await _log(job_id, "info", "enrich", "context_generated",
                   {"file_id": file_id, "doc_context_len": len(doc_context)})

    # ── Phase 3: insert chunks to DB ─────────────────────────────────────────
    chunk_rows = [
        {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "file_id": file_id,
            "chunk_index": i,
            "text": chunk,
            "keywords": meta.get("keywords"),
            "category": meta.get("category"),
        }
        for i, (chunk, meta) in enumerate(zip(chunks, metadata_list))
    ]

    if chunk_rows:
        async with db_module.async_session_factory() as s:
            await s.execute(
                text(
                    "INSERT INTO ingest_chunks (id, job_id, file_id, chunk_index, text, "
                    "keywords, category, chunk_status, created_at) "
                    "VALUES (:id, :job_id, :file_id, :chunk_index, :text, "
                    ":keywords, :category, 'pending', now())"
                ),
                chunk_rows,
            )
            await s.execute(
                text("UPDATE ingest_files SET file_status='chunked', chunk_count=:n, "
                     "updated_at=now() WHERE id=:fid"),
                {"n": len(chunks), "fid": file_id},
            )
            await s.commit()

    await _increment_job(job_id, files_chunked=1)
    await _log(job_id, "info", "chunk", "file_chunked",
               {"filename": filename, "chunk_count": len(chunks), "file_id": file_id})

    if enrichment_metadata:
        await _increment_job(job_id, enrichment_done=len(chunks))

    return len(chunks)


# ── Stage 4: Embed ────────────────────────────────────────────────────────────


async def _embed_and_upsert_batch(
    job_id: str,
    batch_rows: list[dict],  # {id, text, doc_context, keywords, category, collection, topic, source_lang}
    rate_limiter: EmbeddingRateLimiter,
    embed_sem: asyncio.Semaphore,
    llm_router,
) -> int:
    """Embed one batch, upsert to Qdrant, update DB. Returns count of upserted chunks."""
    if not batch_rows:
        return 0

    # Build input texts: prepend doc_context if available.
    # Truncate to 8 000 chars — at worst-case Russian tokenization (~1 char/token)
    # this stays under OpenAI's per-item 8 192-token hard limit.
    _MAX_CHARS_PER_ITEM = 8_000
    texts = []
    for row in batch_rows:
        dc = row.get("doc_context") or ""
        chunk_text_val = row["text"]
        combined = f"{dc}\n---\n{chunk_text_val}" if dc else chunk_text_val
        if len(combined) > _MAX_CHARS_PER_ITEM:
            combined = combined[:_MAX_CHARS_PER_ITEM]
        texts.append(combined)

    tokens_estimate = sum(len(t) // 2 for t in texts)  # ~2 chars/token for Russian

    async with embed_sem:
        await rate_limiter.acquire(tokens_estimate)
        routing = await llm_router._get_routing("embedding", "*")
        api_key = llm_router._get_api_key(routing.provider_id)

        embeddings = None
        last_err: Exception | None = None
        for attempt in range(3):
            client = AsyncOpenAI(api_key=api_key, timeout=90)
            try:
                resp = await client.embeddings.create(model=routing.model_id, input=texts)
                embeddings = [e.embedding for e in sorted(resp.data, key=lambda x: x.index)]
                break
            except Exception as e:
                last_err = e
                await client.close()
                if attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))  # 5s, 10s
                continue
            finally:
                await client.close()

        if embeddings is None:
            await _log(job_id, "error", "embed", "batch_failed",
                       {"error": str(last_err), "batch_size": len(texts), "attempts": 3})
            return 0

        # Group by collection for Qdrant upsert
        by_collection: dict[str, list] = {}
        for row, vector in zip(batch_rows, embeddings):
            col = row["collection"]
            if col not in by_collection:
                by_collection[col] = []
            point_id = row["id"]  # chunk_id → idempotent retry (same chunk → same Qdrant point)
            payload = {
                "topic": row.get("topic", ""),
                "text": row["text"],
                "collection": col,
                "lang": row.get("source_lang", "ru"),
                "source_lang": row.get("source_lang", "ru"),
                "file_id": row["file_id"],
                "has_context": bool(row.get("doc_context")),
            }
            if row.get("keywords"):
                payload["keywords"] = row["keywords"]
            if row.get("category"):
                payload["category"] = row["category"]
            by_collection[col].append((point_id, row["id"], vector, payload))

        qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
        try:
            for col, items in by_collection.items():
                points = [
                    PointStruct(id=point_id, vector=vector, payload=payload)
                    for point_id, _, vector, payload in items
                ]
                await qdrant.upsert(collection_name=col, points=points, wait=False)

                # Bulk-update chunk statuses using a VALUES join
                chunk_ids = [chunk_id for _, chunk_id, _, _ in items]
                point_ids = [point_id for point_id, _, _, _ in items]
                async with db_module.async_session_factory() as s:
                    await s.execute(
                        text(
                            "UPDATE ingest_chunks AS ic SET chunk_status='done', "
                            "qdrant_point_id=v.pid "
                            "FROM (SELECT unnest(CAST(:cids AS text[])) AS cid, "
                            "             unnest(CAST(:pids AS text[])) AS pid) AS v "
                            "WHERE ic.id = v.cid"
                        ),
                        {"cids": chunk_ids, "pids": point_ids},
                    )
                    await s.commit()
        finally:
            await qdrant.close()

        n = len(batch_rows)
        await _increment_job(job_id, chunks_done=n, qdrant_upserted=n)
        await _log(job_id, "info", "embed", "batch_embedded",
                   {"batch_size": n, "tokens_estimate": tokens_estimate})
        return n


# ── Main pipeline ─────────────────────────────────────────────────────────────


async def run_ingest_job_v2(
    job_id: str,
    filename: str,
    collection: str,
    file_topic: str,
    llm_router,
) -> int:
    """Full pipeline stages 1-5. Returns total chunks upserted."""
    tmp_path = str(Path(_INGEST_DATA_ROOT) / job_id)
    original_path = Path(tmp_path)

    # Load enrichment config
    enrichment_context = (await _get_app_config("kb_enrichment_context", "true")).lower() == "true"
    enrichment_metadata = (await _get_app_config("kb_enrichment_metadata", "true")).lower() == "true"
    enrich_concurrency = int(await _get_app_config("kb_enrich_concurrency", "4"))
    category_list_raw = await _get_app_config("kb_category_list", "")
    category_list = get_category_list(category_list_raw)

    is_zip = filename.lower().endswith(".zip")
    zip_path = original_path / "original.zip"
    single_path = next(original_path.glob("original.*"), None) if not is_zip else None

    # ── Stage 2: Extract ──────────────────────────────────────────────────────
    await _update_job(job_id, stage="extract")

    file_ids: list[tuple[str, str, str]] = []  # (file_id, filename, collection)

    if is_zip:
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP не найден на диске: {zip_path}")
        try:
            with zipfile.ZipFile(str(zip_path)) as zf:
                names = [
                    n for n in zf.namelist()
                    if not n.endswith("/") and not n.startswith("__MACOSX")
                    and not n.split("/")[-1].startswith(".")
                ]

                # Detect sub-collections from folder structure
                folder_collections = {
                    parts[0]
                    for n in names
                    for parts in [n.split("/")]
                    if len(parts) > 1 and parts[0].startswith("knowledge_")
                }
                for col in folder_collections:
                    await _ensure_collection(col)

                await _update_job(job_id, files_total=len(names))

                # Pre-read all entries sequentially off the event loop (ZipFile is not thread-safe)
                loop = asyncio.get_running_loop()
                file_bytes_map: dict[str, bytes] = {}
                for name in names:
                    file_bytes_map[name] = await loop.run_in_executor(_THREAD_POOL, zf.read, name)

                async def _extract_zip_entry(name: str) -> Optional[str]:
                    parts = name.split("/")
                    fname = parts[-1]
                    if not fname:
                        return None
                    target_col = parts[0] if len(parts) > 1 and parts[0].startswith("knowledge_") else collection
                    book_name = fname.rsplit(".", 1)[0]
                    topic = f"{file_topic} / {book_name}" if file_topic else book_name
                    raw = file_bytes_map[name]
                    fid = await _extract_one_file(job_id, raw, fname, target_col, topic)
                    if fid:
                        file_ids.append((fid, fname, target_col))
                    return fid

                results = await asyncio.gather(
                    *[_extract_zip_entry(n) for n in names], return_exceptions=True
                )
                ok = sum(1 for r in results if r and not isinstance(r, Exception))
        except zipfile.BadZipFile as e:
            raise ValueError(f"Некорректный ZIP: {e}") from e
    else:
        # Single file
        if not single_path or not single_path.exists():
            raise FileNotFoundError(f"Файл не найден на диске: {tmp_path}")
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, single_path.read_bytes)
        await _update_job(job_id, files_total=1)
        fid = await _extract_one_file(job_id, raw, filename, collection, file_topic)
        ok = 0
        if fid:
            file_ids.append((fid, filename, collection))
            ok = 1

    # files_extracted already incremented per-file inside _extract_one_file
    await _update_job(job_id, stage="chunk")

    if not file_ids:
        raise ValueError("Ни один файл не удалось обработать")

    # ── Stage 3: Chunk + Enrich ───────────────────────────────────────────────
    # One semaphore per job controls concurrent LLM enrichment calls across all files.
    enrich_sem = asyncio.Semaphore(enrich_concurrency)
    chunk_tasks = [
        _chunk_and_enrich_file(
            job_id, fid, fname, enrichment_context, enrichment_metadata,
            llm_router, category_list, enrich_sem,
        )
        for fid, fname, _ in file_ids
    ]
    chunk_counts = await asyncio.gather(*chunk_tasks, return_exceptions=True)
    total_chunks = sum(c for c in chunk_counts if isinstance(c, int) and c > 0)

    # files_chunked already incremented per-file inside _chunk_and_enrich_file
    await _update_job(
        job_id,
        chunks_total=total_chunks,
        enrichment_total=total_chunks if enrichment_metadata else 0,
        stage="embed",
    )

    if total_chunks == 0:
        raise ValueError("Нет чанков для эмбеддинга")

    # ── Stage 4: Embed ────────────────────────────────────────────────────────
    tier = await get_embedding_tier(llm_router)
    await _update_job(job_id, tier=tier.name)

    rate_limiter = EmbeddingRateLimiter(tpm=tier.tpm, rpm=tier.rpm)
    embed_sem = asyncio.Semaphore(tier.max_concurrent)

    # Load all pending chunks with doc_context (JOIN ingest_files)
    async with db_module.async_session_factory() as s:
        rows = (await s.execute(
            text(
                "SELECT ic.id, ic.text, ic.keywords, ic.category, ic.file_id, "
                "inf.document_context, inf.collection, inf.topic, inf.source_lang "
                "FROM ingest_chunks ic "
                "JOIN ingest_files inf ON ic.file_id = inf.id "
                "WHERE ic.job_id=:jid AND ic.chunk_status='pending' "
                "ORDER BY ic.chunk_index"
            ),
            {"jid": job_id},
        )).fetchall()

    chunk_data = [
        {
            "id": r[0], "text": r[1], "keywords": r[2], "category": r[3],
            "file_id": r[4], "doc_context": r[5], "collection": r[6],
            "topic": r[7], "source_lang": r[8],
        }
        for r in rows
    ]

    # Ensure all collections exist
    collections_needed = {r["collection"] for r in chunk_data}
    for col in collections_needed:
        await _ensure_collection(col)

    # Split into batches by token estimate (not just chunk count) to stay under 300K token limit
    # Use //2 (≈2 chars/token) for Cyrillic-heavy text; //4 is too optimistic for Russian.
    _MAX_TOKENS_PER_BATCH = 200_000  # conservative — OpenAI hard limit is 300K
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_tokens = 0
    for row in chunk_data:
        dc = row.get("doc_context") or ""
        row_tokens = (len(dc) + len(row["text"]) + 4) // 2
        if current_batch and (current_tokens + row_tokens > _MAX_TOKENS_PER_BATCH or len(current_batch) >= tier.batch_size):
            batches.append(current_batch)
            current_batch = [row]
            current_tokens = row_tokens
        else:
            current_batch.append(row)
            current_tokens += row_tokens
    if current_batch:
        batches.append(current_batch)

    embed_results = await asyncio.gather(
        *[_embed_and_upsert_batch(job_id, batch, rate_limiter, embed_sem, llm_router)
          for batch in batches],
        return_exceptions=True,
    )
    total_upserted = sum(r for r in embed_results if isinstance(r, int) and r > 0)
    failed_batches = sum(
        1 for r in embed_results if isinstance(r, Exception) or (isinstance(r, int) and r == 0)
    )

    await _log(job_id, "info", "embed", "embed_stage_done",
               {"total_upserted": total_upserted, "total_chunks": total_chunks,
                "failed_batches": failed_batches})

    if failed_batches > 0:
        logger.warning("ingest.embed_partial",
                       job_id=job_id, upserted=total_upserted, total=total_chunks,
                       failed_batches=failed_batches)
        raise RuntimeError(
            f"Неполный ingest: {total_upserted} из {total_chunks} чанков загружено, "
            f"{failed_batches} батч(ей) провалилось"
        )

    # ── Stage 5: Cleanup ─────────────────────────────────────────────────────
    await _update_job(job_id, stage="cleanup")
    await cleanup_job(job_id, tmp_path)
    await _log(job_id, "info", "cleanup", "job_done",
               {"total_chunks": total_chunks, "qdrant_upserted": total_upserted})

    return total_upserted


# ── Embed-only resume ─────────────────────────────────────────────────────────


async def run_embed_stage_only(job_id: str, llm_router) -> int:
    """Resume embed stage for a job that previously failed during embedding.

    Only processes chunks with chunk_status='pending'. Chunks already marked 'done'
    are already in Qdrant — skipping them prevents duplication and wasted tokens.
    Returns total chunks now in Qdrant (previously done + newly upserted).
    """
    async with db_module.async_session_factory() as s:
        done_count = (await s.execute(
            text("SELECT COUNT(*) FROM ingest_chunks WHERE job_id=:jid AND chunk_status='done'"),
            {"jid": job_id},
        )).scalar() or 0
        pending_count = (await s.execute(
            text("SELECT COUNT(*) FROM ingest_chunks WHERE job_id=:jid AND chunk_status='pending'"),
            {"jid": job_id},
        )).scalar() or 0
        tmp_row = (await s.execute(
            text("SELECT tmp_path FROM ingest_jobs WHERE id=:jid"), {"jid": job_id}
        )).fetchone()
        tmp_path = tmp_row[0] if tmp_row else None

    if pending_count == 0:
        raise ValueError("Нет чанков со статусом 'pending' для повторного эмбеддинга")

    total_chunks = done_count + pending_count
    await _update_job(job_id, stage="embed")
    await _log(job_id, "info", "embed", "embed_resume_started",
               {"done_before": done_count, "pending": pending_count})

    tier = await get_embedding_tier(llm_router)
    await _update_job(job_id, tier=tier.name)

    rate_limiter = EmbeddingRateLimiter(tpm=tier.tpm, rpm=tier.rpm)
    embed_sem = asyncio.Semaphore(tier.max_concurrent)

    async with db_module.async_session_factory() as s:
        rows = (await s.execute(
            text(
                "SELECT ic.id, ic.text, ic.keywords, ic.category, ic.file_id, "
                "inf.document_context, inf.collection, inf.topic, inf.source_lang "
                "FROM ingest_chunks ic "
                "JOIN ingest_files inf ON ic.file_id = inf.id "
                "WHERE ic.job_id=:jid AND ic.chunk_status='pending' "
                "ORDER BY ic.chunk_index"
            ),
            {"jid": job_id},
        )).fetchall()

    chunk_data = [
        {
            "id": r[0], "text": r[1], "keywords": r[2], "category": r[3],
            "file_id": r[4], "doc_context": r[5], "collection": r[6],
            "topic": r[7], "source_lang": r[8],
        }
        for r in rows
    ]

    for col in {r["collection"] for r in chunk_data}:
        await _ensure_collection(col)

    _MAX_TOKENS_PER_BATCH = 200_000
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_tokens = 0
    for row in chunk_data:
        dc = row.get("doc_context") or ""
        row_tokens = (len(dc) + len(row["text"]) + 4) // 2
        if current_batch and (current_tokens + row_tokens > _MAX_TOKENS_PER_BATCH or len(current_batch) >= tier.batch_size):
            batches.append(current_batch)
            current_batch = [row]
            current_tokens = row_tokens
        else:
            current_batch.append(row)
            current_tokens += row_tokens
    if current_batch:
        batches.append(current_batch)

    embed_results = await asyncio.gather(
        *[_embed_and_upsert_batch(job_id, batch, rate_limiter, embed_sem, llm_router)
          for batch in batches],
        return_exceptions=True,
    )
    total_upserted = sum(r for r in embed_results if isinstance(r, int) and r > 0)
    failed_batches = sum(
        1 for r in embed_results if isinstance(r, Exception) or (isinstance(r, int) and r == 0)
    )

    await _log(job_id, "info", "embed", "embed_stage_done",
               {"total_upserted": total_upserted, "total_chunks": total_chunks,
                "failed_batches": failed_batches, "resumed_from_done": done_count})

    if failed_batches > 0:
        logger.warning("ingest.embed_partial",
                       job_id=job_id, upserted=done_count + total_upserted, total=total_chunks,
                       failed_batches=failed_batches)
        raise RuntimeError(
            f"Неполный ingest: {done_count + total_upserted} из {total_chunks} чанков загружено, "
            f"{failed_batches} батч(ей) провалилось"
        )

    await _update_job(job_id, stage="cleanup")
    if tmp_path:
        await cleanup_job(job_id, tmp_path)
    await _log(job_id, "info", "cleanup", "job_done",
               {"total_chunks": total_chunks, "qdrant_upserted": done_count + total_upserted})

    return done_count + total_upserted
