"""Telephony port.

A telephony provider delivers calls and audio to Sparta and carries Sparta's speech back. Capabilities are explicit and
honest: the UI shows exactly what the active provider can do, and unsupported owner actions return a clear reason rather
than pretending to work. The simulator is a supported development mode, labelled ``simulated`` everywhere.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from sparta.domain.enums import ProviderKind
from sparta.domain.models import CallCapabilities, SpeechPlan


@dataclass(frozen=True)
class TelephonyCapabilities:
    can_answer: bool
    can_play_audio: bool
    can_stop_playback: bool  # barge-in
    can_transfer: bool  # owner takeover / bridge
    can_hangup: bool
    receives_caller_audio: bool
    two_way_audio: bool
    dtmf: bool
    simulated: bool
    live_calls_supported: bool  # can the product receive *real* calls with this provider right now?
    note: str = ""
    takeover_destination: str | None = None  # a fixed destination the provider rings (a SIP extension), not a number
    takeover_note: str | None = None  # what Take Over really does here, when that is not "bridge your phone number"

    def call_capabilities(self, *, ended: bool = False) -> CallCapabilities:
        """Owner-control availability for one call, with honest explanations."""
        takeover_note = None
        if not self.can_transfer:
            takeover_note = "This provider cannot bridge the call to you."
        elif self.simulated:
            takeover_note = "Takeover is simulated: no real phone call is being bridged."
        elif self.takeover_note:
            takeover_note = self.takeover_note
        audio_note = (
            "Simulated call: no cellular audio is involved."
            if self.simulated
            else (None if self.two_way_audio else "Two-way audio is not connected for this call.")
        )
        takeover_via = (
            "none"
            if not self.can_transfer
            else "simulated"
            if self.simulated
            else "sip_extension"
            if self.takeover_destination
            else "phone_number"
        )
        return CallCapabilities(
            can_take_over=self.can_transfer and not ended,
            can_continue=not ended,
            can_end=self.can_hangup and not ended,
            can_block=True,
            takeover_note=takeover_note,
            takeover_via=takeover_via,
            simulated=self.simulated,
            two_way_audio=self.two_way_audio,
            audio_note=audio_note,
        )


@dataclass(frozen=True)
class ProviderCallRef:
    """Handle the telephony provider and the call service use to talk about one call."""

    call_id: str  # Sparta call id
    provider_call_id: str | None = None  # the provider's id (ACS serverCallId, ...)
    provider_context: str | None = None  # opaque, e.g. ACS incomingCallContext


@dataclass(frozen=True)
class IncomingCall:
    provider: str
    provider_call_id: str
    caller_number: str | None  # raw E.164 when the network provides it; never logged, never returned by the API
    called_number: str | None
    display_name: str | None
    correlation_id: str | None
    received_at: datetime
    context: str | None = None  # opaque provider token needed to answer


@dataclass
class Playback:
    playback_id: str
    call_id: str
    duration_ms: int
    simulated: bool = False


@dataclass
class TransferResult:
    accepted: bool
    simulated: bool
    detail: str = ""


@dataclass
class ProviderStatus:
    provider: str
    kind: ProviderKind
    healthy: bool
    simulated: bool
    detail: str = ""
    extra: dict[str, str] = field(default_factory=dict)


class TelephonyEventSink(Protocol):
    """What the call service exposes to a telephony provider for inbound events (idempotent on provider event ids)."""

    async def incoming_call(self, call: IncomingCall) -> str: ...

    async def caller_audio(self, call_id: str, pcm16: bytes, sample_rate: int) -> None: ...

    async def caller_dtmf(self, call_id: str, digit: str) -> None: ...

    async def playback_finished(self, call_id: str, playback_id: str) -> None: ...

    async def remote_hangup(self, call_id: str, reason: str) -> None: ...

    async def provider_error(self, call_id: str | None, stage: str, message: str) -> None: ...


PlaybackCallback = Callable[[str, str], Awaitable[None]]


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str
    kind: ProviderKind
    capabilities: TelephonyCapabilities

    async def answer(self, call: ProviderCallRef) -> None: ...

    async def play(self, call: ProviderCallRef, plan: SpeechPlan) -> Playback:
        """Speak ``plan`` to the caller. Completion is reported through ``TelephonyEventSink.playback_finished``."""
        ...

    async def stop_playback(self, call: ProviderCallRef, playback_id: str) -> None:
        """Caller barge-in: stop speaking promptly."""
        ...

    async def hangup(self, call: ProviderCallRef, reason: str) -> None: ...

    async def transfer(self, call: ProviderCallRef, destination: str | None) -> TransferResult: ...

    async def status(self) -> ProviderStatus: ...

    def bind(self, sink: TelephonyEventSink) -> None:
        """Called once at startup so the provider can deliver inbound events."""
        ...
