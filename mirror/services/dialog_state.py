from dataclasses import dataclass
from typing import TypedDict


class DialogState(TypedDict):
    # input
    user_id: str
    session_id: str
    message: str
    tier: str
    is_first_message: bool

    # after classify_intent
    intent: str | None
    intent_conf: float | None

    # after check_policy
    risk_level: str | None
    sales_allowed: bool
    blocked: bool
    crisis_response: str | None
    referral_hint: str | None

    # memory context (assembled in route_mode)
    session_history: list[dict]
    memory_context: dict  # {"episodes": [...], "facts": [...]}
    psych_chunks: list[str]  # relevant KB chunks from knowledge_psych
    psych_profile: dict  # inferred psychological portrait from user_profiles

    # after generate_response
    response: str | None
    mode_used: str | None


@dataclass
class IntentResult:
    intent: str
    confidence: float
