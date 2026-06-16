"""RAG search for dream symbols in knowledge_dreams collection."""
import structlog
from qdrant_client import AsyncQdrantClient

from mirror.config import settings

logger = structlog.get_logger()


async def search_dream_knowledge(
    symbols: list[str],
    llm_router,
    top_k_per_symbol: int = 3,
) -> list[dict]:
    """
    Embeds each symbol and searches knowledge_dreams.
    Returns list[{"symbol": str, "interpretation": str, "lunar_context": str}].
    Symbols not found in KB are silently skipped.
    """
    if not symbols:
        return []

    results = []
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        for symbol in symbols[:20]:
            try:
                embedding = await llm_router.embed(symbol)
                response = await qdrant.query_points(
                    collection_name="knowledge_dreams",
                    query=embedding,
                    limit=top_k_per_symbol,
                    with_payload=True,
                )
                for point in response.points:
                    if point.score > 0.6:
                        payload = point.payload or {}
                        results.append({
                            "symbol": symbol,
                            "interpretation": payload.get("interpretation", payload.get("content", "")),
                            "lunar_context": payload.get("lunar_context", ""),
                        })
            except Exception:
                logger.warning("rag.dreams.symbol_failed", symbol=symbol)
    finally:
        await qdrant.close()

    return results
