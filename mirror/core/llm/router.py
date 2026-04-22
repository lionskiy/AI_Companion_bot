import asyncio
import os
import time

import structlog
from anthropic import APIError as AnthropicAPIError
from anthropic import APITimeoutError as AnthropicTimeoutError
from anthropic import AsyncAnthropic
from anthropic import RateLimitError as AnthropicRateLimitError
from openai import APIError as OpenAIAPIError
from openai import APITimeoutError as OpenAITimeoutError
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError
from sqlalchemy import select, text

import mirror.db.session as db_module
from mirror.core.llm.exceptions import AllModelsUnavailableError
from mirror.models.llm import LLMProvider, LLMRouting

logger = structlog.get_logger()

CANONICAL_TASK_KINDS = {
    "main_chat", "main_chat_premium", "intent_classify", "crisis_classify",
    "memory_summarize", "memory_extract_facts", "tarot_interpret",
    "astro_interpret", "game_narration", "proactive_compose",
    "persona_evolve", "embedding",
}

_RETRY_ERRORS_OPENAI = (OpenAIRateLimitError, OpenAITimeoutError)
_RETRY_ERRORS_ANTHROPIC = (AnthropicRateLimitError, AnthropicTimeoutError)
_BREAK_ERRORS_OPENAI = (OpenAIAPIError,)
_BREAK_ERRORS_ANTHROPIC = (AnthropicAPIError,)


def sanitize_input(text_: str) -> str:
    return text_[:4000].strip()


class LLMRouter:
    _routing_cache: dict[tuple[str, str], LLMRouting] = {}
    _provider_cache: dict[str, LLMProvider] = {}

    async def call(
        self,
        task_kind: str,
        messages: list[dict],
        tier: str = "free",
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict | None = None,
    ) -> str:
        routing = await self._get_routing(task_kind, tier)
        mt = max_tokens or routing.max_tokens
        temp = temperature if temperature is not None else float(routing.temperature)

        models_to_try = [(routing.provider_id, routing.model_id)] + [
            (f["provider_id"], f["model_id"]) for f in (routing.fallback_chain or [])
        ]

        for provider_id, model_id in models_to_try:
            for attempt in range(3):
                t0 = time.monotonic()
                try:
                    result = await self._call_provider(
                        provider_id, model_id, messages, mt, temp, response_format
                    )
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    logger.info(
                        "llm.call_ok",
                        task_kind=task_kind,
                        tier=tier,
                        provider=provider_id,
                        attempt=attempt + 1,
                        latency_ms=latency_ms,
                    )
                    return result
                except _RETRY_ERRORS_OPENAI + _RETRY_ERRORS_ANTHROPIC:
                    if attempt < 2:
                        await asyncio.sleep(2.0)
                        continue
                    break
                except _BREAK_ERRORS_OPENAI + _BREAK_ERRORS_ANTHROPIC:
                    logger.warning("llm.provider_error", task_kind=task_kind, provider=provider_id, attempt=attempt + 1)
                    break
                except Exception:
                    logger.warning("llm.unexpected_error", task_kind=task_kind, provider=provider_id, attempt=attempt + 1)
                    break

        raise AllModelsUnavailableError()

    # Alias used by MemoryService and others
    async def complete(self, messages: list[dict], task_kind: str, tier: str = "free") -> str:
        return await self.call(task_kind=task_kind, messages=messages, tier=tier)

    async def embed(self, text_: str) -> list[float]:
        routing = await self._get_routing("embedding", "*")
        api_key = self._get_api_key(routing.provider_id)
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.embeddings.create(model=routing.model_id, input=sanitize_input(text_))
        return resp.data[0].embedding

    def invalidate_cache(self) -> None:
        self._routing_cache.clear()
        self._provider_cache.clear()

    async def validate_routing(self) -> None:
        """Startup guard: raises ValueError if any canonical task_kind is missing."""
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(LLMRouting.task_kind).where(LLMRouting.tier == "*")
            )
            covered = {row[0] for row in result.fetchall()}
        missing = CANONICAL_TASK_KINDS - covered
        if missing:
            raise ValueError(f"LLM routing missing for task_kinds: {missing}")
        logger.info("llm.routing_validated", count=len(covered))

    async def _get_routing(self, task_kind: str, tier: str) -> LLMRouting:
        key = (task_kind, tier)
        if key not in self._routing_cache:
            row = await self._fetch_routing(task_kind, tier)
            if row is None:
                # fallback to wildcard tier
                row = await self._fetch_routing(task_kind, "*")
            if row is None:
                raise ValueError(f"No routing for task_kind={task_kind!r} tier={tier!r}")
            self._routing_cache[key] = row
        return self._routing_cache[key]

    async def _fetch_routing(self, task_kind: str, tier: str) -> LLMRouting | None:
        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(LLMRouting).where(
                    LLMRouting.task_kind == task_kind,
                    LLMRouting.tier == tier,
                )
            )
            return result.scalar_one_or_none()

    def _get_api_key(self, provider_id: str) -> str:
        env_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
        env_var = env_map.get(provider_id, f"{provider_id.upper()}_API_KEY")
        key = os.environ.get(env_var, "")
        return key

    async def _call_provider(
        self,
        provider_id: str,
        model_id: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        response_format: dict | None,
    ) -> str:
        api_key = self._get_api_key(provider_id)

        if provider_id == "openai":
            client = AsyncOpenAI(api_key=api_key)
            kwargs: dict = dict(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if response_format:
                kwargs["response_format"] = response_format
            resp = await client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content

        elif provider_id == "anthropic":
            client = AsyncAnthropic(api_key=api_key)
            system_msgs = [m["content"] for m in messages if m["role"] == "system"]
            chat_msgs = [m for m in messages if m["role"] != "system"]
            kwargs = dict(
                model=model_id,
                messages=chat_msgs,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if system_msgs:
                kwargs["system"] = "\n\n".join(system_msgs)
            resp = await client.messages.create(**kwargs)
            return resp.content[0].text

        raise ValueError(f"Unknown provider: {provider_id}")
