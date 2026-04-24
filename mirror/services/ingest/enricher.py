"""Semantic enrichment: contextual prefix + payload metadata (keywords, category)."""
import asyncio
import json
import re
from typing import Optional

import structlog

logger = structlog.get_logger()

_DEFAULT_CATEGORY_LIST = [
    "КПТ", "психоанализ", "травма", "отношения", "детская_психология",
    "саморазвитие", "духовность", "нарратив", "тревога", "депрессия", "другое",
]
_METADATA_BATCH = 50


async def enrich_context(
    text_sample: str,
    llm_router,
    sem: asyncio.Semaphore,
) -> Optional[str]:
    """Generate a 2-3 sentence document summary for contextual prefix embedding."""
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
    category_list: Optional[list[str]],
    sem: asyncio.Semaphore,
) -> list[dict]:
    """Extract keywords + category for each chunk. Batches run concurrently via gather."""
    if not chunks:
        return []
    cats = category_list or _DEFAULT_CATEGORY_LIST

    async def _one_batch(batch_start: int) -> tuple[int, list[dict]]:
        batch = chunks[batch_start: batch_start + _METADATA_BATCH]
        numbered = "\n\n".join(f"[{i + 1}] {t[:800]}" for i, t in enumerate(batch))
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
            return batch_start, _parse_metadata_response(response, len(batch))
        except Exception as e:
            logger.warning("enricher.metadata_batch_failed",
                           batch_start=batch_start, error=str(e))
            return batch_start, [{"keywords": None, "category": None}] * len(batch)

    batch_starts = list(range(0, len(chunks), _METADATA_BATCH))
    batch_results = await asyncio.gather(*[_one_batch(s) for s in batch_starts])

    results: list[dict] = [{"keywords": None, "category": None}] * len(chunks)
    for start, meta_list in batch_results:
        for i, meta in enumerate(meta_list):
            results[start + i] = meta
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
    """Parse category list from app_config value (comma-separated or JSON list)."""
    if app_config_value:
        v = app_config_value.strip()
        # Try JSON list first
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list) and parsed:
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        # Comma-separated plain text
        cats = [c.strip() for c in v.split(",") if c.strip()]
        if cats:
            return cats
    return _DEFAULT_CATEGORY_LIST
