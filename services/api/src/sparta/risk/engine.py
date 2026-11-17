"""Risk scoring: combines per-call signals into a structured, explainable assessment.

Design rules (see docs/SAFETY_MODEL.md):
* Deterministic. The same signals always give the same assessment; no model output can lower a critical result.
* Noisy-OR over risk signal weights, a floor for critical signals, and a bounded discount for legitimacy hints that can
  never excuse a protected-information request.
* Confidence is separate from risk and states how much evidence there is; unknown stays unknown.
* Reasons are short evidence statements, never model reasoning.
"""

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from sparta.domain.enums import (
    CallCategory,
    RecommendedAction,
    RiskLevel,
    ScreeningStrictness,
    SignalCode,
    SignalKind,
    SignalSeverity,
)
from sparta.domain.models import CallerClaim, RiskAssessment, RiskSignal, utcnow
from sparta.risk.policy import SafetyPolicy, load_default_policy

S = SignalCode

# Risk signals that may coexist with a legitimate delivery context without making the call a scam. The assistant still
# refuses to hand anything over; it escalates so the owner decides (couriers genuinely ask for delivery OTPs and
# landmarks, and criminals imitate them).
DELIVERY_EXCEPTION_CODES = frozenset(
    {
        S.OTP_REQUEST,
        S.ADDRESS_OR_LOCATION_REQUEST,
        S.OWNER_AVAILABILITY_PROBE,
        S.IMPERSONATION_COURIER,
        S.URGENCY_PRESSURE,
    }
)

LEGIT_ESCALATION_CODES = frozenset(
    {
        S.LEGIT_DELIVERY_COORDINATION,
        S.LEGIT_SCHOOL_OR_HOSPITAL,
        S.LEGIT_EMERGENCY_CONTEXT,
        S.LEGIT_RECRUITER_INTRO,
        S.LEGIT_SUPPORT_CALLBACK,
        S.LEGIT_KNOWN_SERVICE_CALLBACK,
        S.LEGIT_APPOINTMENT_CONFIRMATION,
        S.LEGIT_FAMILY_OR_FRIEND,
    }
)

IMPERSONATION_CATEGORY = {
    S.IMPERSONATION_BANK: CallCategory.POSSIBLE_FINANCIAL_IMPERSONATION,
    S.IMPERSONATION_GOVERNMENT: CallCategory.POSSIBLE_GOVERNMENT_IMPERSONATION,
    S.IMPERSONATION_POLICE: CallCategory.POSSIBLE_GOVERNMENT_IMPERSONATION,
    S.IMPERSONATION_COURIER: CallCategory.POSSIBLE_COURIER_IMPERSONATION,
    S.IMPERSONATION_EMPLOYER: CallCategory.POSSIBLE_EMPLOYER_IMPERSONATION,
}

CATEGORY_TIE_ORDER = [
    CallCategory.POSSIBLE_TECH_SUPPORT_SCAM,
    CallCategory.POSSIBLE_COURIER_IMPERSONATION,
    CallCategory.POSSIBLE_EMPLOYER_IMPERSONATION,
    CallCategory.POSSIBLE_GOVERNMENT_IMPERSONATION,
    CallCategory.POSSIBLE_PRIZE_SCAM,
    CallCategory.POSSIBLE_FINANCIAL_IMPERSONATION,
    CallCategory.HARASSMENT,
    CallCategory.TELEMARKETING,
]

LEGIT_CATEGORY_ORDER = [
    (S.LEGIT_EMERGENCY_CONTEXT, CallCategory.LEGITIMATE_URGENT),
    (S.LEGIT_SCHOOL_OR_HOSPITAL, CallCategory.LEGITIMATE_URGENT),
    (S.LEGIT_DELIVERY_COORDINATION, CallCategory.LEGITIMATE_DELIVERY),
    (S.LEGIT_RECRUITER_INTRO, CallCategory.LEGITIMATE_RECRUITER),
    (S.LEGIT_APPOINTMENT_CONFIRMATION, CallCategory.LEGITIMATE_APPOINTMENT),
    (S.LEGIT_SUPPORT_CALLBACK, CallCategory.LEGITIMATE_SUPPORT_CALLBACK),
    (S.LEGIT_KNOWN_SERVICE_CALLBACK, CallCategory.LEGITIMATE_SUPPORT_CALLBACK),
    (S.LEGIT_FAMILY_OR_FRIEND, CallCategory.LEGITIMATE_PERSONAL),
]

