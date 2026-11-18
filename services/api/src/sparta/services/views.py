"""Response models for owner-facing aggregate endpoints (home, system status, safety center, screening)."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from sparta.domain.enums import (
    CallCategory,
    RecommendedAction,
    RiskLevel,
    ScreeningStrictness,
    SignalKind,
    SignalSeverity,
)
from sparta.domain.models import (
    CallDetail,
    CallListItem,
    LiveEvent,
    RiskAssessment,
    SpartaModel,
    SpeechPlan,
    StrictInputModel,
)

# ----------------------------------------------------------------------------------------------------- system


class TelephonyView(SpartaModel):
    provider: Literal["simulator", "azure", "other"]
    simulated: bool
    live_calls_supported: bool
    forwarding_number: str | None = None
    note: str = ""


class LanguageView(SpartaModel):
    code: str
    name: str
    native_name: str
    status: Literal["supported", "planned"]


class FeaturesView(SpartaModel):
    simulator: bool
    personal_voice: bool
    llm_summaries: bool
    translation: bool
    raw_audio_storage: Literal[False] = False


class LimitsView(SpartaModel):
    max_call_duration_s: int
    max_audio_bytes: int
    max_audio_seconds: int
    daily_call_cap: int


class SystemStatus(SpartaModel):
    version: str
    env: str
    auth_mode: Literal["dev", "oidc"]
    dev_banner: bool
    telephony: TelephonyView
    stt_provider: str
    tts_provider: str
    llm_provider: str
    llm_model: str | None = None
    features: FeaturesView
    policy_version: str
    language_pack_version: str
    languages: list[LanguageView]
    limits: LimitsView


class MeView(SpartaModel):
    id: str
    display_name: str
    auth_mode: Literal["dev", "oidc"]


# -------------------------------------------------------------------------------------------------------- home


class ProtectionView(SpartaModel):
    status: Literal["active", "attention", "degraded", "setup_needed"]
    headline: str
    detail: str
    provider: str
    simulated: bool
    live_calls_supported: bool


class TodayView(SpartaModel):
    handled: int = 0
    high_risk: int = 0
    escalations: int = 0
    ended_spam: int = 0
    minutes_handled: float = 0.0


class NextAction(SpartaModel):
    kind: Literal["finish_onboarding", "review_escalation", "review_call", "run_simulator", "none"]
    label: str
    route: str


class HomeSummary(SpartaModel):
    protection: ProtectionView
    today: TodayView
    next_action: NextAction
    attention: list[CallListItem] = Field(default_factory=list)
    recent: list[CallListItem] = Field(default_factory=list)


# -------------------------------------------------------------------------------------------- assistant studio


class PreviewRequest(StrictInputModel):
    language: str = Field(default="auto", max_length=16)
    sample_text: str | None = Field(default=None, max_length=400)


class PreviewResult(SpartaModel):
    disclosure: SpeechPlan
    reply: SpeechPlan | None = None
    risk: RiskAssessment | None = None
    detected_language: str | None = None


class VoiceConsentView(SpartaModel):
    version: str
    text: str
    requires_provider_approval: bool = True
    supported_locales: list[str] = Field(default_factory=list)


class VoiceEnrollRequest(StrictInputModel):
    consent: bool
    consent_version: str = Field(min_length=1, max_length=32)
    speaker_name: str = Field(min_length=1, max_length=60)


# ----------------------------------------------------------------------------------------------- safety center


class ProtectedInfoView(SpartaModel):
    code: str
    label: str


class SignalView(SpartaModel):
    code: str
    kind: SignalKind
    severity: SignalSeverity
    description: str
    protected: bool


class PromptInjectionView(SpartaModel):
    summary: str
    examples: list[str]


class SafetyPolicyView(SpartaModel):
    version: str
    name: str
    protected_information: list[ProtectedInfoView]
    signals: list[SignalView]
    strictness: ScreeningStrictness
    thresholds: dict[str, dict[str, float]]
    limits: dict[str, int]
    prompt_injection: PromptInjectionView


class SafetyEventView(SpartaModel):
    call_id: str
    at: datetime
    risk_level: RiskLevel
    category: CallCategory
    action: RecommendedAction | None = None
    signal_codes: list[str] = Field(default_factory=list)


class AuditEntry(SpartaModel):
    at: datetime
    action: str
    target_type: str
    target_id: str | None = None
    detail: dict[str, object] | None = None


class ListNumberRequest(StrictInputModel):
    number: str = Field(min_length=3, max_length=32)
    reason: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=80)


# ---------------------------------------------------------------------------------------------- native screening


class ScreeningConfig(SpartaModel):
    fingerprint_salt: str
    unknown_caller_behavior: Literal["screen", "silence", "allow"]
    trusted_contact_behavior: Literal["allow_directly", "screen_anyway"]
    strictness: ScreeningStrictness
    forwarding_number: str | None = None
    provider: str
    live_calls_supported: bool


class BlockedFingerprint(SpartaModel):
    id: str
    fingerprint: str
    number_display: str


class TrustedFingerprint(SpartaModel):
    id: str
    fingerprint: str
    number_display: str
    label: str | None = None


class ScreeningLists(SpartaModel):
    blocked: list[BlockedFingerprint]
    trusted: list[TrustedFingerprint]


class ScreeningEventRequest(StrictInputModel):
    client_event_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9\-_.]+$")
    number_fingerprint: str = Field(min_length=16, max_length=128, pattern=r"^[0-9a-fA-F]+$")
    number_display: str = Field(default="Private number", max_length=48)
    decision: Literal["allow", "silence", "reject"]
    reason: str = Field(default="", max_length=120)
    verification_status: str | None = Field(default=None, max_length=32)
    direction: Literal["incoming", "outgoing"] | None = None
    occurred_at: datetime


# ---------------------------------------------------------------------------------------------- simulator


class ProviderOption(SpartaModel):
    id: str
    kind: Literal["telephony", "stt", "tts", "llm"]
    active: bool
    available: bool
    simulated: bool
    label: str
    reason: str = ""


class ScenarioTurn(StrictInputModel):
    """One scripted caller step: a spoken turn, or silence (the caller says nothing for ``delay_ms``)."""

    kind: Literal["speech", "silence"] = "speech"
    text: str = Field(default="", max_length=400)
    language: str | None = Field(default=None, max_length=16)
    delay_ms: int = Field(default=800, ge=0, le=15000)
    stt_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    barge_in: bool = Field(default=False, description="Speak over the assistant instead of waiting for it to finish")

    @model_validator(mode="after")
    def _speech_needs_text(self) -> Self:
        if self.kind == "speech" and not self.text.strip():
            raise ValueError("a speech turn needs text")
        return self


class CreateScenarioRequest(StrictInputModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    language_profile: str = Field(default="mixed", max_length=24)
    turns: list[ScenarioTurn] = Field(min_length=1, max_length=14)
    expected_action: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _bounded_total(self) -> Self:
        if sum(len(t.text) for t in self.turns) > 4000:
            raise ValueError("a scenario may contain at most 4000 characters of caller text")
        return self


class ScenarioSummary(SpartaModel):
    id: str
    title: str
    description: str = ""
    language_profile: str
    languages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    turn_count: int
    expected_action: str | None = None
    custom: bool = False


class ScenarioDetail(ScenarioSummary):
    caller_number: str | None = None
    caller_label: str | None = None
    turns: list[ScenarioTurn] = Field(default_factory=list)


class ReplayRequest(StrictInputModel):
    scenario_id: str = Field(min_length=1, max_length=64)
    language_mode: str = Field(default="auto", max_length=16)
    network_profile: Literal["ideal", "mobile_4g", "congested"] = "ideal"


class ReplayResult(SpartaModel):
    call: CallDetail
    events: list[LiveEvent]
    checksum: str
    checksum_covers: str
