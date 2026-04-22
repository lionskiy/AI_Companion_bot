import re

CRISIS_PATTERNS: list[tuple[str, str]] = [
    # crisis — суицид / самоповреждение
    (r"не хочу (больше )?жить", "crisis"),
    (r"хочу умереть", "crisis"),
    (r"покончить с (собой|жизнью)", "crisis"),
    (r"суицид", "crisis"),
    (r"kill myself", "crisis"),
    (r"want to die", "crisis"),
    (r"порезать себя", "crisis"),
    (r"прощайте все", "crisis"),
    # risk_signal — выраженный дистресс
    (r"всё бессмысленно", "risk_signal"),
    (r"нет смысла (жить|в жизни)", "risk_signal"),
    (r"никому не нужен", "risk_signal"),
    (r"больше не могу", "risk_signal"),
    # referral_hint — запрос на специалиста
    (r"нужен (психолог|психотерапевт|специалист)", "referral_hint"),
    (r"хочу к (психологу|терапевту)", "referral_hint"),
]

_PRIORITY = {"crisis": 3, "risk_signal": 2, "referral_hint": 1}


def fast_pattern_match(text: str) -> str | None:
    text_lower = text.lower()
    found = [level for pattern, level in CRISIS_PATTERNS if re.search(pattern, text_lower)]
    if not found:
        return None
    return max(found, key=lambda lvl: _PRIORITY.get(lvl, 0))
