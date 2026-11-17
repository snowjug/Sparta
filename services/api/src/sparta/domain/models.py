"""Pydantic domain models. These double as API response schemas, so field names are a public contract."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from sparta.domain.enums import (
    CallCategory,
    CallMode,
    CallState,
    CallStatus,
    EscalationStatus,
    FeedbackKind,
    OwnerActionType,
    ProviderKind,
    RecommendedAction,
    ResponseStyle,
    RiskLevel,
    ScreeningStrictness,
    SignalCode,
    SignalKind,
    SignalSeverity,
    Speaker,
    TurnSource,
    VoiceStatus,
)

Score = Annotated[float, Field(ge=0.0, le=1.0)]
ScriptCode = Literal["Latn", "Deva", "Knda", "Mixed", "Other"]
LanguageVariant = Literal["hinglish", "kanglish"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class SpartaModel(BaseModel):
    """Base for response/domain models: tolerant of additive fields so clients can evolve."""

    model_config = ConfigDict(populate_by_name=True)


class StrictInputModel(BaseModel):
    """Base for request bodies: unknown fields are rejected at the API boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------------------
# Call content
# --------------------------------------------------------------------------------------


class LatencyBreakdown(SpartaModel):
    """Per-stage timings in milliseconds for one caller turn → assistant response.

    ``simulated_stages`` lists stages whose value came from a simulated provider profile rather than a measurement.
    """

    audio_input_ms: float | None = None
    vad_ms: float | None = None
    stt_ms: float | None = None
    language_detect_ms: float | None = None
    policy_ms: float | None = None
    model_ms: float | None = None
    tts_first_audio_ms: float | None = None
    playback_start_ms: float | None = None
    interruption_ms: float | None = None
    total_ms: float | None = None
    simulated_stages: list[str] = Field(default_factory=list)


class LanguageSegment(SpartaModel):
    language: str = Field(description="BCP-47 tag such as en-IN, hi-IN, kn-IN, or 'und'")
    script: ScriptCode
    romanized: bool = False
    start: int = Field(ge=0, description="Character offset (inclusive) in the turn text")
    end: int = Field(ge=0, description="Character offset (exclusive) in the turn text")
    confidence: Score
    variant: LanguageVariant | None = None


class SpeechPlan(SpartaModel):
    """What the assistant will say. ``text`` is in the script the speech provider needs."""

    text: str
    locale: str
    voice_id: str | None = None
    rate: float = 1.0
    style: str | None = None
    ssml: str | None = None
    transliteration: str | None = Field(
        default=None,
        description="Latin-script rendering for developers/testers when text is in a native script",
    )
    est_duration_ms: int = 0


class CallerClaim(SpartaModel):
    name: str | None = None
    organization: str | None = None
    role: str | None = None


class RiskSignal(SpartaModel):
    code: SignalCode
    kind: SignalKind = SignalKind.RISK
    severity: SignalSeverity
    weight: Score = 0.0
    evidence_turn_ids: list[str] = Field(default_factory=list)
    evidence_excerpt: str | None = Field(default=None, max_length=160)
    description: str = ""


class RiskAssessment(SpartaModel):
    call_id: str
    detected_languages: list[str] = Field(default_factory=list)
    language_profile: str | None = Field(default=None, description="e.g. 'english', 'hinglish', 'kanglish'")
    caller_claim: CallerClaim = Field(default_factory=CallerClaim)
    purpose: str | None = None
    category: CallCategory = CallCategory.UNKNOWN
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    risk_score: Score = 0.0
    confidence: Score = 0.0
    signals: list[RiskSignal] = Field(default_factory=list)
    recommended_action: RecommendedAction = RecommendedAction.CONTINUE_SCREENING
    additional_actions: list[RecommendedAction] = Field(
        default_factory=list,
        description="Extra advice alongside the primary action, e.g. block/report recommended",
    )
    requires_owner_attention: bool = False
    reasons: list[str] = Field(
        default_factory=list, description="Short evidence-based reasons. Never contains model reasoning."
    )
    policy_version: str = ""
    assessed_at: datetime = Field(default_factory=utcnow)
    turn_count: int = 0


class CallTurn(SpartaModel):
    id: str = Field(description="Stable per-call turn id, e.g. 'turn_7'")
    call_id: str
    seq: int
    speaker: Speaker
    text: str
    transliteration: str | None = None
    translation: str | None = None
    language: str | None = None
    language_confidence: Score | None = None
    language_profile: str | None = None
    segments: list[LanguageSegment] = Field(default_factory=list)
    is_final: bool = True
    confidence: Score | None = None
    source: TurnSource = TurnSource.TYPED
    interrupted: bool = False
    spoken_fraction: Score | None = None
    state_after: CallState | None = None
    created_at: datetime = Field(default_factory=utcnow)
    latency: LatencyBreakdown | None = None
    speech: SpeechPlan | None = None


