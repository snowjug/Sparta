"""Service-level request/response models (shared by the HTTP layer and the services)."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from sparta.domain.enums import CallState, TurnSource
from sparta.domain.models import (
    CallCapabilities,
    CallListItem,
    CallTurn,
    Escalation,
    OwnerAction,
    RiskAssessment,
    SpartaModel,
    StrictInputModel,
)

NetworkProfile = Literal["ideal", "mobile_4g", "congested"]
SilenceTimers = Literal["preferences", "off"]


@dataclass(frozen=True)
class Principal:
    """The authenticated owner. ``id`` is the isolation boundary for every query."""

    id: str
    display_name: str = ""


class CreateCallRequest(StrictInputModel):
    caller_number: str | None = Field(default=None, max_length=32)
    caller_label: str | None = Field(default=None, max_length=80)
    language_mode: str = Field(default="auto", max_length=16)
    network_profile: NetworkProfile = "ideal"
    scenario_id: str | None = Field(default=None, max_length=64)
    autoplay: bool = False
    silence_timers: SilenceTimers = "preferences"


class TurnRequest(StrictInputModel):
    text: str = Field(min_length=1, max_length=1000)
    source: Literal["typed", "browser_stt", "scripted"] = "typed"
    language_hint: str | None = Field(default=None, max_length=16)
    stt_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    client_turn_id: str | None = Field(default=None, max_length=64)

    def turn_source(self) -> TurnSource:
        return TurnSource(self.source)


class PartialRequest(StrictInputModel):
    text: str = Field(min_length=1, max_length=1000)
    language_hint: str | None = Field(default=None, max_length=16)


class InterruptRequest(StrictInputModel):
    turn_id: str | None = Field(default=None, max_length=24)
    spoken_fraction: float | None = Field(default=None, ge=0.0, le=1.0)


class BlockRequest(StrictInputModel):
    reason: str | None = Field(default=None, max_length=200)


class TrustRequest(StrictInputModel):
    label: str | None = Field(default=None, max_length=80)


class TurnResult(SpartaModel):
    caller_turn: CallTurn | None
    assistant_turn: CallTurn | None
    call: CallListItem
    risk: RiskAssessment | None
    state: CallState
    ended: bool
    escalation: Escalation | None = None
    interrupted_turn_id: str | None = None


class OwnerActionResult(SpartaModel):
    action: OwnerAction
    call: CallListItem
    capabilities: CallCapabilities


class InterruptResult(SpartaModel):
    interrupted: bool
    turn_id: str | None = None
    interruption_ms: float | None = None
    spoken_fraction: float | None = None
