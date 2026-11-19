"""Shared vocabulary of the Sparta domain. Values are part of the public API contract."""

from enum import StrEnum


class CallState(StrEnum):
    """Explicit conversation states. Transitions are validated in ``sparta.orchestrator.state_machine``."""

    INITIALIZING = "INITIALIZING"
    DISCLOSURE = "DISCLOSURE"
    IDENTIFY_CALLER = "IDENTIFY_CALLER"
    IDENTIFY_PURPOSE = "IDENTIFY_PURPOSE"
    CLARIFY = "CLARIFY"
    ASSESSING = "ASSESSING"
    SAFE_CONTINUE = "SAFE_CONTINUE"
    ESCALATE = "ESCALATE"
    REFUSE_SENSITIVE_REQUEST = "REFUSE_SENSITIVE_REQUEST"
    END_SPAM = "END_SPAM"
    END_SILENCE = "END_SILENCE"
    OWNER_TAKEOVER = "OWNER_TAKEOVER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TERMINAL_STATES: frozenset[CallState] = frozenset({CallState.COMPLETED, CallState.FAILED})
ENDING_STATES: frozenset[CallState] = frozenset({CallState.END_SPAM, CallState.END_SILENCE})


class CallStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


class RiskLevel(StrEnum):
    """``unknown`` means there is not enough evidence yet. Sparta never shows certainty it does not have."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecommendedAction(StrEnum):
    CONTINUE_SCREENING = "continue_screening"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
    ESCALATE_TO_OWNER = "escalate_to_owner"
    REFUSE_AND_END = "refuse_and_end"
    END_SPAM = "end_spam"
    BLOCK_RECOMMENDED = "block_recommended"
    REPORT_RECOMMENDED = "report_recommended"
    HUMAN_REVIEW = "human_review"


class SignalSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SignalKind(StrEnum):
    RISK = "risk"
    LEGITIMATE = "legitimate"


class SignalCode(StrEnum):
    """Risk and legitimacy signal identifiers (stable, versioned with the safety policy)."""

    # Protected-information requests
    OTP_REQUEST = "OTP_REQUEST"
    PASSWORD_REQUEST = "PASSWORD_REQUEST"  # signal id, not a credential  # noqa: S105  # nosec B105
    PIN_REQUEST = "PIN_REQUEST"
    CVV_REQUEST = "CVV_REQUEST"
    CARD_OR_ACCOUNT_CREDENTIAL_REQUEST = "CARD_OR_ACCOUNT_CREDENTIAL_REQUEST"
    AUTH_OR_RECOVERY_CODE_REQUEST = "AUTH_OR_RECOVERY_CODE_REQUEST"
    IDENTITY_DOCUMENT_REQUEST = "IDENTITY_DOCUMENT_REQUEST"
    ADDRESS_OR_LOCATION_REQUEST = "ADDRESS_OR_LOCATION_REQUEST"
    OWNER_AVAILABILITY_PROBE = "OWNER_AVAILABILITY_PROBE"
    # Actions demanded of the owner
    REMOTE_ACCESS_REQUEST = "REMOTE_ACCESS_REQUEST"
    SCREEN_SHARING_REQUEST = "SCREEN_SHARING_REQUEST"
    PAYMENT_OR_TRANSFER_REQUEST = "PAYMENT_OR_TRANSFER_REQUEST"
    GIFT_CARD_OR_CRYPTO_REQUEST = "GIFT_CARD_OR_CRYPTO_REQUEST"
    MALICIOUS_LINK_OR_CALLBACK = "MALICIOUS_LINK_OR_CALLBACK"
    # Pressure and threats
    ARREST_OR_LEGAL_THREAT = "ARREST_OR_LEGAL_THREAT"
    ACCOUNT_CLOSURE_THREAT = "ACCOUNT_CLOSURE_THREAT"
    FAKE_KYC_URGENCY = "FAKE_KYC_URGENCY"
    URGENCY_PRESSURE = "URGENCY_PRESSURE"
    SUSPICIOUS_PRIZE = "SUSPICIOUS_PRIZE"
    # Impersonation
    IMPERSONATION_BANK = "IMPERSONATION_BANK"
    IMPERSONATION_GOVERNMENT = "IMPERSONATION_GOVERNMENT"
    IMPERSONATION_POLICE = "IMPERSONATION_POLICE"
    IMPERSONATION_COURIER = "IMPERSONATION_COURIER"
    IMPERSONATION_EMPLOYER = "IMPERSONATION_EMPLOYER"
    # Attacks on the assistant itself
    RULE_OVERRIDE_ATTEMPT = "RULE_OVERRIDE_ATTEMPT"
    FALSE_OWNER_AUTHORIZATION = "FALSE_OWNER_AUTHORIZATION"
    # Conduct
    HARASSMENT_OR_ABUSE = "HARASSMENT_OR_ABUSE"
    TELEMARKETING = "TELEMARKETING"
    # Possibly-legitimate patterns (kind = legitimate)
    LEGIT_DELIVERY_COORDINATION = "LEGIT_DELIVERY_COORDINATION"
    LEGIT_APPOINTMENT_CONFIRMATION = "LEGIT_APPOINTMENT_CONFIRMATION"
    LEGIT_RECRUITER_INTRO = "LEGIT_RECRUITER_INTRO"
    LEGIT_KNOWN_SERVICE_CALLBACK = "LEGIT_KNOWN_SERVICE_CALLBACK"
    LEGIT_FAMILY_OR_FRIEND = "LEGIT_FAMILY_OR_FRIEND"
    LEGIT_SCHOOL_OR_HOSPITAL = "LEGIT_SCHOOL_OR_HOSPITAL"
    LEGIT_EMERGENCY_CONTEXT = "LEGIT_EMERGENCY_CONTEXT"
    LEGIT_SUPPORT_CALLBACK = "LEGIT_SUPPORT_CALLBACK"


class CallCategory(StrEnum):
    """Owner-facing classification of a call."""

    UNKNOWN = "unknown"
    SILENT = "silent"
    POSSIBLE_FINANCIAL_IMPERSONATION = "possible_financial_impersonation"
    POSSIBLE_GOVERNMENT_IMPERSONATION = "possible_government_impersonation"
    POSSIBLE_COURIER_IMPERSONATION = "possible_courier_impersonation"
    POSSIBLE_TECH_SUPPORT_SCAM = "possible_tech_support_scam"
    POSSIBLE_PRIZE_SCAM = "possible_prize_scam"
    POSSIBLE_EMPLOYER_IMPERSONATION = "possible_employer_impersonation"
    PROMPT_INJECTION_ATTEMPT = "prompt_injection_attempt"
    TELEMARKETING = "telemarketing"
    HARASSMENT = "harassment"
    LEGITIMATE_DELIVERY = "legitimate_delivery"
    LEGITIMATE_APPOINTMENT = "legitimate_appointment"
    LEGITIMATE_RECRUITER = "legitimate_recruiter"
    LEGITIMATE_SUPPORT_CALLBACK = "legitimate_support_callback"
    LEGITIMATE_PERSONAL = "legitimate_personal"
    LEGITIMATE_URGENT = "legitimate_urgent"


class Speaker(StrEnum):
    CALLER = "caller"
    ASSISTANT = "assistant"
    OWNER = "owner"
    SYSTEM = "system"


class TurnSource(StrEnum):
    TYPED = "typed"
    BROWSER_STT = "browser_stt"
    PROVIDER_STT = "provider_stt"
    UPLOADED_AUDIO = "uploaded_audio"
    SCRIPTED = "scripted"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ProviderKind(StrEnum):
    SIMULATOR = "simulator"
    AZURE = "azure"
    ANDROID_SCREENING = "android_screening"
    ASTERISK = "asterisk"
    OTHER = "other"


class CallMode(StrEnum):
    CONVERSATIONAL = "conversational"
    SCREENING_ONLY = "screening_only"


class OwnerActionType(StrEnum):
    TAKEOVER = "takeover"
    CONTINUE = "continue"
    END = "end"
    BLOCK = "block"
    TRUST = "trust"
    UNBLOCK = "unblock"
    UNTRUST = "untrust"


class EscalationStatus(StrEnum):
    REQUESTED = "requested"
    TAKEN_OVER = "taken_over"
    CONTINUED = "continued"
    ENDED = "ended"
    EXPIRED = "expired"


class FeedbackKind(StrEnum):
    CORRECT_CLASSIFICATION = "correct_classification"
    WAS_SPAM = "was_spam"
    WAS_LEGITIMATE = "was_legitimate"
    WRONG_LANGUAGE = "wrong_language"
    POOR_TRANSCRIPTION = "poor_transcription"
    WRONG_SUMMARY = "wrong_summary"
    TRUST_CALLER = "trust_caller"
    BLOCK_CALLER = "block_caller"


class ScreeningStrictness(StrEnum):
    RELAXED = "relaxed"
    BALANCED = "balanced"
    STRICT = "strict"


class ResponseStyle(StrEnum):
    CONCISE = "concise"
    WARM = "warm"
    FORMAL = "formal"


class VoiceStatus(StrEnum):
    NOT_ENROLLED = "not_enrolled"
    CONSENT_RECORDED = "consent_recorded"
    PENDING_PROVIDER_APPROVAL = "pending_provider_approval"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class EventType(StrEnum):
    """Live WebSocket event names."""

    CALL_SNAPSHOT = "call.snapshot"
    CALL_CREATED = "call.created"
    CALL_CONNECTED = "call.connected"
    CALL_LISTENING = "call.listening"
    STATE_CHANGED = "state.changed"
    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"
    LANGUAGE_CHANGED = "language.changed"
    RISK_UPDATED = "risk.updated"
    ASSISTANT_SPEAKING = "assistant.speaking"
    ASSISTANT_FINISHED = "assistant.finished"
    ASSISTANT_INTERRUPTED = "assistant.interrupted"
    ESCALATION_REQUESTED = "escalation.requested"
    OWNER_TAKEOVER = "owner.takeover"
    OWNER_ACTION = "owner.action"
    CALL_ENDED = "call.ended"
    SUMMARY_CREATED = "summary.created"
    PROVIDER_ERROR = "provider.error"
