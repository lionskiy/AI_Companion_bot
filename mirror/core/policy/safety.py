from uuid import UUID

import structlog
from sqlalchemy import select, text

import mirror.db.session as db_module
from mirror.core.policy.models import PolicyResult, RiskLevel
from mirror.core.policy.patterns import fast_pattern_match
from mirror.events.publishers.safety import publish_crisis_detected
from mirror.models.policy import SafetyLog

logger = structlog.get_logger()

DEFAULT_CRISIS_RESPONSE = (
    "Я здесь, и я слышу тебя. То, что ты чувствуешь — важно.\n\n"
    "Пожалуйста, позвони на бесплатную линию психологической помощи:\n"
    "📞 8-800-2000-122 (бесплатно, круглосуточно)\n\n"
    "Напиши мне, когда будешь готов. Я никуда не ухожу."
)

DEFAULT_REFERRAL_HINT = (
    "Если чувствуешь, что нужна поддержка живого специалиста — "
    "это нормально и правильно. Психолог поможет разобраться глубже 💙"
)


class PolicyEngine:
    def __init__(self, llm_router=None) -> None:
        self._llm_router = llm_router
        self._crisis_response: str | None = None
        self._referral_hint: str | None = None

    async def _load_templates(self) -> None:
        if self._crisis_response is not None:
            return
        try:
            async with db_module.async_session_factory() as session:
                row = await session.execute(
                    text("SELECT key, value FROM app_config WHERE key IN ('crisis_response', 'referral_hint')")
                )
                rows = {r[0]: r[1] for r in row.fetchall()}
            self._crisis_response = rows.get("crisis_response", DEFAULT_CRISIS_RESPONSE)
            self._referral_hint = rows.get("referral_hint", DEFAULT_REFERRAL_HINT)
        except Exception:
            self._crisis_response = DEFAULT_CRISIS_RESPONSE
            self._referral_hint = DEFAULT_REFERRAL_HINT

    async def check(self, user_id: UUID, text_: str, session_id: UUID | None = None) -> PolicyResult:
        await self._load_templates()

        pattern_level = fast_pattern_match(text_)

        if pattern_level is None:
            return PolicyResult(
                risk_level=RiskLevel.WELLBEING,
                sales_allowed=True,
                blocked=False,
                crisis_response=None,
                referral_hint=None,
            )

        # LLM подтверждает уровень (если доступен)
        if self._llm_router is not None:
            confirmed_level = await self._llm_classify(text_)
        else:
            confirmed_level = RiskLevel(pattern_level)

        result = self._build_result(confirmed_level)
        await self._log_incident(user_id, session_id, confirmed_level, result)

        if confirmed_level == RiskLevel.CRISIS:
            await publish_crisis_detected(str(user_id), str(session_id) if session_id else None)

        return result

    def _build_result(self, level: RiskLevel) -> PolicyResult:
        if level == RiskLevel.CRISIS:
            return PolicyResult(
                risk_level=RiskLevel.CRISIS,
                sales_allowed=False,
                blocked=True,
                crisis_response=self._crisis_response or DEFAULT_CRISIS_RESPONSE,
                referral_hint=None,
            )
        if level == RiskLevel.RISK_SIGNAL:
            return PolicyResult(
                risk_level=RiskLevel.RISK_SIGNAL,
                sales_allowed=False,
                blocked=False,
                crisis_response=None,
                referral_hint=None,
            )
        if level == RiskLevel.REFERRAL_HINT:
            return PolicyResult(
                risk_level=RiskLevel.REFERRAL_HINT,
                sales_allowed=False,
                blocked=False,
                crisis_response=None,
                referral_hint=self._referral_hint or DEFAULT_REFERRAL_HINT,
            )
        return PolicyResult(
            risk_level=RiskLevel.WELLBEING,
            sales_allowed=True,
            blocked=False,
            crisis_response=None,
            referral_hint=None,
        )

    async def _llm_classify(self, text_: str) -> RiskLevel:
        prompt = (
            "Classify the risk level of the following message. "
            "Reply with exactly one word: crisis, risk_signal, referral_hint, or wellbeing.\n\n"
            f"Message: {text_}"
        )
        try:
            raw = await self._llm_router.complete(
                messages=[{"role": "user", "content": prompt}],
                task_kind="crisis_classify",
            )
            level_str = raw.strip().lower().split()[0]
            return RiskLevel(level_str)
        except (ValueError, Exception):
            return RiskLevel.WELLBEING

    async def _log_incident(
        self, user_id: UUID, session_id: UUID | None, level: RiskLevel, result: PolicyResult
    ) -> None:
        action = "crisis_response_sent" if result.blocked else "sales_blocked" if not result.sales_allowed else "flagged"
        try:
            async with db_module.async_session_factory() as session:
                log = SafetyLog(
                    user_id=user_id,
                    session_id=session_id,
                    risk_level=level.value,
                    action=action,
                )
                session.add(log)
                await session.commit()
        except Exception:
            logger.warning("policy.log_failed", user_id=str(user_id), risk_level=level.value)
        logger.info("policy.incident", user_id=str(user_id), risk_level=level.value, action=action)
