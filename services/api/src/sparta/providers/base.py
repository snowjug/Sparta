"""Provider ports: the interfaces every speech, voice-activity and conversation-model provider implements.

Real providers (Azure Speech, Azure OpenAI) and the built-in simulators satisfy the *same* protocols, so the call
pipeline never knows which one it is talking to. Every provider reports ``meta.simulated`` so the UI can label it
honestly, and every failure is a :class:`ProviderError` with a sanitised message (no response bodies, no secrets).
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from sparta.domain.enums import SignalCode
from sparta.domain.models import CallSummary, RiskAssessment, SpeechPlan, VoiceOption

# --------------------------------------------------------------------------------------------------- errors


class ProviderError(Exception):
    """A sanitised provider failure. ``message`` is safe to log and to show to the owner."""

    def __init__(
        self,
        provider: str,
        stage: str,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(f"{provider}/{stage}: {message}")
        self.provider = provider
        self.stage = stage
        self.message = message
        self.retryable = retryable
        self.status = status
        self.retry_after_s = retry_after_s


class ProviderTimeout(ProviderError):
    def __init__(self, provider: str, stage: str, timeout_s: float) -> None:
        super().__init__(provider, stage, f"timed out after {timeout_s:g}s", retryable=True)


class ProviderUnavailable(ProviderError):
    """Not configured, or the circuit breaker is open."""

    def __init__(self, provider: str, stage: str, message: str = "provider unavailable") -> None:
        super().__init__(provider, stage, message, retryable=False)


class ProviderRejected(ProviderError):
    """The provider refused the request (bad audio, unsupported locale, content filter). Not retryable."""

    def __init__(self, provider: str, stage: str, message: str, status: int | None = None) -> None:
        super().__init__(provider, stage, message, retryable=False, status=status)


# ------------------------------------------------------------------------------------------ shared types


@dataclass(frozen=True)
class ProviderMeta:
    provider: str  # e.g. "simulator", "azure-speech", "azure-openai"
    simulated: bool
    model: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class Usage:
    """What a call to a provider consumed, for cost and usage observability."""

    audio_seconds: float = 0.0
    characters: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 1


# -------------------------------------------------------------------------------------------------- STT


@dataclass
class TranscriptEvent:
    kind: Literal["partial", "final"]
    text: str
    language: str | None = None  # detected BCP-47 tag
    confidence: float | None = None
    offset_ms: int = 0
    duration_ms: int = 0


@dataclass
class TranscriptResult:
    text: str
    language: str | None
    confidence: float | None
    segments: list[TranscriptEvent] = field(default_factory=list)
    audio_seconds: float = 0.0
    usage: Usage = field(default_factory=Usage)
    simulated: bool = False


@runtime_checkable
class SttStream(Protocol):
    """One live recognition session. ``push_audio`` feeds PCM; ``events`` yields partial then final transcripts."""

    async def push_audio(self, chunk: bytes) -> None: ...

    def events(self) -> AsyncIterator[TranscriptEvent]: ...

    async def stop_stream(self) -> None: ...


@runtime_checkable
class SpeechToTextProvider(Protocol):
    meta: ProviderMeta

    async def start_stream(
        self, *, candidate_locales: Sequence[str], locale_hint: str | None, trace_id: str, sample_rate: int = 16000
    ) -> SttStream: ...

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        candidate_locales: Sequence[str],
        locale_hint: str | None,
        trace_id: str,
        transcript_hint: str | None = None,
    ) -> TranscriptResult:
        """One-shot transcription of an uploaded clip. The simulator can only echo ``transcript_hint``."""
        ...


# -------------------------------------------------------------------------------------------------- TTS


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    locale: str
    voice_id: str | None
    rate: float = 1.0
    style: str | None = None
    output_format: Literal["pcm16_8k", "pcm16_16k", "pcm16_24k", "mulaw_8k", "alaw_8k"] = "pcm16_16k"
    trace_id: str = ""


@dataclass
class AudioChunk:
    data: bytes
    sample_rate: int
    encoding: str
    seq: int
    final: bool = False


@runtime_checkable
class TextToSpeechProvider(Protocol):
    meta: ProviderMeta

    def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        """Yield audio as it becomes available. The simulator yields timing-only chunks with empty ``data``."""
        ...

    async def stop_playback(self, playback_id: str) -> None: ...

    async def list_voices(self, locale: str | None = None) -> list[VoiceOption]: ...


# ----------------------------------------------------------------------------------- conversation model


@dataclass
class TurnEvaluationRequest:
    """Everything a model may see about one caller turn. The text is UNTRUSTED data, never instructions."""

    call_id: str
    caller_text: str
    language: str | None
    recent_turns: list[tuple[str, str]]  # (speaker, text), oldest first, already length-bounded
    known_signals: list[SignalCode]
    trace_id: str


@dataclass
class TurnAnalysis:
    """Advisory output. The deterministic engine may only *raise* risk with it, never lower it."""

    extra_signals: list[SignalCode] = field(default_factory=list)
    claimed_name: str | None = None
    claimed_organization: str | None = None
    purpose: str | None = None
    intent: str | None = None
    notes: str = ""
    usage: Usage = field(default_factory=Usage)
    simulated: bool = False


@dataclass
class ReplyRequest:
    call_id: str
    state: str
    language: str
    owner_display_name: str | None
    recent_turns: list[tuple[str, str]]
    trace_id: str


@dataclass
class ReplySuggestion:
    text: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class SummaryRequest:
    call_id: str
    rules_summary: str
    turns: list[tuple[str, str]]
    risk: RiskAssessment | None
    trace_id: str


@dataclass
class SummaryResult:
    text: str
    usage: Usage = field(default_factory=Usage)
    simulated: bool = False


@dataclass
class TranslationResult:
    text: str
    source_language: str
    target_language: str
    usage: Usage = field(default_factory=Usage)
    simulated: bool = False


@runtime_checkable
class ConversationModelProvider(Protocol):
    meta: ProviderMeta

    async def evaluate_turn(self, request: TurnEvaluationRequest) -> TurnAnalysis: ...

    async def generate_safe_reply(self, request: ReplyRequest) -> ReplySuggestion | None:
        """Optional suggestion for non-critical states. Replies in V1 come from templates; this is for providers
        that can phrase them. Anything returned still has to pass the output validator."""
        ...

    async def summarize_call(self, request: SummaryRequest) -> SummaryResult: ...

    async def classify_call(self, request: SummaryRequest) -> RiskAssessment | None: ...

    async def translate(
        self, text: str, source_language: str, target_language: str, trace_id: str
    ) -> TranslationResult | None:
        """``None`` means this provider cannot translate (the rules provider has no machine translation)."""
        ...


# -------------------------------------------------------------------------------------------------- VAD


@dataclass(frozen=True)
class VadEvent:
    kind: Literal["speech_started", "speech_ended", "silence_timeout"]
    at_ms: int


@runtime_checkable
class VoiceActivityProvider(Protocol):
    """Stateful detector fed PCM16 mono frames; returns events as soon as they are decidable."""

    def process(self, pcm16: bytes, sample_rate: int) -> list[VadEvent]: ...

    def reset(self) -> None: ...


__all__ = [
    "AudioChunk",
    "CallSummary",
    "ConversationModelProvider",
    "ProviderError",
    "ProviderMeta",
    "ProviderRejected",
    "ProviderTimeout",
    "ProviderUnavailable",
    "ReplyRequest",
    "ReplySuggestion",
    "SpeechPlan",
    "SpeechToTextProvider",
    "SttStream",
    "SummaryRequest",
    "SummaryResult",
    "SynthesisRequest",
    "TextToSpeechProvider",
    "TranscriptEvent",
    "TranscriptResult",
    "TranslationResult",
    "TurnAnalysis",
    "TurnEvaluationRequest",
    "Usage",
    "VadEvent",
    "VoiceActivityProvider",
]