class Escalation(SpartaModel):
    id: str
    call_id: str
    reason: str
    status: EscalationStatus = EscalationStatus.REQUESTED
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    important_lines: list[str] = Field(default_factory=list)


class OwnerAction(SpartaModel):
    id: str
    call_id: str
    action: OwnerActionType
    created_at: datetime = Field(default_factory=utcnow)
    simulated: bool = False
    result: str = "ok"
    detail: str | None = None


class CallSummary(SpartaModel):
    call_id: str
    text: str = Field(description="One-sentence factual summary")
    category: CallCategory = CallCategory.UNKNOWN
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    action_taken: str | None = None
    owner_action_required: bool = False
    generated_by: str = "rules-v1"
    created_at: datetime = Field(default_factory=utcnow)


class FeedbackRecord(SpartaModel):
    id: str
    call_id: str
    kind: FeedbackKind
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ProviderEventRecord(SpartaModel):
    """Sanitized view of an inbound/outbound provider event (no payload bodies, no secrets)."""

    id: str
    provider: str
    event_type: str
    external_id: str | None = None
    received_at: datetime = Field(default_factory=utcnow)
    detail: str | None = None


class TimelineEntry(SpartaModel):
    at: datetime
    kind: Literal["state", "owner_action", "escalation", "risk", "language", "provider", "system"]
    label: str
    detail: str | None = None


class VersionInfo(SpartaModel):
    app_version: str = ""
    policy_version: str = ""
    language_pack_version: str = ""
    telephony_provider: str = ""
    stt_provider: str = ""
    tts_provider: str = ""
    llm_provider: str = ""
    llm_model: str | None = None


class CallListItem(SpartaModel):
    id: str
    provider: ProviderKind
    mode: CallMode = CallMode.CONVERSATIONAL
    simulated: bool
    status: CallStatus
    state: CallState
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    caller_display: str = Field(description="Masked number or label; never the raw number unless the owner opted in")
    caller_claim: CallerClaim = Field(default_factory=CallerClaim)
    purpose: str | None = None
    category: CallCategory = CallCategory.UNKNOWN
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    risk_score: Score = 0.0
    confidence: Score = 0.0
    languages: list[str] = Field(default_factory=list)
    language_profile: str | None = None
    summary_text: str | None = None
    action_taken: str | None = None
    owner_attention_required: bool = False
    blocked: bool = False
    trusted: bool = False
    has_content: bool = True


class CallCapabilities(SpartaModel):
    """Which owner controls are honest/available for this call's provider. Unsupported controls carry a reason."""

    can_take_over: bool = False
    can_continue: bool = False
    can_end: bool = False
    can_block: bool = True
    takeover_note: str | None = None
    simulated: bool = False
    two_way_audio: bool = False
    audio_note: str | None = None


class CallDetail(CallListItem):
    language_mode: str = "auto"
    assistant_speaking: bool = Field(
        default=False, description="The assistant is mid-utterance right now (see `speaking_turn_id`)."
    )
    speaking_turn_id: str | None = Field(
        default=None, description="Turn being spoken while `assistant_speaking`; its `speech.est_duration_ms` is known."
    )
    turns: list[CallTurn] = Field(default_factory=list)
    risk: RiskAssessment | None = None
    escalations: list[Escalation] = Field(default_factory=list)
    owner_actions: list[OwnerAction] = Field(default_factory=list)
    summary: CallSummary | None = None
    feedback: list[FeedbackRecord] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    provider_events: list[ProviderEventRecord] = Field(default_factory=list)
    versions: VersionInfo = Field(default_factory=VersionInfo)
    trace_id: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    capabilities: CallCapabilities = Field(default_factory=CallCapabilities)


class ConversationContext(SpartaModel):
    """Persisted snapshot of the call state machine (rebuildable from immutable turns/events)."""

    state: CallState = CallState.INITIALIZING
    language: str = "en-IN"
    language_mode: str = "auto"
    detected_languages: list[str] = Field(default_factory=list)
    language_profile: str | None = None
    caller_claim: CallerClaim = Field(default_factory=CallerClaim)
    purpose: str | None = None
    seq: int = 0
    caller_turns: int = 0
    clarify_attempts: dict[str, int] = Field(default_factory=dict)
    silence_count: int = 0
    refusals: int = 0
    low_confidence_streak: int = 0
    escalation_id: str | None = None
    escalated_at: datetime | None = None
    escalation_closed: bool = Field(
        default=False, description="The owner decided (or the owner window expired): never alert them again"
    )
    owner_decision: OwnerActionType | None = None
    risk: RiskAssessment | None = None
    signals: list[RiskSignal] = Field(default_factory=list)
    action_taken: str | None = None
    ended_reason: str | None = None
    assistant_speaking: bool = False
    speaking_turn_id: str | None = None
    turn_languages: list[str] = Field(default_factory=list, description="Dominant language of each caller turn")
    safe_turns: int = 0
    last_caller_turn_id: str | None = None


