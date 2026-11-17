"""Post-call summary: deterministic, factual, built only from facts present in the call state.

An LLM provider may rewrite the wording (feature flag), but the rules summary is always generated first and is the
fallback, so a summary can never mention something the engine did not observe.
"""

from datetime import datetime

from sparta.domain.enums import (
    CallCategory,
    OwnerActionType,
    RecommendedAction,
    RiskLevel,
    SignalCode,
    SignalKind,
)
from sparta.domain.models import CallSummary, ConversationContext, RiskAssessment, RiskSignal, utcnow

S = SignalCode

# What the caller did, strongest first. Only one phrase per signal family is used.
ACT_PHRASES: list[tuple[SignalCode, str]] = [
    (S.OTP_REQUEST, "asked for a one-time password (OTP)"),
    (S.PIN_REQUEST, "asked for a PIN"),
    (S.CVV_REQUEST, "asked for card security details"),
    (S.PASSWORD_REQUEST, "asked for a password"),
    (S.AUTH_OR_RECOVERY_CODE_REQUEST, "asked for an authentication or recovery code"),
    (S.CARD_OR_ACCOUNT_CREDENTIAL_REQUEST, "asked for card or bank account details"),
    (S.IDENTITY_DOCUMENT_REQUEST, "asked for identity details"),
    (S.REMOTE_ACCESS_REQUEST, "asked to install remote-access software"),
    (S.SCREEN_SHARING_REQUEST, "asked for screen sharing"),
    (S.GIFT_CARD_OR_CRYPTO_REQUEST, "asked for gift cards or cryptocurrency"),
    (S.PAYMENT_OR_TRANSFER_REQUEST, "demanded a payment"),
    (S.ARREST_OR_LEGAL_THREAT, "threatened arrest or legal action"),
    (S.RULE_OVERRIDE_ATTEMPT, "tried to override the assistant's rules"),
    (S.FALSE_OWNER_AUTHORIZATION, "claimed the owner had authorized sharing protected details"),
    (S.SUSPICIOUS_PRIZE, "announced a prize or reward"),
    (S.FAKE_KYC_URGENCY, "pressed for an urgent KYC update"),
    (S.ACCOUNT_CLOSURE_THREAT, "threatened to block an account"),
    (S.MALICIOUS_LINK_OR_CALLBACK, "pushed a link or an unknown callback number"),
    (S.ADDRESS_OR_LOCATION_REQUEST, "asked about the owner's address or location"),
    (S.OWNER_AVAILABILITY_PROBE, "asked whether the owner was home or available"),
    (S.HARASSMENT_OR_ABUSE, "used abusive language"),
    (S.TELEMARKETING, "pitched a sales offer"),
    (S.LEGIT_EMERGENCY_CONTEXT, "mentioned a possible emergency"),
    (S.LEGIT_SCHOOL_OR_HOSPITAL, "called about a hospital or school matter"),
    (S.LEGIT_DELIVERY_COORDINATION, "was coordinating a delivery"),
    (S.LEGIT_RECRUITER_INTRO, "was arranging a job interview"),
    (S.LEGIT_APPOINTMENT_CONFIRMATION, "was confirming an appointment"),
    (S.LEGIT_SUPPORT_CALLBACK, "was following up on a support request"),
    (S.LEGIT_KNOWN_SERVICE_CALLBACK, "was returning a call"),
    (S.LEGIT_FAMILY_OR_FRIEND, "said they were a family member, friend or colleague"),
]

REPRESENTS: dict[SignalCode, str] = {
    S.IMPERSONATION_BANK: "a bank",
    S.IMPERSONATION_POLICE: "the police",
    S.IMPERSONATION_GOVERNMENT: "a government agency",
    S.IMPERSONATION_COURIER: "a courier company",
    S.IMPERSONATION_EMPLOYER: "an employer or recruiter",
}

PROTECTED_ACTS = {
    S.OTP_REQUEST,
    S.PIN_REQUEST,
    S.CVV_REQUEST,
    S.PASSWORD_REQUEST,
    S.AUTH_OR_RECOVERY_CODE_REQUEST,
    S.CARD_OR_ACCOUNT_CREDENTIAL_REQUEST,
    S.IDENTITY_DOCUMENT_REQUEST,
    S.REMOTE_ACCESS_REQUEST,
    S.SCREEN_SHARING_REQUEST,
    S.GIFT_CARD_OR_CRYPTO_REQUEST,
    S.PAYMENT_OR_TRANSFER_REQUEST,
}


def _acts(signals: list[RiskSignal], limit: int = 2) -> list[str]:
    present = {s.code for s in signals}
    out: list[str] = []
    for code, base_phrase in ACT_PHRASES:
        if code not in present:
            continue
        if code is S.LEGIT_SCHOOL_OR_HOSPITAL and S.LEGIT_EMERGENCY_CONTEXT in present:
            continue  # the emergency phrase already covers it
        landmark = code is S.ADDRESS_OR_LOCATION_REQUEST and S.LEGIT_DELIVERY_COORDINATION in present
        out.append("asked for a landmark to find the building" if landmark else base_phrase)
    return out[:limit]


