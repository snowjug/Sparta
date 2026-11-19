// String vocabularies of the Sparta API. Values mirror services/api/src/sparta/domain/enums.py exactly.
// When packages/contracts/openapi.json is available, run `npm run types:api` and compare against src/lib/api/generated.ts.

export const CALL_STATES = [
  "INITIALIZING",
  "DISCLOSURE",
  "IDENTIFY_CALLER",
  "IDENTIFY_PURPOSE",
  "CLARIFY",
  "ASSESSING",
  "SAFE_CONTINUE",
  "ESCALATE",
  "REFUSE_SENSITIVE_REQUEST",
  "END_SPAM",
  "END_SILENCE",
  "OWNER_TAKEOVER",
  "COMPLETED",
  "FAILED",
] as const;
export type CallState = (typeof CALL_STATES)[number];

export const CALL_STATUSES = ["active", "ended", "failed"] as const;
export type CallStatus = (typeof CALL_STATUSES)[number];

export const RISK_LEVELS = ["unknown", "low", "medium", "high"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];

export const RECOMMENDED_ACTIONS = [
  "continue_screening",
  "ask_clarifying_question",
  "escalate_to_owner",
  "refuse_and_end",
  "end_spam",
  "block_recommended",
  "report_recommended",
  "human_review",
] as const;
export type RecommendedAction = (typeof RECOMMENDED_ACTIONS)[number];

export const SIGNAL_SEVERITIES = ["info", "low", "medium", "high", "critical"] as const;
export type SignalSeverity = (typeof SIGNAL_SEVERITIES)[number];

export const SIGNAL_KINDS = ["risk", "legitimate"] as const;
export type SignalKind = (typeof SIGNAL_KINDS)[number];

export const SIGNAL_CODES = [
  "OTP_REQUEST",
  "PASSWORD_REQUEST",
  "PIN_REQUEST",
  "CVV_REQUEST",
  "CARD_OR_ACCOUNT_CREDENTIAL_REQUEST",
  "AUTH_OR_RECOVERY_CODE_REQUEST",
  "IDENTITY_DOCUMENT_REQUEST",
  "ADDRESS_OR_LOCATION_REQUEST",
  "OWNER_AVAILABILITY_PROBE",
  "REMOTE_ACCESS_REQUEST",
  "SCREEN_SHARING_REQUEST",
  "PAYMENT_OR_TRANSFER_REQUEST",
  "GIFT_CARD_OR_CRYPTO_REQUEST",
  "MALICIOUS_LINK_OR_CALLBACK",
  "ARREST_OR_LEGAL_THREAT",
  "ACCOUNT_CLOSURE_THREAT",
  "FAKE_KYC_URGENCY",
  "URGENCY_PRESSURE",
  "SUSPICIOUS_PRIZE",
  "IMPERSONATION_BANK",
  "IMPERSONATION_GOVERNMENT",
  "IMPERSONATION_POLICE",
  "IMPERSONATION_COURIER",
  "IMPERSONATION_EMPLOYER",
  "RULE_OVERRIDE_ATTEMPT",
  "FALSE_OWNER_AUTHORIZATION",
  "HARASSMENT_OR_ABUSE",
  "TELEMARKETING",
  "LEGIT_DELIVERY_COORDINATION",
  "LEGIT_APPOINTMENT_CONFIRMATION",
  "LEGIT_RECRUITER_INTRO",
  "LEGIT_KNOWN_SERVICE_CALLBACK",
  "LEGIT_FAMILY_OR_FRIEND",
  "LEGIT_SCHOOL_OR_HOSPITAL",
  "LEGIT_EMERGENCY_CONTEXT",
  "LEGIT_SUPPORT_CALLBACK",
] as const;
export type SignalCode = (typeof SIGNAL_CODES)[number];

