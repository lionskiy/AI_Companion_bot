import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny

from mirror.config import settings

logger = structlog.get_logger()


async def search_psych_knowledge(
    query: str,
    llm_router,
    top_k: int = 4,
    profile_context: str = "",
) -> list[str]:
    """
    Semantic search over knowledge_psych (CBT, therapy dialogs, emotion frameworks).
    Enriches query with profile context so retrieval is personalized.
    """
    try:
        full_query = f"{query}\n{profile_context}".strip() if profile_context else query
        embedding = await llm_router.embed(full_query)

        qdrant = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            response = await qdrant.query_points(
                collection_name="knowledge_psych",
                query=embedding,
                limit=top_k,
                with_payload=True,
            )
        finally:
            await qdrant.close()

        chunks = []
        for r in response.points:
            text = r.payload.get("text") or r.payload.get("content", "")
            if text and r.score > 0.35:   # relevance threshold
                chunks.append(text)
        return chunks
    except Exception:
        logger.warning("rag.psych_search_failed")
        return []
