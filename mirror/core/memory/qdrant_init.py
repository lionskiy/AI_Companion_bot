from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

import structlog

from mirror.config import settings

logger = structlog.get_logger()

QDRANT_COLLECTIONS = {
    "user_episodes":        {"size": 3072, "distance": Distance.COSINE},
    "user_facts":           {"size": 3072, "distance": Distance.COSINE},
    "knowledge_astro":      {"size": 3072, "distance": Distance.COSINE},
    "knowledge_tarot":      {"size": 3072, "distance": Distance.COSINE},
    "knowledge_psych":      {"size": 3072, "distance": Distance.COSINE},
    "knowledge_dreams":     {"size": 3072, "distance": Distance.COSINE},
    "knowledge_numerology": {"size": 3072, "distance": Distance.COSINE},
}


async def init_qdrant_collections() -> None:
    client = AsyncQdrantClient(url=settings.qdrant_url)
    existing = {c.name for c in (await client.get_collections()).collections}

    for name, params in QDRANT_COLLECTIONS.items():
        if name not in existing:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=params["size"],
                    distance=params["distance"],
                ),
            )
            logger.info("qdrant.collection_created", name=name)
        else:
            logger.info("qdrant.collection_exists", name=name)

    await client.close()