def _who(ctx: ConversationContext, signals: list[RiskSignal]) -> str:
    claim = ctx.caller_claim
    subject = f"Caller {claim.name}" if claim.name else "Caller"
    present = {s.code for s in signals}
    descriptors = [text for code, text in REPRESENTS.items() if code in present]
    if descriptors:
        base = f"{subject} claimed to represent {descriptors[0]}"
        return f"{base} ({claim.organization})" if claim.organization else base
    if claim.organization:
        return f"{subject} from {claim.organization}"
    if claim.role:
        return f"{subject} identified as a {claim.role}"
    if ctx.language_profile == "unsupported" and not signals:
        return f"{subject} spoke in a language Sparta does not support yet"
    return f"{subject} did not say who they were" if not signals and not ctx.purpose else subject


def _what(ctx: ConversationContext, signals: list[RiskSignal], who: str) -> str:
    acts = _acts(signals)
    joiner = " and " if any(marker in who for marker in (" claimed ", " identified ")) else " "
    if acts:
        return f"{who}{joiner}{' and '.join(acts)}."
    if ctx.purpose and ctx.caller_turns:
        return f"{who}{joiner}said the call was about {ctx.purpose}."
    if ctx.caller_turns == 0:
        return "The caller did not say anything."
    return f"{who}."


def _action_sentence(ctx: ConversationContext, risk: RiskAssessment, simulated: bool) -> str:
    reason = ctx.ended_reason or ""
    protected = any(s.code in PROTECTED_ACTS for s in risk.signals)
    tag = " (simulated)" if simulated else ""
    if reason == "refused_and_ended":
        return "Sparta refused and ended the call."
    if reason == "high_risk_ended":
        return "Sparta ended the call."
    if reason == "spam_ended":
        return "Sparta ended the call as unwanted."
    if reason == "abusive_caller":
        return "Sparta ended the call because of abusive language."
    if reason == "silence":
        return (
            "The caller stayed silent, so Sparta ended the call."
            if risk.category is CallCategory.SILENT
            else "The caller stopped responding, so Sparta ended the call."
        )
    if reason == "unsupported_language":
        return "The caller used a language Sparta does not support yet, so Sparta took a message."
    if reason == "owner_ended":
        return "The owner ended the call."
    if reason == "blocked_by_owner":
        return "The owner blocked the caller and the call was ended."
    if reason == "max_duration":
        return "The call reached the maximum duration and was ended."
    if reason == "abandoned":
        return "The call was abandoned and closed automatically."
    if ctx.owner_decision is OwnerActionType.TAKEOVER:
        return f"The owner took over the call{tag}."
    if ctx.escalation_id:
        extra = " and refused to share protected details" if protected else ""
        decided = " The owner let Sparta continue." if ctx.owner_decision is OwnerActionType.CONTINUE else ""
        return f"Sparta alerted the owner{extra}.{decided}"
    if ctx.action_taken in {"took_message", "owner_unavailable_took_message"} or reason == "message_taken":
        return "Sparta took a message."
    return "The call ended."


def _owner_sentence(ctx: ConversationContext, risk: RiskAssessment) -> tuple[str, bool]:
    handled = ctx.owner_decision in (OwnerActionType.TAKEOVER, OwnerActionType.END, OwnerActionType.BLOCK)
    legit = risk.category.value.startswith("legitimate")
    if handled:
        return "", False
    if risk.recommended_action is RecommendedAction.HUMAN_REVIEW:
        return "Please review this call.", True
    if risk.requires_owner_attention or (legit and ctx.escalation_id):
        if risk.category is CallCategory.LEGITIMATE_URGENT:
            return "The owner should call back promptly.", True
        return "The owner may want to call back.", True
    if legit:
        return "The owner may want to call back.", True
    extras = set(risk.additional_actions)
    if RecommendedAction.BLOCK_RECOMMENDED in extras:
        return "No owner action is required; blocking this number is recommended.", False
    if risk.risk_level is RiskLevel.HIGH or risk.category is CallCategory.TELEMARKETING:
        return "No owner action is required.", False
    return "No owner action is required.", False


def build_summary(
    call_id: str,
    ctx: ConversationContext,
    risk: RiskAssessment | None,
    *,
    simulated: bool = False,
    now: datetime | None = None,
) -> CallSummary:
    """One-sentence factual summary. ``now`` is the injected clock's time (deterministic replays)."""
    created = now or utcnow()
    if risk is None:
        return CallSummary(
            call_id=call_id,
            text="The call ended before Sparta could assess it.",
            created_at=created,
        )
    signals = [s for s in risk.signals if s.kind in (SignalKind.RISK, SignalKind.LEGITIMATE)]
    who = _who(ctx, signals)
    first = _what(ctx, signals, who)
    second = _action_sentence(ctx, risk, simulated)
    third, attention = _owner_sentence(ctx, risk)
    text = " ".join(part for part in (first, second, third) if part)
    return CallSummary(
        call_id=call_id,
        text=text,
        category=risk.category,
        risk_level=risk.risk_level,
        action_taken=ctx.action_taken,
        owner_action_required=attention,
        generated_by="rules-v1",
        created_at=created,
    )
