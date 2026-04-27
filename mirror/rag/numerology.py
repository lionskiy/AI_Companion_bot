"""RAG search for numerology number interpretations in knowledge_numerology collection."""
import structlog
from qdrant_client import AsyncQdrantClient

from mirror.config import settings

logger = structlog.get_logger()


async def search_numerology_knowledge(
    numbers: list[int],
    llm_router,
    top_k_per_number: int = 3,
) -> list[dict]:
    """
    Embeds each number query and searches knowledge_numerology.
    Returns list[{"number": int, "aspect": str, "title": str, "description": str}].
    Numbers not found in KB are silently skipped.
    """
    if not numbers:
        return []

    results = []
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        for number in numbers:
            try:
                query_text = f"число {number} жизненный путь значение"
                embedding = await llm_router.embed(query_text)
                response = await qdrant.query_points(
                    collection_name="knowledge_numerology",
                    query=embedding,
                    limit=top_k_per_number,
                    with_payload=True,
                )
                for point in response.points:
                    if point.score > 0.6:
                        payload = point.payload or {}
                        results.append({
                            "number": number,
                            "aspect": payload.get("aspect", ""),
                            "title": payload.get("title", ""),
                            "description": payload.get("description", payload.get("content", "")),
                            "personal_year_meaning": payload.get("personal_year_meaning", ""),
                        })
            except Exception:
                logger.warning("rag.numerology.number_failed", number=number)
    finally:
        await qdrant.close()

    return results