PURPOSE_BY_SIGNAL: list[tuple[SignalCode, str]] = [
    (S.LEGIT_EMERGENCY_CONTEXT, "Possible emergency involving a person"),
    (S.LEGIT_SCHOOL_OR_HOSPITAL, "School or hospital contact"),
    (S.LEGIT_DELIVERY_COORDINATION, "Delivery coordination"),
    (S.LEGIT_RECRUITER_INTRO, "Job interview or recruitment"),
    (S.LEGIT_APPOINTMENT_CONFIRMATION, "Appointment confirmation"),
    (S.LEGIT_SUPPORT_CALLBACK, "Support follow-up"),
    (S.LEGIT_KNOWN_SERVICE_CALLBACK, "Callback about a recent request"),
    (S.LEGIT_FAMILY_OR_FRIEND, "Personal call"),
    (S.RULE_OVERRIDE_ATTEMPT, "Attempt to change the assistant's rules"),
    (S.FALSE_OWNER_AUTHORIZATION, "Claimed owner authorization for protected information"),
    (S.FAKE_KYC_URGENCY, "KYC update"),
    (S.ARREST_OR_LEGAL_THREAT, "Arrest or legal threat"),
    (S.SUSPICIOUS_PRIZE, "Prize or reward claim"),
    (S.REMOTE_ACCESS_REQUEST, "Remote device access"),
    (S.SCREEN_SHARING_REQUEST, "Remote device access"),
    (S.GIFT_CARD_OR_CRYPTO_REQUEST, "Payment demand"),
    (S.PAYMENT_OR_TRANSFER_REQUEST, "Payment demand"),
    (S.OTP_REQUEST, "Request for a verification code"),
    (S.PIN_REQUEST, "Request for security credentials"),
    (S.PASSWORD_REQUEST, "Request for security credentials"),
    (S.CVV_REQUEST, "Request for security credentials"),
    (S.CARD_OR_ACCOUNT_CREDENTIAL_REQUEST, "Request for card or account details"),
    (S.AUTH_OR_RECOVERY_CODE_REQUEST, "Request for security credentials"),
    (S.IDENTITY_DOCUMENT_REQUEST, "Request for identity details"),
    (S.ADDRESS_OR_LOCATION_REQUEST, "Questions about the owner's location"),
    (S.OWNER_AVAILABILITY_PROBE, "Questions about the owner's availability"),
    (S.ACCOUNT_CLOSURE_THREAT, "Account block warning"),
    (S.HARASSMENT_OR_ABUSE, "Abusive call"),
    (S.TELEMARKETING, "Sales offer"),
]


@dataclass
class CallRiskContext:
    call_id: str
    caller_turns: int
    detected_languages: list[str] = field(default_factory=list)
    language_profile: str | None = None
    language_uncertain: bool = False
    min_stt_confidence: float | None = None
    caller_claim: CallerClaim = field(default_factory=CallerClaim)
    stated_purpose: str | None = None
    strictness: ScreeningStrictness = ScreeningStrictness.BALANCED
    silent: bool = False


def _turn_label(ids: list[str]) -> str:
    nums = [i.removeprefix("turn_") for i in ids]
    return f" (turn {', '.join(nums[:3])})" if nums else ""


