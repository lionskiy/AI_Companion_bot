import asyncio
import math
from abc import ABC, abstractmethod

import structlog

logger = structlog.get_logger()


class BaseReranker(ABC):
    @abstractmethod
    async def score(self, query: str, candidates: list[str]) -> list[float]:
        """Returns list[float] same length as candidates, normalized 0.0-1.0."""


class LLMReranker(BaseReranker):
    """Uses LLM to score relevance. More accurate, more expensive (~$0.001/call)."""

    def __init__(self, llm_router) -> None:
        self._llm = llm_router

    async def score(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        try:
            import json
            prompt = (
                f"Rate the relevance of each text to the query on a scale 0.0-1.0.\n"
                f"Query: {query}\n\n"
                f"Texts:\n"
                + "\n".join(f"{i}. {c[:300]}" for i, c in enumerate(candidates))
                + '\n\nReply with JSON: {"scores": [<float>, ...]}'
            )
            raw = await self._llm.call(
                task_kind="rerank",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            data = json.loads(raw)
            scores = [float(s) for s in data.get("scores", [])]
            if len(scores) == len(candidates):
                return scores
        except Exception:
            logger.warning("reranker.llm_failed")
        return [1.0] * len(candidates)


class CrossEncoderReranker(BaseReranker):
    """Local cross-encoder model. Faster (~10ms), no API cost."""

    MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self) -> None:
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.MODEL_NAME)

    async def score(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        self._load_model()
        loop = asyncio.get_event_loop()
        pairs = [(query, c) for c in candidates]
        raw_scores = await loop.run_in_executor(None, self._model.predict, pairs)
        return [1 / (1 + math.exp(-float(s))) for s in raw_scores]


class DisabledReranker(BaseReranker):
    """No-op reranker — returns 1.0 for all candidates."""

    async def score(self, query: str, candidates: list[str]) -> list[float]:
        return [1.0] * len(candidates)


def get_reranker(reranker_type: str, llm_router=None) -> BaseReranker:
    if reranker_type == "llm" and llm_router is not None:
        return LLMReranker(llm_router)
    if reranker_type == "cross_encoder":
        return CrossEncoderReranker()
    return DisabledReranker()
