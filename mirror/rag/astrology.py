import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter

from mirror.config import settings

logger = structlog.get_logger()


async def search_astro_knowledge(
    query: str,
    natal_context: str,
    llm_router,
    top_k: int = 5,
) -> list[str]:
    try:
        full_query = f"{query}\n{natal_context}" if natal_context else query
        embedding = await llm_router.embed(full_query)

        qdrant = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            response = await qdrant.query_points(
                collection_name="knowledge_astro",
                query=embedding,
                limit=top_k,
                with_payload=True,
            )
        finally:
            await qdrant.close()

        chunks = []
        for r in response.points:
            text = r.payload.get("text") or r.payload.get("content", "")
            if text:
                chunks.append(text)
        return chunks
    except Exception:
        logger.warning("rag.astrology_search_failed")
        return []
