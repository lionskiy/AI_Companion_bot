import json

import structlog

from mirror.services.dialog_state import IntentResult

logger = structlog.get_logger()

INTENTS = ["astrology", "tarot", "daily_ritual", "chat", "help", "cancel"]

_CLASSIFY_PROMPT = (
    "Classify the user's intent into exactly one of: "
    "astrology, tarot, daily_ritual, chat, help, cancel.\n\n"
    "Intent definitions:\n"
    "- daily_ritual: morning ritual, card of the day (карта дня), daily affirmation, ежедневный ритуал\n"
    "- tarot: tarot spread/reading, fortune telling, past-present-future, расклад, гадание\n"
    "- astrology: birth chart, transits, horoscope, натальная карта, транзиты\n"
    "- help: asking what the bot can do\n"
    "- cancel: stop, change topic\n"
    "- chat: everything else\n\n"
    'Reply with JSON: {{"intent": "<intent>", "confidence": <0.0-1.0>}}\n\n'
    "User message: {message}"
)


class IntentRouter:
    def __init__(self, llm_router) -> None:
        self._llm = llm_router

    async def classify(self, text: str) -> IntentResult:
        try:
            raw = await self._llm.call(
                task_kind="intent_classify",
                messages=[
                    {"role": "user", "content": _CLASSIFY_PROMPT.format(message=text[:500])}
                ],
                response_format={"type": "json_object"},
            )
            data = json.loads(raw)
            intent = data.get("intent", "chat")
            confidence = float(data.get("confidence", 0.5))

            if intent not in INTENTS or confidence < 0.5:
                intent = "chat"
                confidence = 1.0

            return IntentResult(intent=intent, confidence=confidence)
        except Exception:
            logger.warning("intent_router.classify_failed")
            return IntentResult(intent="chat", confidence=1.0)