# --------------------------------------------------------------------------------------
# Preferences and assistant configuration
# --------------------------------------------------------------------------------------


class RetentionPolicy(StrictInputModel):
    """Privacy defaults: minimal retention, no raw audio."""

    store_transcripts: bool = True
    transcript_retention_days: int = Field(default=7, ge=0, le=365)
    summary_retention_days: int = Field(default=90, ge=1, le=730)
    store_raw_audio: bool = False
    store_full_caller_number: bool = False


class EscalationRules(StrictInputModel):
    escalate_categories: list[CallCategory] = Field(
        default_factory=lambda: [
            CallCategory.LEGITIMATE_DELIVERY,
            CallCategory.LEGITIMATE_URGENT,
            CallCategory.LEGITIMATE_RECRUITER,
            CallCategory.LEGITIMATE_SUPPORT_CALLBACK,
            CallCategory.LEGITIMATE_PERSONAL,
            CallCategory.LEGITIMATE_APPOINTMENT,
        ]
    )
    escalate_uncertain_urgent: bool = True
    auto_end_high_risk: bool = True
    owner_response_timeout_s: int = Field(default=30, ge=5, le=180)


class NotificationPreferences(StrictInputModel):
    notify_on_escalation: bool = True
    notify_on_high_risk: bool = False
    include_transcript_lines: bool = True
    quiet_hours_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_hours_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class UserPreferences(StrictInputModel):
    onboarding_completed: bool = False
    primary_language: str = "en-IN"
    enabled_languages: list[str] = Field(default_factory=lambda: ["en-IN", "hi-IN", "kn-IN"])
    auto_detect_language: bool = True
    translate_transcripts_to: str | None = "en-IN"
    strictness: ScreeningStrictness = ScreeningStrictness.BALANCED
    trusted_contact_behavior: Literal["allow_directly", "screen_anyway"] = "allow_directly"
    unknown_caller_behavior: Literal["screen", "silence", "allow"] = "screen"
    silence_first_timeout_s: int = Field(default=8, ge=3, le=30)
    silence_second_timeout_s: int = Field(default=8, ge=3, le=30)
    max_call_duration_s: int = Field(default=180, ge=30, le=900)
    takeover_number: str | None = Field(
        default=None,
        pattern=r"^\+?[0-9 ()\-]{7,20}$",
        description="Where a real provider bridges the call when you tap Take Over (never used by the simulator)",
    )
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)
    escalation: EscalationRules = Field(default_factory=EscalationRules)
    notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)


class AssistantProfile(StrictInputModel):
    """How the assistant presents itself. The AI disclosure is not configurable away."""

    owner_display_name: str = Field(default="the owner", min_length=1, max_length=60)
    response_style: ResponseStyle = ResponseStyle.CONCISE
    speaking_rate: float = Field(default=1.0, ge=0.7, le=1.3)
    voice_ids: dict[str, str] = Field(
        default_factory=dict, description="locale → predefined voice id; empty uses the catalog default"
    )
    use_personal_voice: bool = False


class VoiceOption(SpartaModel):
    id: str
    locale: str
    display_name: str
    gender: Literal["female", "male", "neutral"]
    provider: str
    verified: bool = Field(description="True only if the voice name was verified in provider documentation")
    note: str | None = None


class VoiceProfileView(SpartaModel):
    status: VoiceStatus = VoiceStatus.NOT_ENROLLED
    consent_recorded_at: datetime | None = None
    consent_version: str | None = None
    provider_voice_id: str | None = None
    active: bool = False
    detail: str = "No personal voice enrolled. A predefined natural voice is used."
    requires_provider_approval: bool = True


class TrustedCaller(SpartaModel):
    id: str
    number_display: str
    label: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    source_call_id: str | None = None


class BlockedCaller(SpartaModel):
    id: str
    number_display: str
    reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    source_call_id: str | None = None


# --------------------------------------------------------------------------------------
# Live events
# --------------------------------------------------------------------------------------


class LiveEvent(SpartaModel):
    """Envelope for every WebSocket message. ``seq`` is monotonic per call."""

    type: str
    call_id: str
    seq: int = 0
    ts: datetime = Field(default_factory=utcnow)
    simulated: bool = False
    data: dict[str, object] = Field(default_factory=dict)
