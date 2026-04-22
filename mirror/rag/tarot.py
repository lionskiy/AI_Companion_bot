import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from mirror.config import settings

logger = structlog.get_logger()


async def search_tarot_knowledge(
    card_name: str,
    user_question: str,
    llm_router,
    top_k: int = 3,
) -> list[str]:
    try:
        query = f"{card_name}: {user_question}"
        embedding = await llm_router.embed(query)

        qdrant = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            response = await qdrant.query_points(
                collection_name="knowledge_tarot",
                query=embedding,
                query_filter=Filter(
                    should=[
                        FieldCondition(key="card_name", match=MatchValue(value=card_name))
                    ]
                ),
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
        logger.warning("rag.tarot_search_failed", card_name=card_name)
        return []
