"""Call lifecycle: turns engine decisions into persisted state, live events, telephony actions and timers.

The conversation engine is pure; this service is where side effects happen, in a fixed order per step:
  1) read state under the per-call lock, 2) run the engine, 3) apply simulated network latency (if any),
  4) persist everything in one transaction, 5) publish live events *after* commit, 6) speak / hang up via the
  telephony provider, 7) re-arm timers.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from sparta import __version__
from sparta.clock import Clock
from sparta.config import Settings
from sparta.db import models as m
from sparta.db.crypto import user_salt
from sparta.db.repository import CallFilter, Repository, list_item_from_row
from sparta.db.session import Database
from sparta.domain.enums import (
    CallCategory,
    CallMode,
    CallState,
    CallStatus,
    EscalationStatus,
    EventType,
    FeedbackKind,
    OwnerActionType,
    ProviderKind,
    RecommendedAction,
    RiskLevel,
    SignalKind,
    Speaker,
    TurnSource,
)
from sparta.domain.models import (
    AssistantProfile,
    BlockedCaller,
    CallCapabilities,
    CallDetail,
    CallListItem,
    CallSummary,
    CallTurn,
    ConversationContext,
    FeedbackRecord,
    LatencyBreakdown,
    LiveEvent,
    OwnerAction,
    RiskAssessment,
    SpeechPlan,
    TrustedCaller,
    UserPreferences,
    VersionInfo,
)
from sparta.language.registry import load_registry
from sparta.observability import metrics as mt
from sparta.observability.metrics import Metrics, percentile
from sparta.observability.tracing import UnitCosts, estimate_cost, new_trace_id
from sparta.orchestrator.engine import (
    CallerInput,
    ConversationEngine,
    EngineConfig,
    EngineResult,
    risk_changed,
    sanitize_text,
)
from sparta.orchestrator.summary import build_summary
from sparta.providers.base import (
    ConversationModelProvider,
    ProviderError,
    SpeechToTextProvider,
    SummaryRequest,
    TextToSpeechProvider,
    TurnEvaluationRequest,
)
from sparta.providers.resilience import ResilientCaller
from sparta.services.dto import (
    CreateCallRequest,
    InterruptResult,
    OwnerActionResult,
    Principal,
    TurnResult,
)
from sparta.services.errors import Conflict, InvalidInput, NotFound, RateLimited, UnsupportedByProvider
from sparta.services.ids import IdFactory
from sparta.services.kv import KeyValueStore
from sparta.services.live import LiveHub
from sparta.services.notifier import PushNotification, PushNotifier
from sparta.services.numbers import PRIVATE_DISPLAY, fingerprint, mask_number, normalize_number
from sparta.services.runtime import (
    NETWORK_PROFILES,
    CallRuntime,
    EventBuffer,
    RuntimeParams,
    config_from_json,
    config_to_json,
    jitter,
)
from sparta.services.timeline import build_timeline
from sparta.telephony.base import IncomingCall, Playback, TelephonyProvider

log = logging.getLogger("sparta.calls")
ASSISTANT_PROFILE_DEFAULT_NAME = "the owner"
DEFAULT_SOURCE_LABEL = {"simulator": "Simulated caller"}


def _utc_midnight(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class CallService:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        engine: ConversationEngine,
        clock: Clock,
        ids: IdFactory,
        hub: LiveHub,
        metrics: Metrics,
        kv: KeyValueStore,
        telephony: TelephonyProvider,
        sim_telephony: TelephonyProvider,
        stt: SpeechToTextProvider,
        tts: TextToSpeechProvider,
        llm: ConversationModelProvider,
        notifier: PushNotifier,
        pepper: bytes,
        costs: UnitCosts | None = None,
    ) -> None:
        self.settings, self.db, self.engine, self.clock = settings, db, engine, clock
        self.ids, self.hub, self.metrics, self.kv = ids, hub, metrics, kv
        self.telephony, self.sim_telephony = telephony, sim_telephony
        self.stt, self.tts, self.llm, self.notifier = stt, tts, llm, notifier
        self.pepper = pepper
        self.costs = costs or UnitCosts()
        self._runtimes: dict[str, CallRuntime] = {}
        self._llm_caller = ResilientCaller(
            self.llm.meta.provider,
            "llm",
            timeout_s=min(settings.provider_timeout_s, 4.0),
            max_retries=0,
            clock=clock,
            metrics=metrics,
        )
        self.finalize_hooks: list[Callable[[str], None]] = []
        self._supported = set(load_registry().supported_codes())

    # ================================================================================== lifecycle
    def start(self) -> None:
        self.telephony.bind(self)
        if self.sim_telephony is not self.telephony:
            self.sim_telephony.bind(self)

    async def stop(self) -> None:
        for rt in list(self._runtimes.values()):
            rt.cancel_timers()
        self._runtimes.clear()

    def active_runtime_count(self) -> int:
        return len(self._runtimes)

    # ================================================================================== helpers
    def _provider_by_name(self, name: str) -> TelephonyProvider:
        if name == self.telephony.name:
            return self.telephony
        return self.sim_telephony

    def _versions(self, provider: TelephonyProvider) -> dict[str, Any]:
        return VersionInfo(
            app_version=__version__,
            policy_version=self.engine.policy.version,
            language_pack_version=self.engine.planner.registry.version(),
            telephony_provider=provider.name,
            stt_provider=self.stt.meta.provider,
            tts_provider=self.tts.meta.provider,
            llm_provider=self.llm.meta.provider,
            llm_model=self.llm.meta.model,
        ).model_dump(mode="json")

    async def _publish(self, user_id: str, events: list[LiveEvent]) -> None:
        for event in events:
            try:
                await self.hub.publish(user_id, event)
            except Exception:
                log.exception("live publish failed")

    def _buffer(self, repo: Repository, call_id: str, simulated: bool) -> EventBuffer:
        return EventBuffer(repo=repo, clock=self.clock, call_id=call_id, simulated=simulated)

    @asynccontextmanager
    async def _locked(self, rt: CallRuntime) -> AsyncIterator[None]:
        async with rt.lock:
            if self.kv.remote:
                async with self.kv.lock(f"call:{rt.call_id}", ttl_s=30.0):
                    yield
            else:
                yield

    def _validate_language_mode(self, requested: str, prefs: UserPreferences) -> str:
        if requested in ("", "auto"):
            return "auto" if prefs.auto_detect_language else prefs.primary_language
        if requested not in self._supported:
            raise InvalidInput(
                f"Unsupported language '{requested}'. Supported: {', '.join(sorted(self._supported))} or 'auto'."
            )
        return requested

    async def _enforce_limits(self, repo: Repository, user_id: str, now: datetime) -> None:
        if await repo.count_active_calls(user_id) >= self.settings.max_active_calls:
            raise Conflict("Too many calls are active at once. End one before starting another.")
        if await repo.count_calls_since(user_id, _utc_midnight(now)) >= self.settings.daily_call_cap:
            midnight = _utc_midnight(now) + timedelta(days=1)
            raise RateLimited(
                "The daily call limit has been reached.", retry_after_s=max(1, int((midnight - now).total_seconds()))
            )

    def _engine_config(
        self, call_id: str, principal: Principal, prefs: UserPreferences, profile: AssistantProfile, language_mode: str
    ) -> EngineConfig:
        owner = profile.owner_display_name
        if owner.strip().lower() == ASSISTANT_PROFILE_DEFAULT_NAME and principal.display_name:
            owner = principal.display_name
        return EngineConfig(
            call_id=call_id,
            owner_name=None if owner.strip().lower() == ASSISTANT_PROFILE_DEFAULT_NAME else owner,
            response_style=profile.response_style,
            speaking_rate=profile.speaking_rate,
            voice_ids=dict(profile.voice_ids),
            primary_language=prefs.primary_language,
            enabled_languages=tuple(prefs.enabled_languages),
            language_mode=language_mode,
            auto_detect_language=prefs.auto_detect_language,
            strictness=prefs.strictness,
            escalation=prefs.escalation,
        )

    def _runtime_from_row(self, row: m.CallSessionRow) -> CallRuntime:
        cfg, params = config_from_json(row.id, row.config or {"engine": {}})
        provider = self._provider_by_name(row.provider)
        rt = CallRuntime(
            row.id, row.user_id, cfg, params, provider, row.external_id, row.simulated, self.clock.monotonic()
        )
        rt.state = CallState(row.state)
        self._runtimes[row.id] = rt
        return rt

    async def _runtime(self, user_id: str, call_id: str) -> CallRuntime:
        rt = self._runtimes.get(call_id)
        if rt is not None and rt.user_id == user_id:
            return rt
        async with self.db.uow() as repo:
            row = await repo.get_call_row(user_id, call_id)
            if row is None:
                raise NotFound("Call not found.")
            if row.status != CallStatus.ACTIVE.value or row.mode != CallMode.CONVERSATIONAL.value:
                raise Conflict("This call has ended.")
            return self._runtime_from_row(row)

    # ================================================================================ create
    async def create_call(self, principal: Principal, req: CreateCallRequest, *, simulator: bool) -> CallDetail:
        provider = self.sim_telephony if simulator else self.telephony
        if not simulator and not provider.capabilities.simulated:
            raise UnsupportedByProvider(
                "Calls from this telephony provider start when the provider delivers them; they cannot be created here. "
                "Use the Simulator Lab to start a simulated call."
            )
        return await self._create(principal, provider, req, incoming=None)

    async def _create(
        self, principal: Principal, provider: TelephonyProvider, req: CreateCallRequest, incoming: IncomingCall | None
    ) -> CallDetail:
        now = self.clock.now()
        call_id = self.ids.new("call")
        simulated = provider.capabilities.simulated
        raw_number = incoming.caller_number if incoming else req.caller_number
        e164 = normalize_number(raw_number)
        async with self.db.uow() as repo:
            await repo.ensure_user(principal.id, principal.display_name or principal.id, now)
            prefs = await repo.get_preferences(principal.id)
            profile = await repo.get_assistant_profile(principal.id) or AssistantProfile()
            await self._enforce_limits(repo, principal.id, now)
            language_mode = self._validate_language_mode(req.language_mode, prefs)
            fp = None
            if e164:
                fp = fingerprint(user_salt(self.pepper, principal.id), e164)
            blocked, trusted = await repo.caller_status(principal.id, fp) if fp else (False, False)
            label = (req.caller_label or "").strip() or None
            masked = mask_number(e164) if e164 else None
            display = (
                f"{label} · {masked}" if (label and masked) else (masked or label or self._default_display(provider))
            )
            cfg = self._engine_config(call_id, principal, prefs, profile, language_mode)
            params = RuntimeParams(
                silence_timers=req.silence_timers == "preferences",
                silence_first_s=float(prefs.silence_first_timeout_s),
                silence_second_s=float(prefs.silence_second_timeout_s),
                owner_timeout_s=float(prefs.escalation.owner_response_timeout_s),
                max_duration_s=float(min(prefs.max_call_duration_s, self.settings.max_call_duration_s)),
                network_profile=req.network_profile,
            )
            row = m.CallSessionRow(
                id=call_id,
                user_id=principal.id,
                provider=provider.kind.value,
                mode=CallMode.CONVERSATIONAL.value,
                simulated=simulated,
                status=CallStatus.ACTIVE.value,
                state=CallState.INITIALIZING.value,
                language_mode=language_mode,
                started_at=now,
                caller_fingerprint=fp,
                caller_display=display[:64],
                caller_number_enc=e164 if (e164 and prefs.retention.store_full_caller_number) else None,
                caller_label=(label or None),
                claim=None,
                category=CallCategory.UNKNOWN.value,
                risk_level=RiskLevel.UNKNOWN.value,
                risk_score=0.0,
                confidence=0.0,
                signal_codes=[],
                languages=[],
                owner_attention=False,
                blocked=blocked,
                trusted=trusted,
                has_content=True,
                config=config_to_json(cfg, params),
                trace_id=new_trace_id(),
                versions=self._versions(provider),
                metrics={},
                external_id=incoming.provider_call_id if incoming else None,
                scenario_id=req.scenario_id,
                network_profile=req.network_profile,
            )
            await repo.create_call(row)
            ev = self._buffer(repo, call_id, simulated)
            await ev.emit(EventType.CALL_CREATED, {"call": list_item_from_row(row).model_dump(mode="json")})

            bypass = self._bypass_reason(blocked, trusted, prefs, simulated)
            if bypass is not None:
                detail = await self._finish_bypassed(repo, ev, row, bypass, simulated)
                published = ev.items
            else:
                result = self.engine.start(cfg)
                await ev.emit(EventType.CALL_CONNECTED, {"state": result.ctx.state.value})
                await self._persist_result(
                    repo, ev, row, ConversationContext(), result, latency=self._tts_latency(call_id, 1, params)
                )
                detail = None
                published = ev.items
        await self._publish(principal.id, published)
        self.metrics.inc(mt.CALLS_TOTAL, provider=provider.name, outcome="started")
        if bypass is not None and detail is not None:
            return detail

        rt = CallRuntime(
            call_id, principal.id, cfg, params, provider, row.external_id, simulated, self.clock.monotonic()
        )
        rt.state = result.ctx.state
        self._runtimes[call_id] = rt
        async with self._locked(rt):
            with contextlib.suppress(ProviderError):
                await provider.answer(rt.ref)
            assert result.assistant_turn is not None
            await self._play(rt, result.assistant_turn)
            rt.limit_task = asyncio.create_task(self._limit_after(rt))
        return await self.get_call(principal, call_id)

    def _default_display(self, provider: TelephonyProvider) -> str:
        return DEFAULT_SOURCE_LABEL.get(provider.name, PRIVATE_DISPLAY)

    @staticmethod
    def _bypass_reason(blocked: bool, trusted: bool, prefs: UserPreferences, simulated: bool) -> str | None:
        if blocked:
            return "blocked_number"
        if trusted and simulated and prefs.trusted_contact_behavior == "allow_directly":
            return "trusted_caller"
        return None

    async def _finish_bypassed(
        self, repo: Repository, ev: EventBuffer, row: m.CallSessionRow, reason: str, simulated: bool
    ) -> CallDetail:
        """A blocked number is ended without answering; a trusted caller is passed straight through (simulated)."""
        now = self.clock.now()
        ctx = ConversationContext(state=CallState.COMPLETED, ended_reason=reason)
        if reason == "blocked_number":
            text = f"Caller {row.caller_display} is on your blocked list. Sparta ended the call without answering."
            action = "ended_blocked_number"
        else:
            tag = " (simulated)" if simulated else ""
            text = (
                f"Trusted caller {row.caller_display} was passed straight through to you{tag}. No screening was needed."
            )
            action = "passed_trusted_caller"
        summary = CallSummary(
            call_id=row.id,
            text=text,
            category=CallCategory.UNKNOWN,
            risk_level=RiskLevel.UNKNOWN,
            action_taken=action,
            owner_action_required=reason == "trusted_caller",
            generated_by="rules-v1",
            created_at=now,
        )
        await repo.save_summary(summary)
        await repo.update_call(
            row.id,
            status=CallStatus.ENDED.value,
            state=CallState.COMPLETED.value,
            ended_at=now,
            duration_ms=0,
            summary_text=text,
            action_taken=action,
            context=ctx.model_dump(mode="json"),
            owner_attention=summary.owner_action_required,
        )
        await ev.emit(EventType.CALL_ENDED, {"reason": reason, "state": CallState.COMPLETED.value, "duration_ms": 0})
        await ev.emit(EventType.SUMMARY_CREATED, {"summary": summary.model_dump(mode="json")})
        self.metrics.inc(mt.CALLS_TOTAL, provider=row.provider, outcome=reason)
        detail = await repo.load_detail(row.user_id, row.id)
        assert detail is not None
        detail.capabilities = self._capabilities_for(row.provider, ended=True)
        return detail

    # ====================================================================== persistence of an engine step
    def _tts_latency(self, call_id: str, seq: int, params: RuntimeParams) -> LatencyBreakdown:
        prof = NETWORK_PROFILES[params.network_profile]
        sim: list[str] = []
        tts = pb = None
        if prof.tts_first_audio_ms:
            tts, pb = (
                jitter(prof.tts_first_audio_ms, call_id, seq, "tts"),
                jitter(prof.playback_start_ms, call_id, seq, "pb"),
            )
            sim = ["tts_first_audio_ms", "playback_start_ms"]
        total = round((tts or 0) + (pb or 0), 1) or None
        return LatencyBreakdown(tts_first_audio_ms=tts, playback_start_ms=pb, total_ms=total, simulated_stages=sim)

    def _turn_latency(
        self,
        rt: CallRuntime,
        inp_source: TurnSource,
        stt_ms: float | None,
        result: EngineResult,
        model_ms: float | None,
    ) -> tuple[LatencyBreakdown, float]:
        prof = NETWORK_PROFILES[rt.params.network_profile]
        seq = result.ctx.seq
        sim_stages: list[str] = []
        sim_ms = 0.0
        stt = stt_ms
        audio_source = inp_source in (TurnSource.BROWSER_STT, TurnSource.UPLOADED_AUDIO, TurnSource.PROVIDER_STT)
        if stt is None and audio_source and prof.stt_ms:
            stt = jitter(prof.stt_ms, rt.call_id, seq, "stt")
            sim_stages.append("stt_ms")
            sim_ms += stt
        tts = pb = None
        if prof.tts_first_audio_ms:
            tts = jitter(prof.tts_first_audio_ms, rt.call_id, seq, "tts")
            pb = jitter(prof.playback_start_ms, rt.call_id, seq, "pb")
            sim_stages += ["tts_first_audio_ms", "playback_start_ms"]
            sim_ms += tts + pb
        t = result.timings_ms
        measured = [
            stt_ms,
            t.get("language_detect_ms"),
            t.get("policy_ms", 0) + t.get("decision_ms", 0),
            model_ms,
            t.get("plan_ms"),
        ]
        total = round(
            sum(v for v in measured if v) + (stt if stt_ms is None and stt else 0) + (tts or 0) + (pb or 0), 1
        )
        return (
            LatencyBreakdown(
                stt_ms=stt,
                language_detect_ms=t.get("language_detect_ms"),
                policy_ms=round(t.get("policy_ms", 0) + t.get("decision_ms", 0), 3),
                model_ms=model_ms,
                tts_first_audio_ms=tts,
                playback_start_ms=pb,
                total_ms=total,
                simulated_stages=sim_stages,
            ),
            sim_ms,
        )

    @staticmethod
    def _denormalised(ctx: ConversationContext, risk: RiskAssessment | None) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "state": ctx.state.value,
            "context": ctx.model_dump(mode="json"),
            "language_profile": ctx.language_profile,
            "languages": list(ctx.detected_languages),
            "claim": ctx.caller_claim.model_dump(mode="json"),
            "action_taken": ctx.action_taken,
        }
        if risk is not None:
            fields.update(
                purpose=risk.purpose or ctx.purpose,
                category=risk.category.value,
                risk_level=risk.risk_level.value,
                risk_score=risk.risk_score,
                confidence=risk.confidence,
                recommended_action=risk.recommended_action.value,
                signal_codes=sorted(s.code.value for s in risk.signals),
                owner_attention=risk.requires_owner_attention,
            )
        elif ctx.purpose:
            fields["purpose"] = ctx.purpose
        return fields

    async def _persist_result(
        self,
        repo: Repository,
        ev: EventBuffer,
        row: m.CallSessionRow,
        old_ctx: ConversationContext,
        result: EngineResult,
        *,
        latency: LatencyBreakdown | None,
    ) -> None:
        now = self.clock.now()
        ctx = result.ctx
        if result.caller_turn is not None:
            turn = result.caller_turn
            turn.latency = latency
            await repo.add_turns([turn])
            await ev.emit(EventType.TRANSCRIPT_FINAL, {"turn": turn.model_dump(mode="json")})
            self.metrics.inc(mt.AUDIO_SECONDS, 0.0, provider=row.provider)
            if turn.confidence is not None:
                self.metrics.observe(mt.TRANSCRIPT_CONFIDENCE, turn.confidence)
            if turn.language_confidence is not None:
                self.metrics.observe(mt.LANGUAGE_CONFIDENCE, turn.language_confidence)
        if result.language_changed:
            await ev.emit(EventType.LANGUAGE_CHANGED, dict(result.language_changed))
        previous = old_ctx.state
        for state in result.state_path:
            await ev.emit(EventType.STATE_CHANGED, {"from": previous.value, "to": state.value})
            previous = state
        risk = result.risk
        if risk is not None and risk_changed(old_ctx.risk, risk):
            await repo.save_risk(row.id, risk, now)
            await ev.emit(EventType.RISK_UPDATED, {"risk": risk.model_dump(mode="json")})
        if result.escalation is not None:
            await repo.add_escalation(result.escalation)
            await ev.emit(
                EventType.ESCALATION_REQUESTED,
                {
                    "escalation": result.escalation.model_dump(mode="json"),
                    "risk": risk.model_dump(mode="json") if risk else None,
                },
            )
            self.metrics.inc(mt.ESCALATIONS_TOTAL, provider=row.provider)
        if result.assistant_turn is not None:
            turn = result.assistant_turn
            turn.latency = latency
            await repo.add_turns([turn])
            await ev.emit(EventType.TRANSCRIPT_FINAL, {"turn": turn.model_dump(mode="json")})
            speech = turn.speech
            assert speech is not None
            await ev.emit(
                EventType.ASSISTANT_SPEAKING,
                {
                    "turn_id": turn.id,
                    "text": speech.text,
                    "locale": speech.locale,
                    "voice_id": speech.voice_id,
                    "est_duration_ms": speech.est_duration_ms,
                },
            )
        if result.validator_fallback:
            self.metrics.inc(mt.VALIDATOR_FALLBACKS)
        await repo.update_call(row.id, **self._denormalised(ctx, risk or ctx.risk))
        if latency is not None and latency.total_ms is not None:
            self.metrics.observe(mt.STAGE_LATENCY_MS, latency.total_ms, stage="turn_total")
        for stage in ("language_detect_ms", "policy_ms"):
            value = getattr(latency, stage, None) if latency else None
            if value is not None:
                self.metrics.observe(mt.STAGE_LATENCY_MS, value, stage=stage)

    # ===================================================================================== playback
    async def _play(self, rt: CallRuntime, turn: CallTurn) -> None:
        """Speak an assistant turn through the telephony provider and remember when it will be over."""
        assert turn.speech is not None
        try:
            playback: Playback = await rt.provider.play(rt.ref, turn.speech)
        except ProviderError as exc:
            await self._report_provider_error(rt, exc, degraded=True)
            rt.playback_id, rt.speaking_until = None, 0.0
            if rt.pending_finalize:
                await self._finalize_locked(rt)
            else:
                self._arm_silence(rt)
            return
        rt.playback_id = playback.playback_id
        rt.speaking_turn_id = turn.id
        rt.speaking_started = self.clock.monotonic()
        rt.speaking_est_ms = playback.duration_ms
        rt.speaking_until = rt.speaking_started + playback.duration_ms / 1000.0

    async def playback_finished(self, call_id: str, playback_id: str) -> None:
        rt = self._runtimes.get(call_id)
        if rt is None or rt.playback_id != playback_id:
            return
        async with self._locked(rt):
            if rt.playback_id != playback_id:
                return
            turn_id = rt.speaking_turn_id
            rt.playback_id, rt.speaking_until = None, 0.0
            async with self.db.uow() as repo:
                row = await repo.get_call_row(rt.user_id, call_id)
                if row is None or row.status != CallStatus.ACTIVE.value:
                    return
                ctx = repo.context_of(row)
                ctx.assistant_speaking = False
                await repo.update_call(call_id, context=ctx.model_dump(mode="json"))
                ev = self._buffer(repo, call_id, rt.simulated)
                await ev.emit(EventType.ASSISTANT_FINISHED, {"turn_id": turn_id})
                await ev.emit(EventType.CALL_LISTENING, {})
            await self._publish(rt.user_id, ev.items)
            if rt.pending_finalize:
                await self._finalize_locked(rt)
            else:
                self._arm_silence(rt)

    async def _barge_in_locked(
        self, rt: CallRuntime, *, spoken_fraction: float | None = None, force: bool = False
    ) -> InterruptResult:
        now = self.clock.monotonic()
        if not rt.playback_id or (not force and rt.speaking_until <= now):
            return InterruptResult(interrupted=False)
        started = time.perf_counter()
        est = rt.speaking_est_ms / 1000.0
        fraction = (
            spoken_fraction
            if spoken_fraction is not None
            else (min(1.0, (now - rt.speaking_started) / est) if est else 1.0)
        )
        playback_id, turn_id = rt.playback_id, rt.speaking_turn_id
        with contextlib.suppress(ProviderError):
            await rt.provider.stop_playback(rt.ref, playback_id)
        interruption_ms = round((time.perf_counter() - started) * 1000.0, 3)
        rt.playback_id, rt.speaking_until = None, 0.0
        async with self.db.uow() as repo:
            row = await repo.get_call_row(rt.user_id, rt.call_id)
            if row is None:
                return InterruptResult(interrupted=False)
            ctx = repo.context_of(row)
            ctx.assistant_speaking = False
            await repo.update_call(rt.call_id, context=ctx.model_dump(mode="json"))
            if turn_id:
                turn = await repo.get_turn(rt.call_id, turn_id)
                latency = (turn.latency if turn and turn.latency else LatencyBreakdown()).model_copy(
                    update={"interruption_ms": interruption_ms}
                )
                await repo.update_turn(
                    rt.call_id,
                    turn_id,
                    interrupted=True,
                    spoken_fraction=round(fraction, 3),
                    latency=latency.model_dump(mode="json"),
                )
            ev = self._buffer(repo, rt.call_id, rt.simulated)
            await ev.emit(
                EventType.ASSISTANT_INTERRUPTED,
                {"turn_id": turn_id, "spoken_fraction": round(fraction, 3), "interruption_ms": interruption_ms},
            )
        await self._publish(rt.user_id, ev.items)
        self.metrics.observe(mt.STAGE_LATENCY_MS, interruption_ms, stage="interruption")
        return InterruptResult(
            interrupted=True, turn_id=turn_id, interruption_ms=interruption_ms, spoken_fraction=round(fraction, 3)
        )

    # ======================================================================================= timers
    def _arm_silence(self, rt: CallRuntime) -> None:
        if rt.silence_task is not None and not rt.silence_task.done():
            rt.silence_task.cancel()
        rt.silence_task = None
        if not rt.params.silence_timers or rt.state in (
            CallState.OWNER_TAKEOVER,
            CallState.COMPLETED,
            CallState.FAILED,
        ):
            return
        if rt.pending_finalize:
            return
        delay = rt.params.silence_first_s if rt.silence_count == 0 else rt.params.silence_second_s
        rt.silence_task = asyncio.create_task(self._silence_after(rt, delay))

    async def _silence_after(self, rt: CallRuntime, delay: float) -> None:
        try:
            await self.clock.sleep(delay)
            if rt.call_id not in self._runtimes:
                return
            async with self._locked(rt):
                await self._silence_locked(rt)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("silence timer failed")

    async def _limit_after(self, rt: CallRuntime) -> None:
        try:
            await self.clock.sleep(rt.params.max_duration_s)
            if rt.call_id not in self._runtimes:
                return
            async with self._locked(rt):
                await self._step_locked(rt, lambda ctx: self.engine.on_limit_reached(ctx, rt.cfg, "max_duration"))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("duration limit failed")

    async def _owner_timeout_after(self, rt: CallRuntime, escalation_id: str) -> None:
        try:
            await self.clock.sleep(rt.params.owner_timeout_s)
            if rt.call_id not in self._runtimes:
                return
            async with self._locked(rt):
                await self._step_locked(
                    rt,
                    lambda ctx: self.engine.on_owner_timeout(ctx, rt.cfg),
                    escalation_resolution=(escalation_id, EscalationStatus.EXPIRED),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("owner timeout failed")

    # ================================================================ generic non-turn engine steps
    async def _step_locked(
        self,
        rt: CallRuntime,
        run: Callable[[ConversationContext], EngineResult],
        *,
        escalation_resolution: tuple[str, EscalationStatus] | None = None,
        owner_action: OwnerAction | None = None,
        extra_events: list[tuple[EventType, dict[str, Any]]] | None = None,
    ) -> EngineResult | None:
        async with self.db.uow() as repo:
            row = await repo.get_call_row(rt.user_id, rt.call_id)
            if row is None or row.status != CallStatus.ACTIVE.value:
                return None
            old_ctx = repo.context_of(row)
        result = run(old_ctx)
        if (
            result.notes
            and result.assistant_turn is None
            and result.final_state == old_ctx.state
            and not result.state_path
        ):
            return result
        latency = self._tts_latency(rt.call_id, result.ctx.seq, rt.params)
        sim_delay = (latency.tts_first_audio_ms or 0) + (latency.playback_start_ms or 0)
        if sim_delay:
            await self.clock.sleep(sim_delay / 1000.0)
        async with self.db.uow() as repo:
            row = await repo.get_call_row(rt.user_id, rt.call_id)
            assert row is not None
            ev = self._buffer(repo, rt.call_id, rt.simulated)
            if escalation_resolution:
                await repo.resolve_escalation(escalation_resolution[0], escalation_resolution[1], self.clock.now())
            if owner_action is not None:
                await repo.add_owner_action(owner_action)
            await self._persist_result(repo, ev, row, old_ctx, result, latency=latency)
            for kind, data in extra_events or []:
                await ev.emit(kind, data)
        await self._publish(rt.user_id, ev.items)
        rt.state = result.final_state
        rt.silence_count = result.ctx.silence_count
        if result.hangs_up:
            rt.pending_finalize = True
        if result.assistant_turn is not None:
            await self._play(rt, result.assistant_turn)
        elif result.hangs_up:
            await self._finalize_locked(rt)
        return result

    async def _silence_locked(self, rt: CallRuntime) -> EngineResult | None:
        result = await self._step_locked(rt, lambda ctx: self.engine.on_silence(ctx, rt.cfg))
        if result is not None:
            rt.silence_count = result.ctx.silence_count
        return result

    # ===================================================================================== turns
    async def submit_turn(
        self,
        principal: Principal,
        call_id: str,
        text: str,
        *,
        source: TurnSource = TurnSource.TYPED,
        language_hint: str | None = None,
        stt_confidence: float | None = None,
        stt_ms: float | None = None,
    ) -> TurnResult:
        rt = await self._runtime(principal.id, call_id)
        return await self._submit_turn(rt, text, source, language_hint, stt_confidence, stt_ms)

    async def _submit_turn(
        self,
        rt: CallRuntime,
        text: str,
        source: TurnSource,
        language_hint: str | None,
        stt_confidence: float | None,
        stt_ms: float | None,
    ) -> TurnResult:
        text = sanitize_text(text)
        if not text:
            raise InvalidInput("The turn has no text.")
        async with self._locked(rt):
            rt.last_activity = self.clock.monotonic()
            if rt.silence_task is not None and not rt.silence_task.done():
                rt.silence_task.cancel()
            interrupted = await self._barge_in_locked(rt)
            async with self.db.uow() as repo:
                row = await repo.get_call_row(rt.user_id, rt.call_id)
                if row is None or row.status != CallStatus.ACTIVE.value:
                    raise Conflict("This call has ended.")
                old_ctx = repo.context_of(row)
                if not self.engine.accepts_caller_input(old_ctx):
                    raise Conflict("This call is ending and cannot accept more input.")
                previous = await repo.last_caller_turn(rt.call_id)
                recent = await repo.recent_turns(rt.call_id)
            model_codes, model_ms = await self._model_signals(rt, text, old_ctx, recent)
            started = time.perf_counter()
            result = self.engine.on_caller_turn(
                old_ctx,
                rt.cfg,
                CallerInput(
                    text=text,
                    source=source,
                    language_hint=language_hint,
                    stt_confidence=stt_confidence,
                    previous_text=previous[1] if previous else None,
                    previous_turn_id=previous[0] if previous else None,
                    model_signal_codes=model_codes,
                ),
            )
            self.metrics.observe(mt.RISK_ENGINE_MS, (time.perf_counter() - started) * 1000.0)
            latency, sim_ms = self._turn_latency(rt, source, stt_ms, result, model_ms)
            if sim_ms:
                await self.clock.sleep(sim_ms / 1000.0)
            async with self.db.uow() as repo:
                row = await repo.get_call_row(rt.user_id, rt.call_id)
                assert row is not None
                ev = self._buffer(repo, rt.call_id, rt.simulated)
                await self._persist_result(repo, ev, row, old_ctx, result, latency=latency)
                item = list_item_from_row(row)
            await self._publish(rt.user_id, ev.items)
            rt.state = result.final_state
            rt.silence_count = result.ctx.silence_count
            if result.escalation is not None:
                await self._on_escalation(rt, result)
            if result.hangs_up:
                rt.pending_finalize = True
            if result.assistant_turn is not None:
                await self._play(rt, result.assistant_turn)
            elif result.hangs_up:
                await self._finalize_locked(rt)
            return TurnResult(
                caller_turn=result.caller_turn,
                assistant_turn=result.assistant_turn,
                call=item,
                risk=result.risk or result.ctx.risk,
                state=result.final_state,
                ended=result.hangs_up,
                escalation=result.escalation,
                interrupted_turn_id=interrupted.turn_id if interrupted.interrupted else None,
            )

    async def _model_signals(
        self, rt: CallRuntime, text: str, ctx: ConversationContext, recent: list[tuple[str, str]]
    ) -> tuple[tuple[Any, ...], float | None]:
        """Optional model analysis. Failure degrades silently to the deterministic engine."""
        if self.llm.meta.provider == "rules":
            return (), None
        started = time.perf_counter()
        request = TurnEvaluationRequest(
            call_id=rt.call_id,
            caller_text=text[:600],
            language=ctx.language,
            recent_turns=[(s, t[:300]) for s, t in recent[-6:]],
            known_signals=[s.code for s in ctx.signals],
            trace_id="",
        )
        analysis, error = await self._llm_caller.call_or(lambda: self.llm.evaluate_turn(request), None)
        elapsed = round((time.perf_counter() - started) * 1000.0, 1)
        if error is not None or analysis is None:
            if error is not None:
                await self._report_provider_error(rt, error, degraded=True)
            return (), elapsed
        usage = analysis.usage
        self.metrics.inc(mt.TOKENS_TOTAL, usage.prompt_tokens, kind="prompt")
        self.metrics.inc(mt.TOKENS_TOTAL, usage.completion_tokens, kind="completion")
        return tuple(analysis.extra_signals), elapsed

    async def _on_escalation(self, rt: CallRuntime, result: EngineResult) -> None:
        assert result.escalation is not None
        if rt.owner_task is not None and not rt.owner_task.done():
            rt.owner_task.cancel()
        rt.owner_task = asyncio.create_task(self._owner_timeout_after(rt, result.escalation.id))
        async with self.db.uow() as repo:
            prefs = await repo.get_preferences(rt.user_id)
        if prefs.notifications.notify_on_escalation:
            lines = result.escalation.important_lines if prefs.notifications.include_transcript_lines else []
            risk = result.risk
            body = (risk.purpose if risk and risk.purpose else "A call may need your attention") + (
                " (simulated call)" if rt.simulated else ""
            )
            try:
                await self.notifier.notify(
                    rt.user_id,
                    PushNotification("escalation", rt.call_id, "Sparta needs you", body, list(lines)),
                )
            except Exception:
                log.exception("push notification failed")

    async def submit_partial(self, principal: Principal, call_id: str, text: str, language_hint: str | None) -> None:
        rt = await self._runtime(principal.id, call_id)
        text = sanitize_text(text)
        async with self.db.uow() as repo:
            row = await repo.get_call_row(principal.id, call_id)
            if row is None or row.status != CallStatus.ACTIVE.value:
                raise Conflict("This call has ended.")
            ev = self._buffer(repo, call_id, rt.simulated)
            await ev.emit(
                EventType.TRANSCRIPT_PARTIAL, {"speaker": Speaker.CALLER.value, "text": text, "language": language_hint}
            )
        await self._publish(principal.id, ev.items)

    async def silence(self, principal: Principal, call_id: str) -> TurnResult:
        rt = await self._runtime(principal.id, call_id)
        async with self._locked(rt):
            result = await self._silence_locked(rt)
            async with self.db.uow() as repo:
                row = await repo.get_call_row(principal.id, call_id)
                assert row is not None
                item = list_item_from_row(row)
            if result is None:
                raise Conflict("This call has ended.")
            return TurnResult(
                caller_turn=None,
                assistant_turn=result.assistant_turn,
                call=item,
                risk=result.risk or result.ctx.risk,
                state=result.final_state,
                ended=result.hangs_up,
            )

    async def interrupt(
        self, principal: Principal, call_id: str, spoken_fraction: float | None = None
    ) -> InterruptResult:
        rt = await self._runtime(principal.id, call_id)
        async with self._locked(rt):
            return await self._barge_in_locked(rt, spoken_fraction=spoken_fraction, force=True)

    # ================================================================================ owner actions
    async def owner_action(self, principal: Principal, call_id: str, action: OwnerActionType) -> OwnerActionResult:
        rt = await self._runtime(principal.id, call_id)
        caps = rt.provider.capabilities
        if action is OwnerActionType.TAKEOVER and not caps.can_transfer:
            raise UnsupportedByProvider(
                caps.call_capabilities().takeover_note or "This provider cannot hand the call to you."
            )
        if action is OwnerActionType.END and not caps.can_hangup:
            raise UnsupportedByProvider("This provider cannot end the call from here.")
        async with self._locked(rt):
            rt.last_activity = self.clock.monotonic()
            async with self.db.uow() as repo:
                row = await repo.get_call_row(principal.id, call_id)
                if row is None or row.status != CallStatus.ACTIVE.value:
                    raise Conflict("This call has ended.")
                ctx = repo.context_of(row)
                prefs = await repo.get_preferences(principal.id)
            if action is OwnerActionType.CONTINUE and ctx.state is not CallState.ESCALATE:
                raise Conflict("Sparta is not waiting for your decision on this call.")
            if action is OwnerActionType.TAKEOVER and not rt.simulated and not prefs.takeover_number:
                raise UnsupportedByProvider(
                    "Set the phone number Sparta should bridge you to (Assistant Studio) before using Take Over."
                )
            record = OwnerAction(
                id=self.ids.new("act"),
                call_id=call_id,
                action=action,
                created_at=self.clock.now(),
                simulated=caps.simulated,
                detail="Simulated: no real call was bridged"
                if (caps.simulated and action is OwnerActionType.TAKEOVER)
                else None,
            )
            resolution = None
            if ctx.escalation_id:
                status = {
                    OwnerActionType.TAKEOVER: EscalationStatus.TAKEN_OVER,
                    OwnerActionType.CONTINUE: EscalationStatus.CONTINUED,
                }.get(action, EscalationStatus.ENDED)
                resolution = (ctx.escalation_id, status)
            if rt.owner_task is not None and not rt.owner_task.done():
                rt.owner_task.cancel()
            event_type = EventType.OWNER_TAKEOVER if action is OwnerActionType.TAKEOVER else EventType.OWNER_ACTION
            payload: dict[str, Any] = {"action": record.model_dump(mode="json")}
            if action is OwnerActionType.TAKEOVER:
                payload["simulated"] = caps.simulated
            if rt.playback_id:
                await self._barge_in_locked(rt, force=True)
            result = await self._step_locked(
                rt,
                lambda c: self.engine.on_owner_action(c, rt.cfg, action),
                escalation_resolution=resolution,
                owner_action=record,
                extra_events=[(event_type, payload)],
            )
            if result is None or "call_not_active" in result.notes:
                raise Conflict("This call has ended.")
            if action is OwnerActionType.TAKEOVER:
                outcome = await rt.provider.transfer(rt.ref, prefs.takeover_number)
                if not outcome.accepted:
                    await self._report_provider_error(
                        rt,
                        ProviderError(rt.provider.name, "transfer", outcome.detail or "transfer was not accepted"),
                        False,
                    )
            async with self.db.uow() as repo:
                row = await repo.get_call_row(principal.id, call_id)
                assert row is not None
                item = list_item_from_row(row)
            return OwnerActionResult(
                action=record,
                call=item,
                capabilities=self._capabilities_for(row.provider, ended=item.status != CallStatus.ACTIVE),
            )

    async def block(self, principal: Principal, call_id: str, reason: str | None) -> BlockedCaller:
        async with self.db.uow() as repo:
            row = await repo.get_call_row(principal.id, call_id)
            if row is None:
                raise NotFound("Call not found.")
            if not row.caller_fingerprint:
                raise Conflict("This call has no caller number to block.")
            number = None
            entry = await repo.add_blocked(
                principal.id,
                self.ids.new("blk"),
                row.caller_fingerprint,
                row.caller_display,
                number,
                reason,
                call_id,
                self.clock.now(),
            )
            await repo.update_call(call_id, blocked=True, trusted=False)
            active = row.status == CallStatus.ACTIVE.value
            await repo.add_owner_action(
                OwnerAction(
                    id=self.ids.new("act"),
                    call_id=call_id,
                    action=OwnerActionType.BLOCK,
                    created_at=self.clock.now(),
                    simulated=row.simulated,
                )
            )
        if active:
            rt = await self._runtime(principal.id, call_id)
            async with self._locked(rt):
                await self._step_locked(rt, lambda c: self.engine.on_owner_action(c, rt.cfg, OwnerActionType.BLOCK))
        return entry

    async def trust(self, principal: Principal, call_id: str, label: str | None) -> TrustedCaller:
        async with self.db.uow() as repo:
            row = await repo.get_call_row(principal.id, call_id)
            if row is None:
                raise NotFound("Call not found.")
            if not row.caller_fingerprint:
                raise Conflict("This call has no caller number to trust.")
            entry = await repo.add_trusted(
                principal.id,
                self.ids.new("tru"),
                row.caller_fingerprint,
                row.caller_display,
                None,
                label,
                call_id,
                self.clock.now(),
            )
            await repo.update_call(call_id, trusted=True, blocked=False)
            await repo.add_owner_action(
                OwnerAction(
                    id=self.ids.new("act"),
                    call_id=call_id,
                    action=OwnerActionType.TRUST,
                    created_at=self.clock.now(),
                    simulated=row.simulated,
                )
            )
        return entry

    async def feedback(
        self, principal: Principal, call_id: str, kind: FeedbackKind, note: str | None
    ) -> FeedbackRecord:
        async with self.db.uow() as repo:
            row = await repo.get_call_row(principal.id, call_id)
            if row is None:
                raise NotFound("Call not found.")
            record, created = await repo.add_feedback(
                FeedbackRecord(
                    id=self.ids.new("fbk"), call_id=call_id, kind=kind, note=(note or None), created_at=self.clock.now()
                ),
                principal.id,
            )
        if created:
            self.metrics.inc(mt.FEEDBACK_TOTAL, kind=kind.value)
        if kind is FeedbackKind.TRUST_CALLER and created:
            with contextlib.suppress(Conflict):
                await self.trust(principal, call_id, None)
        elif kind is FeedbackKind.BLOCK_CALLER and created:
            with contextlib.suppress(Conflict):
                await self.block(principal, call_id, "Owner feedback")
        return record

    # ====================================================================================== finalize
    async def _finalize_locked(self, rt: CallRuntime, reason: str | None = None) -> None:
        rt.cancel_timers()
        async with self.db.uow() as repo:
            row = await repo.get_call_row(rt.user_id, rt.call_id)
            if row is None or row.status != CallStatus.ACTIVE.value:
                self._runtimes.pop(rt.call_id, None)
                return
            prefs = await repo.get_preferences(rt.user_id)
            ctx = self.engine.complete(repo.context_of(row), reason or "completed")
            risk = ctx.risk or await repo.latest_risk(rt.call_id)
            summary = build_summary(rt.call_id, ctx, risk, simulated=rt.simulated)
            summary = await self._maybe_llm_summary(rt, repo, summary, risk)
            now = self.clock.now()
            ended_at = now
            duration_ms = max(0, int((ended_at - row.started_at).total_seconds() * 1000))
            await repo.save_summary(summary)
            for escalation in await repo.list_escalations(rt.call_id):
                if escalation.status is EscalationStatus.REQUESTED:
                    await repo.resolve_escalation(escalation.id, EscalationStatus.ENDED, now)
            turns = await repo.list_turns(rt.call_id)
            call_metrics = self._call_metrics(turns, duration_ms, rt)
            await repo.update_call(
                rt.call_id,
                status=CallStatus.ENDED.value,
                state=CallState.COMPLETED.value,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary_text=summary.text,
                context=ctx.model_dump(mode="json"),
                action_taken=ctx.action_taken,
                owner_attention=summary.owner_action_required,
                metrics=call_metrics,
            )
            ev = self._buffer(repo, rt.call_id, rt.simulated)
            await ev.emit(EventType.STATE_CHANGED, {"from": rt.state.value, "to": CallState.COMPLETED.value})
            await ev.emit(
                EventType.CALL_ENDED,
                {"reason": ctx.ended_reason, "state": CallState.COMPLETED.value, "duration_ms": duration_ms},
            )
            await ev.emit(EventType.SUMMARY_CREATED, {"summary": summary.model_dump(mode="json")})
            if not prefs.retention.store_transcripts:
                await repo.delete_transcript(rt.call_id)
        await self._publish(rt.user_id, ev.items)
        self._runtimes.pop(rt.call_id, None)
        with contextlib.suppress(ProviderError):
            await rt.provider.hangup(rt.ref, ctx.ended_reason or "completed")
        outcome = ctx.ended_reason or "completed"
        self.metrics.inc(mt.CALLS_TOTAL, provider=rt.provider.name, outcome=outcome)
        self.metrics.inc(mt.CALL_MINUTES, duration_ms / 60000.0, provider=rt.provider.name)
        self.metrics.inc(
            mt.COST_USD,
            estimate_cost(
                self.costs, call_minutes=duration_ms / 60000.0, tts_chars=int(call_metrics.get("tts_chars", 0))
            ),
            provider=rt.provider.name,
        )
        for hook in self.finalize_hooks:
            with contextlib.suppress(Exception):
                hook(rt.call_id)

    def _call_metrics(self, turns: list[CallTurn], duration_ms: int, rt: CallRuntime) -> dict[str, float]:
        totals = [
            t.latency.total_ms for t in turns if t.speaker is Speaker.ASSISTANT and t.latency and t.latency.total_ms
        ]
        return {
            "turns": float(len(turns)),
            "caller_turns": float(sum(1 for t in turns if t.speaker is Speaker.CALLER)),
            "duration_ms": float(duration_ms),
            "tts_chars": float(sum(len(t.text) for t in turns if t.speaker is Speaker.ASSISTANT)),
            "turn_latency_p50_ms": percentile(totals, 50) or 0.0,
            "turn_latency_p95_ms": percentile(totals, 95) or 0.0,
        }

    async def _maybe_llm_summary(
        self, rt: CallRuntime, repo: Repository, summary: CallSummary, risk: RiskAssessment | None
    ) -> CallSummary:
        if not self.settings.feature_llm_summaries or self.llm.meta.provider == "rules":
            return summary
        turns = await repo.recent_turns(rt.call_id, 12)
        request = SummaryRequest(call_id=rt.call_id, rules_summary=summary.text, turns=turns, risk=risk, trace_id="")
        outcome, error = await self._llm_caller.call_or(lambda: self.llm.summarize_call(request), None)
        if error is not None or outcome is None or not outcome.text.strip():
            return summary
        return summary.model_copy(update={"text": outcome.text.strip(), "generated_by": self.llm.meta.provider})

    async def end_internal(self, call_id: str, reason: str) -> None:
        """End a call without a principal (provider hang-up, reaper). Never speaks."""
        rt = self._runtimes.get(call_id)
        if rt is None:
            async with self.db.uow() as repo:
                row = await repo.get_call_row_any_user(call_id)
                if row is None or row.status != CallStatus.ACTIVE.value:
                    return
                rt = self._runtime_from_row(row)
        async with self._locked(rt):
            await self._finalize_locked(rt, reason)

    async def remote_hangup(self, call_id: str, reason: str) -> None:
        await self.end_internal(call_id, "caller_hung_up")

    async def reap_abandoned(self) -> int:
        """Close calls nobody is driving any more (closed browser tab, dropped provider session)."""
        now = self.clock.monotonic()
        limit = float(self.settings.abandoned_call_timeout_s)
        ended = 0
        async with self.db.uow() as repo:
            stale_rows = [(r.id, r.started_at) for r in await repo.active_call_rows()]
        wall = self.clock.now()
        for call_id, started_at in stale_rows:
            rt = self._runtimes.get(call_id)
            idle = (now - rt.last_activity) if rt else (wall - started_at).total_seconds()
            if idle > limit and (rt is None or rt.playback_id is None):
                await self.end_internal(call_id, "abandoned")
                ended += 1
        return ended

    # ===================================================================================== provider events
    async def _report_provider_error(self, rt: CallRuntime, exc: ProviderError, degraded: bool) -> None:
        self.metrics.inc(mt.PROVIDER_ERRORS, provider=exc.provider, stage=exc.stage, kind=type(exc).__name__)
        try:
            async with self.db.uow() as repo:
                if await repo.get_call_row(rt.user_id, rt.call_id) is None:
                    return
                ev = self._buffer(repo, rt.call_id, rt.simulated)
                await ev.emit(
                    EventType.PROVIDER_ERROR,
                    {"provider": exc.provider, "stage": exc.stage, "message": exc.message, "degraded": degraded},
                )
            await self._publish(rt.user_id, ev.items)
        except Exception:
            log.exception("could not record provider error")

    async def provider_error(self, call_id: str | None, stage: str, message: str) -> None:
        rt = self._runtimes.get(call_id) if call_id else None
        if rt is not None:
            await self._report_provider_error(rt, ProviderError(rt.provider.name, stage, message), degraded=True)

    async def incoming_call(self, call: IncomingCall) -> str:
        """A real provider delivered a call: create it for the configured owner and return its Sparta id."""
        owner = self.settings.telephony_owner_user_id or self.settings.dev_user_id
        principal = Principal(
            id=owner, display_name=self.settings.dev_user_name if owner == self.settings.dev_user_id else ""
        )
        detail = await self._create(principal, self.telephony, CreateCallRequest(), incoming=call)
        return detail.id

    async def caller_audio(self, call_id: str, pcm16: bytes, sample_rate: int) -> None:
        rt = self._runtimes.get(call_id)
        if rt is not None and rt.pipeline is not None:
            await rt.pipeline.feed(pcm16, sample_rate)

    async def caller_dtmf(self, call_id: str, digit: str) -> None:
        return None  # DTMF is received but never interpreted: no menu, and never a place to collect credentials

    # ======================================================================================== queries
    def _capabilities_for(self, provider_name: str, *, ended: bool) -> CallCapabilities:
        if provider_name == ProviderKind.ANDROID_SCREENING.value:
            return CallCapabilities(
                can_take_over=False,
                can_continue=False,
                can_end=False,
                can_block=True,
                takeover_note="Native phone screening cannot bridge or answer a call.",
                simulated=False,
                two_way_audio=False,
                audio_note="Android call screening has no access to call audio.",
            )
        return self._provider_by_name(provider_name).capabilities.call_capabilities(ended=ended)

    async def get_call(self, principal: Principal, call_id: str) -> CallDetail:
        async with self.db.uow() as repo:
            detail = await repo.load_detail(principal.id, call_id)
            if detail is None:
                raise NotFound("Call not found.")
            detail.capabilities = self._capabilities_for(
                detail.provider.value, ended=detail.status != CallStatus.ACTIVE
            )
            detail.timeline = build_timeline(detail, await repo.risk_history(call_id))
        return detail

    async def list_calls(self, principal: Principal, flt: CallFilter) -> tuple[list[CallListItem], str | None]:
        async with self.db.uow() as repo:
            return await repo.list_calls(principal.id, flt)

    async def events(self, principal: Principal, call_id: str, after_seq: int) -> list[LiveEvent]:
        async with self.db.uow() as repo:
            if await repo.get_call_row(principal.id, call_id) is None:
                raise NotFound("Call not found.")
            return await repo.list_live_events(call_id, after_seq)

    async def delete_content(self, principal: Principal, call_id: str) -> None:
        async with self.db.uow() as repo:
            row = await repo.get_call_row(principal.id, call_id)
            if row is None:
                raise NotFound("Call not found.")
            if row.status == CallStatus.ACTIVE.value:
                raise Conflict("End the call before deleting its content.")
            await repo.delete_call_content(principal.id, call_id)

    async def delete_call(self, principal: Principal, call_id: str) -> None:
        async with self.db.uow() as repo:
            row = await repo.get_call_row(principal.id, call_id)
            if row is None:
                raise NotFound("Call not found.")
            if row.status == CallStatus.ACTIVE.value:
                raise Conflict("End the call before deleting it.")
            await repo.delete_call(principal.id, call_id)

    async def delete_all_content(self, principal: Principal) -> int:
        async with self.db.uow() as repo:
            return await repo.delete_all_content(principal.id)

    async def diagnostic_report(self, principal: Principal, call_id: str) -> dict[str, Any]:
        """Sanitised report: identifiers, states, timings and codes. No transcript text, names or numbers."""
        detail = await self.get_call(principal, call_id)
        latencies: dict[str, list[float]] = {}
        for turn in detail.turns:
            if turn.latency is None:
                continue
            for stage in (
                "stt_ms",
                "language_detect_ms",
                "policy_ms",
                "model_ms",
                "tts_first_audio_ms",
                "playback_start_ms",
                "total_ms",
            ):
                value = getattr(turn.latency, stage)
                if value is not None:
                    latencies.setdefault(stage, []).append(value)
        async with self.db.uow() as repo:
            events = await repo.list_live_events(call_id)
        counts: dict[str, int] = {}
        for event in events:
            counts[event.type] = counts.get(event.type, 0) + 1
        return {
            "report_version": 1,
            "call_id": detail.id,
            "trace_id": detail.trace_id,
            "provider": detail.provider.value,
            "simulated": detail.simulated,
            "status": detail.status.value,
            "final_state": detail.state.value,
            "started_at": detail.started_at.isoformat(),
            "duration_ms": detail.duration_ms,
            "languages": detail.languages,
            "language_profile": detail.language_profile,
            "risk": {
                "level": detail.risk_level.value,
                "score": detail.risk_score,
                "confidence": detail.confidence,
                "category": detail.category.value,
                "signal_codes": sorted(s.code.value for s in (detail.risk.signals if detail.risk else [])),
                "recommended_action": detail.risk.recommended_action.value if detail.risk else None,
                "policy_version": detail.risk.policy_version if detail.risk else None,
            },
            "action_taken": detail.action_taken,
            "turn_count": len(detail.turns),
            "interrupted_turns": sum(1 for t in detail.turns if t.interrupted),
            "latency_ms": {
                stage: {"p50": percentile(values, 50), "p95": percentile(values, 95), "count": len(values)}
                for stage, values in latencies.items()
            },
            "simulated_latency_stages": sorted(
                {s for t in detail.turns if t.latency for s in t.latency.simulated_stages}
            ),
            "event_counts": counts,
            "versions": detail.versions.model_dump(mode="json"),
            "provider_events": [{"type": e.event_type, "provider": e.provider} for e in detail.provider_events],
            "contains_transcript": False,
        }


__all__ = ["CallService", "RecommendedAction", "SignalKind", "SpeechPlan"]
