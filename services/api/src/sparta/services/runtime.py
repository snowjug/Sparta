"""Per-call runtime state (timers, playback, locks), config snapshots and simulated network profiles."""

import asyncio
import hashlib
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from sparta.domain.enums import CallState, EventType, ResponseStyle, ScreeningStrictness
from sparta.domain.models import EscalationRules, LiveEvent
from sparta.orchestrator.engine import EngineConfig
from sparta.telephony.base import ProviderCallRef, TelephonyProvider

if TYPE_CHECKING:
    from sparta.clock import Clock
    from sparta.db.repository import Repository


@dataclass(frozen=True)
class NetworkLatency:
    """Simulated per-stage latency (ms). ``ideal`` adds nothing and reports nothing as simulated."""

    stt_ms: float = 0.0
    tts_first_audio_ms: float = 0.0
    playback_start_ms: float = 0.0


NETWORK_PROFILES: dict[str, NetworkLatency] = {
    "ideal": NetworkLatency(),
    "mobile_4g": NetworkLatency(stt_ms=280, tts_first_audio_ms=240, playback_start_ms=120),
    "congested": NetworkLatency(stt_ms=900, tts_first_audio_ms=800, playback_start_ms=450),
}


def jitter(value: float, call_id: str, seq: int, stage: str) -> float:
    """Deterministic ±10% variation so simulated latency looks real but replays identically."""
    if value <= 0:
        return 0.0
    digest = hashlib.sha256(f"{call_id}:{seq}:{stage}".encode()).digest()
    return round(value * (0.9 + (digest[0] / 255.0) * 0.2), 1)


@dataclass
class RuntimeParams:
    silence_timers: bool = True
    silence_first_s: float = 8.0
    silence_second_s: float = 8.0
    owner_timeout_s: float = 30.0
    max_duration_s: float = 180.0
    network_profile: str = "ideal"


def config_to_json(cfg: EngineConfig, params: RuntimeParams) -> dict[str, Any]:
    return {
        "engine": {
            "owner_name": cfg.owner_name,
            "response_style": cfg.response_style.value,
            "speaking_rate": cfg.speaking_rate,
            "voice_ids": dict(cfg.voice_ids),
            "primary_language": cfg.primary_language,
            "enabled_languages": list(cfg.enabled_languages),
            "language_mode": cfg.language_mode,
            "auto_detect_language": cfg.auto_detect_language,
            "strictness": cfg.strictness.value,
            "escalation": cfg.escalation.model_dump(mode="json"),
            "owner_private_markers": list(cfg.owner_private_markers),
        },
        "runtime": asdict(params),
    }


def config_from_json(call_id: str, data: dict[str, Any]) -> tuple[EngineConfig, RuntimeParams]:
    e = data["engine"]
    cfg = EngineConfig(
        call_id=call_id,
        owner_name=e.get("owner_name"),
        response_style=ResponseStyle(e.get("response_style", "concise")),
        speaking_rate=float(e.get("speaking_rate", 1.0)),
        voice_ids=dict(e.get("voice_ids", {})),
        primary_language=e.get("primary_language", "en-IN"),
        enabled_languages=tuple(e.get("enabled_languages", ("en-IN", "hi-IN", "kn-IN"))),
        language_mode=e.get("language_mode", "auto"),
        auto_detect_language=bool(e.get("auto_detect_language", True)),
        strictness=ScreeningStrictness(e.get("strictness", "balanced")),
        escalation=EscalationRules.model_validate(e.get("escalation", {})),
        owner_private_markers=tuple(e.get("owner_private_markers", ())),
    )
    return cfg, RuntimeParams(**data.get("runtime", {}))


class CallRuntime:
    """Mutable, in-memory companion of one active call. Durable state lives in the database."""

    def __init__(
        self,
        call_id: str,
        user_id: str,
        cfg: EngineConfig,
        params: RuntimeParams,
        provider: TelephonyProvider,
        provider_call_id: str | None,
        simulated: bool,
        now: float,
    ) -> None:
        self.call_id = call_id
        self.user_id = user_id
        self.cfg = cfg
        self.params = params
        self.provider = provider
        self.ref = ProviderCallRef(call_id=call_id, provider_call_id=provider_call_id)
        self.simulated = simulated
        self.lock = asyncio.Lock()
        self.playback_id: str | None = None
        self.speaking_turn_id: str | None = None
        self.speaking_started = 0.0
        self.speaking_est_ms = 0
        self.speaking_until = 0.0
        self.silence_task: asyncio.Task[None] | None = None
        self.owner_task: asyncio.Task[None] | None = None
        self.limit_task: asyncio.Task[None] | None = None
        self.pending_finalize = False
        self.silence_count = 0
        self.state = CallState.INITIALIZING
        self.last_activity = now
        self.pipeline: Any = None

    def cancel_timers(self) -> None:
        for task in (self.silence_task, self.owner_task, self.limit_task):
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
        self.silence_task = self.owner_task = self.limit_task = None


@dataclass
class EventBuffer:
    """Collects the live events of one transaction so they are published only after it commits."""

    repo: "Repository"
    clock: "Clock"
    call_id: str
    simulated: bool
    items: list[LiveEvent] = field(default_factory=list)

    async def emit(self, type_: EventType | str, data: dict[str, Any] | None = None) -> LiveEvent:
        seq = await self.repo.next_event_seq(self.call_id)
        event = LiveEvent(
            type=type_.value if isinstance(type_, EventType) else type_,
            call_id=self.call_id,
            seq=seq,
            ts=self.clock.now(),
            simulated=self.simulated,
            data=data or {},
        )
        await self.repo.add_live_event(event)
        self.items.append(event)
        return event