export const CALL_CATEGORIES = [
  "unknown",
  "silent",
  "possible_financial_impersonation",
  "possible_government_impersonation",
  "possible_courier_impersonation",
  "possible_tech_support_scam",
  "possible_prize_scam",
  "possible_employer_impersonation",
  "prompt_injection_attempt",
  "telemarketing",
  "harassment",
  "legitimate_delivery",
  "legitimate_appointment",
  "legitimate_recruiter",
  "legitimate_support_callback",
  "legitimate_personal",
  "legitimate_urgent",
] as const;
export type CallCategory = (typeof CALL_CATEGORIES)[number];

export const SPEAKERS = ["caller", "assistant", "owner", "system"] as const;
export type Speaker = (typeof SPEAKERS)[number];

export const TURN_SOURCES = [
  "typed",
  "browser_stt",
  "provider_stt",
  "uploaded_audio",
  "scripted",
  "assistant",
  "system",
] as const;
export type TurnSource = (typeof TURN_SOURCES)[number];

export const PROVIDER_KINDS = ["simulator", "azure", "android_screening", "asterisk", "other"] as const;
export type ProviderKind = (typeof PROVIDER_KINDS)[number];

export const CALL_MODES = ["conversational", "screening_only"] as const;
export type CallMode = (typeof CALL_MODES)[number];

export const OWNER_ACTION_TYPES = ["takeover", "continue", "end", "block", "trust", "unblock", "untrust"] as const;
export type OwnerActionType = (typeof OWNER_ACTION_TYPES)[number];

export const ESCALATION_STATUSES = ["requested", "taken_over", "continued", "ended", "expired"] as const;
export type EscalationStatus = (typeof ESCALATION_STATUSES)[number];

export const FEEDBACK_KINDS = [
  "correct_classification",
  "was_spam",
  "was_legitimate",
  "wrong_language",
  "poor_transcription",
  "wrong_summary",
  "trust_caller",
  "block_caller",
] as const;
export type FeedbackKind = (typeof FEEDBACK_KINDS)[number];

export const SCREENING_STRICTNESS = ["relaxed", "balanced", "strict"] as const;
export type ScreeningStrictness = (typeof SCREENING_STRICTNESS)[number];

export const RESPONSE_STYLES = ["concise", "warm", "formal"] as const;
export type ResponseStyle = (typeof RESPONSE_STYLES)[number];

export const VOICE_STATUSES = [
  "not_enrolled",
  "consent_recorded",
  "pending_provider_approval",
  "ready",
  "failed",
  "deleted",
] as const;
export type VoiceStatus = (typeof VOICE_STATUSES)[number];

export const LIVE_EVENT_TYPES = [
  "call.snapshot",
  "call.created",
  "call.connected",
  "call.listening",
  "state.changed",
  "transcript.partial",
  "transcript.final",
  "language.changed",
  "risk.updated",
  "assistant.speaking",
  "assistant.finished",
  "assistant.interrupted",
  "escalation.requested",
  "owner.takeover",
  "owner.action",
  "call.ended",
  "summary.created",
  "provider.error",
  "stream.resync",
] as const;
export type LiveEventType = (typeof LIVE_EVENT_TYPES)[number];

export const NETWORK_PROFILES = ["ideal", "mobile_4g", "congested"] as const;
export type NetworkProfile = (typeof NETWORK_PROFILES)[number];

export const TRUSTED_CONTACT_BEHAVIORS = ["allow_directly", "screen_anyway"] as const;
export type TrustedContactBehavior = (typeof TRUSTED_CONTACT_BEHAVIORS)[number];

export const UNKNOWN_CALLER_BEHAVIORS = ["screen", "silence", "allow"] as const;
export type UnknownCallerBehavior = (typeof UNKNOWN_CALLER_BEHAVIORS)[number];

export const TURN_SOURCES_FOR_REQUEST = ["typed", "browser_stt", "scripted"] as const;
export type RequestTurnSource = (typeof TURN_SOURCES_FOR_REQUEST)[number];
