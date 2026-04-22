from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    WELLBEING = "wellbeing"
    RISK_SIGNAL = "risk_signal"
    REFERRAL_HINT = "referral_hint"
    CRISIS = "crisis"


@dataclass
class PolicyResult:
    risk_level: RiskLevel
    sales_allowed: bool
    blocked: bool
    crisis_response: str | None
    referral_hint: str | None