class RiskEngine:
    def __init__(self, policy: SafetyPolicy | None = None) -> None:
        self.policy = policy or load_default_policy()

    # ------------------------------------------------------------------ main entry
    def assess(self, ctx: CallRiskContext, signals: list[RiskSignal], *, now: datetime | None = None) -> RiskAssessment:
        """Assess the call so far. ``now`` is the injected clock's time (deterministic replays); wall clock if omitted."""
        p = self.policy
        risk = [s for s in signals if s.kind is SignalKind.RISK]
        legit = [s for s in signals if s.kind is SignalKind.LEGITIMATE]
        protected_codes = p.protected_signal_codes()

        critical = [s for s in risk if s.severity is SignalSeverity.CRITICAL]
        protected_hit = [s for s in risk if s.code in protected_codes]
        legit_strength = max((s.weight for s in legit), default=0.0)

        raw = 1.0
        for s in risk:
            raw *= 1.0 - s.weight
        raw = 1.0 - raw
        score = raw
        if not critical and not any(s.severity is SignalSeverity.HIGH for s in protected_hit):
            score = raw * (1.0 - p.thresholds.legit_max_discount * legit_strength)
        if critical:
            score = max(score, p.thresholds.critical_floor)
        score = round(min(max(score, 0.0), 0.999), 3)

        level_cfg = p.strictness[ctx.strictness]
        if score >= level_cfg.high:
            level = RiskLevel.HIGH
        elif score >= level_cfg.medium:
            level = RiskLevel.MEDIUM
        elif signals or ctx.caller_turns >= 2 or ctx.silent:
            level = RiskLevel.LOW
        else:
            level = RiskLevel.UNKNOWN

        delivery_exception = self._delivery_exception(risk, legit)
        category = self._category(ctx, risk, legit, score, level_cfg.medium)
        if delivery_exception:
            category = CallCategory.LEGITIMATE_DELIVERY
        action, extras, attention = self._action(
            ctx, risk, legit, score, level, critical, delivery_exception, category, level_cfg.high
        )
        confidence = self._confidence(ctx, signals, risk, legit, legit_strength, score, level_cfg.medium)
        purpose = self._purpose(ctx, signals)
        reasons = self._reasons(ctx, risk, legit, level, delivery_exception, confidence)

        return RiskAssessment(
            call_id=ctx.call_id,
            detected_languages=ctx.detected_languages,
            language_profile=ctx.language_profile,
            caller_claim=ctx.caller_claim,
            purpose=purpose,
            category=category,
            risk_level=level,
            risk_score=score,
            confidence=confidence,
            signals=sorted(signals, key=lambda s: (-s.weight, s.code.value)),
            recommended_action=action,
            additional_actions=extras,
            requires_owner_attention=attention,
            reasons=reasons,
            policy_version=p.version,
            assessed_at=now or utcnow(),
            turn_count=ctx.caller_turns,
        )

    # ------------------------------------------------------------------ pieces
    def _delivery_exception(self, risk: list[RiskSignal], legit: list[RiskSignal]) -> bool:
        has_delivery = any(s.code is S.LEGIT_DELIVERY_COORDINATION and s.weight >= 0.5 for s in legit)
        return has_delivery and bool(risk) and all(s.code in DELIVERY_EXCEPTION_CODES for s in risk)

    def _category(
        self,
        ctx: CallRiskContext,
        risk: list[RiskSignal],
        legit: list[RiskSignal],
        score: float,
        medium_cut: float,
    ) -> CallCategory:
        codes = {s.code for s in risk}
        if codes & {S.RULE_OVERRIDE_ATTEMPT, S.FALSE_OWNER_AUTHORIZATION}:
            return CallCategory.PROMPT_INJECTION_ATTEMPT
        by_category: dict[CallCategory, float] = {}
        for s in risk:
            cat = self.policy.signals[s.code].category
            if cat is not None:
                by_category[cat] = by_category.get(cat, 0.0) + s.weight
        impersonated = [IMPERSONATION_CATEGORY[c] for c in codes if c in IMPERSONATION_CATEGORY]
        if len(set(impersonated)) == 1:
            by_category[impersonated[0]] = by_category.get(impersonated[0], 0.0) + 0.5
        risk_cats = {c: w for c, w in by_category.items() if w > 0}
        legit_codes = {s.code: s.weight for s in legit}
        scam_present = score >= medium_cut or any(
            s.severity in (SignalSeverity.CRITICAL, SignalSeverity.HIGH) for s in risk
        )
        if risk_cats and (scam_present or not legit_codes):
            best = max(risk_cats.values())
            tied = [c for c, w in risk_cats.items() if abs(w - best) < 1e-9]
            tied.sort(key=lambda c: CATEGORY_TIE_ORDER.index(c) if c in CATEGORY_TIE_ORDER else 99)
            return tied[0]
        for code, cat in LEGIT_CATEGORY_ORDER:
            if code in legit_codes:
                return cat
        if risk_cats:
            return max(risk_cats.items(), key=lambda kv: kv[1])[0]
        if ctx.silent:
            return CallCategory.SILENT
        return CallCategory.UNKNOWN

    def _action(
        self,
        ctx: CallRiskContext,
        risk: list[RiskSignal],
        legit: list[RiskSignal],
        score: float,
        level: RiskLevel,
        critical: list[RiskSignal],
        delivery_exception: bool,
        category: CallCategory,
        high_cut: float,
    ) -> tuple[RecommendedAction, list[RecommendedAction], bool]:
        codes = {s.code for s in risk}
        legit_strength = max((s.weight for s in legit), default=0.0)
        extras: list[RecommendedAction] = []

        if ctx.silent and not risk:
            return RecommendedAction.END_SPAM, extras, False

        if delivery_exception:
            return RecommendedAction.ESCALATE_TO_OWNER, extras, True

        if critical or score >= high_cut:
            if score >= 0.9 and (len(risk) >= 2 or codes & {S.RULE_OVERRIDE_ATTEMPT, S.HARASSMENT_OR_ABUSE}):
                extras.append(RecommendedAction.BLOCK_RECOMMENDED)
            if category not in (CallCategory.HARASSMENT, CallCategory.TELEMARKETING) and len(risk) >= 2:
                extras.append(RecommendedAction.REPORT_RECOMMENDED)
            return RecommendedAction.REFUSE_AND_END, extras, False

        if S.HARASSMENT_OR_ABUSE in codes:
            return RecommendedAction.END_SPAM, [RecommendedAction.BLOCK_RECOMMENDED], False

        probe = codes & {S.ADDRESS_OR_LOCATION_REQUEST, S.OWNER_AVAILABILITY_PROBE}
        if probe and legit_strength < 0.5:
            # Deflect and ask again; the engine ends the call if the caller keeps probing.
            return RecommendedAction.ASK_CLARIFYING_QUESTION, extras, False

        if (
            legit_strength >= 0.5
            and score < level_medium(self.policy, ctx)
            and any(s.code in LEGIT_ESCALATION_CODES for s in legit)
        ):
            return RecommendedAction.ESCALATE_TO_OWNER, extras, True

        if S.TELEMARKETING in codes and legit_strength < 0.5 and score < level_medium(self.policy, ctx) + 0.2:
            return RecommendedAction.END_SPAM, extras, False

        if level is RiskLevel.MEDIUM:
            return RecommendedAction.ASK_CLARIFYING_QUESTION, extras, False

        if ctx.caller_turns < 3 and not ctx.stated_purpose and not legit:
            return RecommendedAction.ASK_CLARIFYING_QUESTION, extras, False
        return RecommendedAction.CONTINUE_SCREENING, extras, False

    def _confidence(
        self,
        ctx: CallRiskContext,
        signals: list[RiskSignal],
        risk: list[RiskSignal],
        legit: list[RiskSignal],
        legit_strength: float,
        score: float,
        medium_cut: float,
    ) -> float:
        strongest = max((s.weight for s in signals), default=0.0)
        conf = 0.30 + 0.45 * strongest + 0.05 * min(ctx.caller_turns, 4)
        conf += 0.08 * min(max(len(risk) - 1, 0), 3)
        if score >= medium_cut and legit_strength >= 0.5:
            conf -= 0.20  # the evidence points both ways
        if ctx.min_stt_confidence is not None and ctx.min_stt_confidence < 0.75:
            conf -= 0.15 * (0.75 - ctx.min_stt_confidence) / 0.75 * 2
        if ctx.language_uncertain:
            conf -= 0.10
        if ctx.silent and not signals:
            conf = max(conf, 0.6)
        return round(min(max(conf, 0.05), 0.95), 3)

    def _purpose(self, ctx: CallRiskContext, signals: list[RiskSignal]) -> str | None:
        present = {s.code for s in signals}
        for code, label in PURPOSE_BY_SIGNAL:
            if code in present:
                return label
        return ctx.stated_purpose

    def _reasons(
        self,
        ctx: CallRiskContext,
        risk: list[RiskSignal],
        legit: list[RiskSignal],
        level: RiskLevel,
        delivery_exception: bool,
        confidence: float,
    ) -> list[str]:
        reasons: list[str] = []
        for s in sorted(risk, key=lambda s: -s.weight)[:4]:
            reasons.append(f"{s.description}{_turn_label(s.evidence_turn_ids)}")
        for s in sorted(legit, key=lambda s: -s.weight)[:2]:
            reasons.append(f"Looks like: {s.description.lower()}{_turn_label(s.evidence_turn_ids)}")
        if delivery_exception:
            reasons.append("Delivery context: protected details still refused; owner decides")
        if not risk and not legit:
            reasons.append(
                "No sensitive-data request or scam pattern detected so far"
                if ctx.caller_turns
                else "Waiting for the caller to speak"
            )
        if confidence < self.policy.thresholds.uncertain_confidence:
            reasons.append("Sparta is uncertain: limited evidence so far")
        if ctx.language_uncertain:
            reasons.append("Language could not be identified reliably")
        return reasons


def level_medium(policy: SafetyPolicy, ctx: CallRiskContext) -> float:
    return policy.strictness[ctx.strictness].medium


@lru_cache
def get_risk_engine() -> RiskEngine:
    return RiskEngine()
