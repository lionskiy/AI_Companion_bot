"""Semantic enrichment: contextual prefix + payload metadata (keywords, category)."""
import asyncio
import json
import re
from typing import Optional

import structlog

logger = structlog.get_logger()

_ENRICH_SEM: asyncio.Semaphore | None = None
_DEFAULT_CATEGORY_LIST = [
    "КПТ", "психоанализ", "травма", "отношения", "детская_психология",
    "саморазвитие", "духовность", "нарратив", "тревога", "депрессия", "другое",
]
_METADATA_BATCH = 50


def get_enrich_sem(concurrency: int = 4) -> asyncio.Semaphore:
    global _ENRICH_SEM
    if _ENRICH_SEM is None:
        _ENRICH_SEM = asyncio.Semaphore(concurrency)
    return _ENRICH_SEM


async def enrich_context(text_sample: str, llm_router, concurrency: int = 4) -> Optional[str]:
    """Generate a 2-3 sentence document summary for contextual prefix embedding."""
    sem = get_enrich_sem(concurrency)
    prompt = (
        "Прочитай фрагмент документа. Напиши 2-3 предложения:\n"
        "1. О чём этот документ в целом\n"
        "2. Какие основные темы/концепции рассматриваются\n"
        "3. Для кого он предназначен\n\n"
        f"Текст:\n{text_sample[:2000]}"
    )
    try:
        async with sem:
            result = await llm_router.call(
                task_kind="kb_enrich_context",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
            )
        return result.strip() if result else None
    except Exception as e:
        logger.warning("enricher.context_failed", error=str(e))
        return None


async def enrich_metadata_batch(
    chunks: list[str],
    llm_router,
    category_list: Optional[list[str]] = None,
    concurrency: int = 4,
) -> list[dict]:
    """Extract keywords + category for each chunk. Returns list of {keywords, category}."""
    if not chunks:
        return []
    sem = get_enrich_sem(concurrency)
    cats = category_list or _DEFAULT_CATEGORY_LIST
    results: list[dict] = [{"keywords": None, "category": None}] * len(chunks)

    # Process in batches of _METADATA_BATCH
    for batch_start in range(0, len(chunks), _METADATA_BATCH):
        batch = chunks[batch_start: batch_start + _METADATA_BATCH]
        numbered = "\n\n".join(
            f"[{i + 1}] {t[:800]}" for i, t in enumerate(batch)
        )
        prompt = (
            f"Для каждого пронумерованного фрагмента извлеки:\n"
            f"- keywords: 3-5 ключевых слов через запятую\n"
            f"- category: одна из {cats}\n\n"
            f"Формат ответа строго: [N] keywords: ... | category: ...\n\n"
            f"{numbered}"
        )
        try:
            async with sem:
                response = await llm_router.call(
                    task_kind="kb_enrich_metadata",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000,
                    temperature=0.1,
                )
            batch_meta = _parse_metadata_response(response, len(batch))
        except Exception as e:
            logger.warning("enricher.metadata_batch_failed",
                           batch_start=batch_start, error=str(e))
            batch_meta = [{"keywords": None, "category": None}] * len(batch)

        for i, meta in enumerate(batch_meta):
            results[batch_start + i] = meta

    return results


def _parse_metadata_response(text: str, expected: int) -> list[dict]:
    """Parse [N] keywords: ... | category: ... format."""
    result = [{"keywords": None, "category": None}] * expected
    pattern = re.compile(
        r"\[(\d+)\]\s*keywords:\s*([^|]+)\|\s*category:\s*(.+?)(?=\[\d+\]|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        idx = int(m.group(1)) - 1
        if 0 <= idx < expected:
            result[idx] = {
                "keywords": m.group(2).strip(),
                "category": m.group(3).strip().split("\n")[0].strip(),
            }
    return result


def get_category_list(app_config_value: Optional[str]) -> list[str]:
    """Parse category list from app_config JSON value, fallback to default."""
    if app_config_value:
        try:
            parsed = json.loads(app_config_value)
            if isinstance(parsed, list) and parsed:
                return parsed
        except Exception:
            pass
    return _DEFAULT_CATEGORY_LIST
