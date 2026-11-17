"""Deterministic conversation engine.

Pure logic: no I/O, no randomness, injectable clock. The call service feeds it caller utterances, silences and owner
actions and applies the returned decisions (persist, publish, speak, hang up). Because it is pure, every safety property
is unit-testable and a scripted call replays identically.

Safety order inside a caller turn (see docs/SAFETY_MODEL.md):
  language → deterministic signals → claims → risk assessment → deterministic decision → templated reply → validation.
No model output is consulted before the decision is made, and nothing downstream can override a refusal.
"""

import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field

from sparta.clock import Clock, SystemClock
from sparta.domain.enums import (
    ENDING_STATES,
    CallCategory,
    CallState,
    EscalationStatus,
    OwnerActionType,
    RecommendedAction,
    ResponseStyle,
    ScreeningStrictness,
    SignalCode,
    SignalSeverity,
    Speaker,
    TurnSource,
)
from sparta.domain.models import (
    CallerClaim,
    CallTurn,
    ConversationContext,
    Escalation,
    EscalationRules,
    RiskAssessment,
    RiskSignal,
    SpeechPlan,
)
from sparta.language.detector import UNKNOWN, Detection, LanguageDetector, get_detector
from sparta.language.text import mask_digits, settle_joiners, strip_invisible
from sparta.orchestrator.planner import PlannerConfig, ReplyPlanner, clean_owner_name
from sparta.orchestrator.state_machine import is_active, transition
from sparta.orchestrator.validator import OutputValidator
from sparta.risk.engine import CallRiskContext, RiskEngine
from sparta.risk.extraction import extract_claims
from sparta.risk.matchers import SignalDetector, merge_signals
from sparta.risk.policy import SafetyPolicy, load_default_policy

S = SignalCode
MAX_INPUT_CHARS = 1000
MAX_OWNER_DETECTORS = 64  # per-owner-name matcher sets kept in memory (least recently used are dropped)
PROBE_CODES = frozenset({S.ADDRESS_OR_LOCATION_REQUEST, S.OWNER_AVAILABILITY_PROBE})
INJECTION_CODES = frozenset({S.RULE_OVERRIDE_ATTEMPT, S.FALSE_OWNER_AUTHORIZATION})
# A model may add context signals but never the protected-information requests: those stay deterministic, so a
# hallucinating or manipulated model cannot end a legitimate call by "hearing" a request that was never made.
MODEL_ALLOWED_SIGNALS = frozenset(
    {
        S.SUSPICIOUS_PRIZE,
        S.ARREST_OR_LEGAL_THREAT,
        S.ACCOUNT_CLOSURE_THREAT,
        S.FAKE_KYC_URGENCY,
        S.URGENCY_PRESSURE,
        S.IMPERSONATION_BANK,
        S.IMPERSONATION_GOVERNMENT,
        S.IMPERSONATION_POLICE,
        S.IMPERSONATION_COURIER,
        S.IMPERSONATION_EMPLOYER,
        S.MALICIOUS_LINK_OR_CALLBACK,
        S.HARASSMENT_OR_ABUSE,
        S.TELEMARKETING,
    }
)
MODEL_SIGNAL_WEIGHT_CAP = 0.6
FALLBACK_KEYS = ["probe_deflect"]
_SEVERITY_ORDER = [
    SignalSeverity.INFO,
    SignalSeverity.LOW,
    SignalSeverity.MEDIUM,
    SignalSeverity.HIGH,
    SignalSeverity.CRITICAL,
]


def sanitize_text(text: str) -> str:
    """Caller text is untrusted: normalise, drop invisible and control characters, bound the length.

    Compatibility forms (one U+FDFA becomes 18 characters) are expanded *before* the length cap so the cap is real.
    Invisible characters are deleted rather than replaced by spaces, so they cannot split a keyword in two.
    """
    text = unicodedata.normalize("NFKC", text[: MAX_INPUT_CHARS * 4])[: MAX_INPUT_CHARS * 4]
    text = settle_joiners(strip_invisible(text, keep_joiners=True))
    kept: list[str] = []
    for ch in text:
        if ch.isprintable():
            kept.append(ch)
        elif ch in "\t\n\r" or unicodedata.category(ch) in {"Zs", "Zl", "Zp"}:
            kept.append(" ")
    return " ".join("".join(kept).split())[:MAX_INPUT_CHARS]


@dataclass(frozen=True)
class EngineConfig:
    """Per-call configuration snapshot (preferences and assistant profile at call start)."""

    call_id: str
    owner_name: str | None = None
    response_style: ResponseStyle = ResponseStyle.CONCISE
    speaking_rate: float = 1.0
    voice_ids: Mapping[str, str] = field(default_factory=dict)
    primary_language: str = "en-IN"
    enabled_languages: tuple[str, ...] = ("en-IN", "hi-IN", "kn-IN")
    language_mode: str = "auto"
    auto_detect_language: bool = True
    strictness: ScreeningStrictness = ScreeningStrictness.BALANCED
    escalation: EscalationRules = field(default_factory=EscalationRules)
    owner_private_markers: tuple[str, ...] = ()

    def planner_config(self) -> PlannerConfig:
        return PlannerConfig(
            owner_name=self.owner_name,
            response_style=self.response_style,
            speaking_rate=self.speaking_rate,
            voice_ids=dict(self.voice_ids),
        )


@dataclass(frozen=True)
class CallerInput:
    text: str
    source: TurnSource = TurnSource.TYPED
    language_hint: str | None = None
    hint_confidence: float | None = None
    stt_confidence: float | None = None
    previous_text: str | None = None
    previous_turn_id: str | None = None
    # Advisory signal codes from a model provider. Only context signals are accepted (see MODEL_ALLOWED_SIGNALS).
    model_signal_codes: tuple[SignalCode, ...] = ()


@dataclass
class EngineResult:
    ctx: ConversationContext
    final_state: CallState
    caller_turn: CallTurn | None = None
    assistant_turn: CallTurn | None = None
    risk: RiskAssessment | None = None
    state_path: list[CallState] = field(default_factory=list)
    language_changed: dict[str, object] | None = None
    escalation: Escalation | None = None
    end_reason: str | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    template_keys: list[str] = field(default_factory=list)
    validator_fallback: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def hangs_up(self) -> bool:
        return self.end_reason is not None


@dataclass
class _Decision:
    keys: list[str]
    targets: list[CallState]
    end_reason: str | None = None
    escalate: bool = False
    action_override: RecommendedAction | None = None
    attention: bool | None = None
    action_taken: str | None = None


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


class ConversationEngine:
    def __init__(
        self,
        *,
        policy: SafetyPolicy | None = None,
        detector: LanguageDetector | None = None,
        risk_engine: RiskEngine | None = None,
        planner: ReplyPlanner | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.policy = policy or load_default_policy()
        self.detector = detector or get_detector()
        self.risk_engine = risk_engine or RiskEngine(self.policy)
        self.planner = planner or ReplyPlanner()
        self.clock = clock or SystemClock()
        self._signal_detectors: OrderedDict[str, SignalDetector] = OrderedDict()
        self._detector_lock = threading.Lock()
        self._protected = self.policy.protected_signal_codes()
        self._supported = set(self.planner.registry.supported_codes())

    # ================================================================== helpers
    def _signals_for(self, owner_name: str | None) -> SignalDetector:
        """The matchers for one owner name. Building them takes about a second, so they are cached (bounded LRU)."""
        key = clean_owner_name(owner_name) or ""
        with self._detector_lock:
            cached = self._signal_detectors.get(key)
            if cached is not None:
                self._signal_detectors.move_to_end(key)
                return cached
        detector = SignalDetector(self.policy, self.planner.registry, owner_name=key or None)  # slow: no lock held
        with self._detector_lock:
            self._signal_detectors[key] = detector
            self._signal_detectors.move_to_end(key)
            while len(self._signal_detectors) > MAX_OWNER_DETECTORS:
                self._signal_detectors.popitem(last=False)
        return detector

    def is_warm(self, owner_name: str | None) -> bool:
        with self._detector_lock:
            return (clean_owner_name(owner_name) or "") in self._signal_detectors

    def warm(self, owner_name: str | None) -> None:
        """Build the owner's matchers now. Slow: call it from a worker thread, never from the event loop."""
        self._signals_for(owner_name)

    def _validator(self, cfg: EngineConfig) -> OutputValidator:
        return OutputValidator(cfg.owner_private_markers)

    @staticmethod
    def _move(ctx: ConversationContext, target: CallState, path: list[CallState]) -> None:
        new = transition(ctx.state, target)
        if new != ctx.state:
            ctx.state = new
            path.append(new)

    def _forced_language(self, cfg: EngineConfig) -> str | None:
        if cfg.language_mode != "auto":
            return cfg.language_mode
        return None if cfg.auto_detect_language else cfg.primary_language

    def _initial_language(self, cfg: EngineConfig) -> str:
        forced = self._forced_language(cfg)
        lang = forced or cfg.primary_language
        return lang if lang in self._supported else "en-IN"

    def _say(
        self,
        ctx: ConversationContext,
        cfg: EngineConfig,
        keys: list[str],
        language: str,
        result: EngineResult,
    ) -> tuple[SpeechPlan, list[str]]:
        """Render template keys, validate, and fall back to a minimal deflection if validation ever fails."""
        planner_cfg = cfg.planner_config()
        plan = self.planner.render_keys(keys, language, planner_cfg)
        verdict = self._validator(cfg).validate(
            plan,
            owner_name=cfg.owner_name,
            require_ai_disclosure="disclosure" in keys,
            detector=self._signals_for(cfg.owner_name),
        )
        if not verdict.ok:
            result.validator_fallback = True
            result.notes.append("validator_fallback:" + ",".join(verdict.violations))
            keys = list(FALLBACK_KEYS)
            plan = self.planner.render_keys(keys, language, planner_cfg)
        return plan, keys

    def _assistant_turn(
        self, ctx: ConversationContext, cfg: EngineConfig, plan: SpeechPlan, keys: list[str], language: str
    ) -> CallTurn:
        ctx.seq += 1
        english = None
        if not language.startswith("en"):
            english = self.planner.english_equivalent(keys, cfg.planner_config())
        ctx.assistant_speaking = True
        turn_id = f"turn_{ctx.seq}"
        ctx.speaking_turn_id = turn_id
        return CallTurn(
            id=turn_id,
            call_id=cfg.call_id,
            seq=ctx.seq,
            speaker=Speaker.ASSISTANT,
            text=plan.text,
            transliteration=plan.transliteration,
            translation=english,
            language=plan.locale,
            language_confidence=1.0,
            is_final=True,
            source=TurnSource.ASSISTANT,
            state_after=ctx.state,
            created_at=self.clock.now(),
            speech=plan,
        )

    def _resolve_language(self, ctx: ConversationContext, cfg: EngineConfig, det: Detection) -> str:
        forced = self._forced_language(cfg)
        enabled = set(cfg.enabled_languages) & self._supported
        if forced:
            return forced if forced in self._supported else cfg.primary_language
        if det.supported and det.language in enabled and not det.uncertain:
            return det.language
        return ctx.language

    @staticmethod
    def _base_language(profile: str) -> str | None:
        return {"english": "en", "hindi": "hi", "hinglish": "hi", "kannada": "kn", "kanglish": "kn"}.get(profile)

    def _call_profile(self, ctx: ConversationContext, det: Detection) -> str | None:
        if det.profile == "unknown":
            return ctx.language_profile
        bases = {b for p in ctx.turn_languages if (b := self._base_language(p))}
        if len(bases) >= 2:
            return "mixed"
        return det.profile

    # ================================================================== lifecycle
    def start(self, cfg: EngineConfig) -> EngineResult:
        ctx = ConversationContext(language=self._initial_language(cfg), language_mode=cfg.language_mode)
        # `detected_languages` lists what the CALLER spoke. The assistant's opening language is not a detection.
        ctx.detected_languages = []
        result = EngineResult(ctx=ctx, final_state=ctx.state)
        t0 = time.perf_counter()
        self._move(ctx, CallState.DISCLOSURE, result.state_path)
        plan, keys = self._say(ctx, cfg, ["disclosure"], ctx.language, result)
        turn = self._assistant_turn(ctx, cfg, plan, keys, ctx.language)
        self._move(ctx, CallState.IDENTIFY_CALLER, result.state_path)
        turn.state_after = ctx.state
        ctx.action_taken = "introduced_as_ai_assistant"
        result.assistant_turn = turn
        result.template_keys = keys
        result.final_state = ctx.state
        result.timings_ms["plan_ms"] = _ms(t0)
        return result

    def complete(self, ctx_in: ConversationContext, reason: str) -> ConversationContext:
        ctx = ctx_in.model_copy(deep=True)
        if ctx.state not in (CallState.COMPLETED, CallState.FAILED):
            ctx.state = transition(ctx.state, CallState.COMPLETED)
        ctx.ended_reason = ctx.ended_reason or reason
        ctx.assistant_speaking = False
        return ctx

    def fail(self, ctx_in: ConversationContext, reason: str) -> ConversationContext:
        ctx = ctx_in.model_copy(deep=True)
        if ctx.state not in (CallState.COMPLETED, CallState.FAILED):
            ctx.state = transition(ctx.state, CallState.FAILED)
        ctx.ended_reason = ctx.ended_reason or reason
        ctx.assistant_speaking = False
        return ctx

    @staticmethod
    def accepts_caller_input(ctx: ConversationContext) -> bool:
        return ctx.ended_reason is None and (is_active(ctx.state) or ctx.state is CallState.OWNER_TAKEOVER)

    def detect_signals(
        self,
        cfg: EngineConfig,
        text: str,
        turn_id: str,
        *,
        previous_text: str | None = None,
        previous_turn_id: str | None = None,
        known: frozenset[SignalCode] = frozenset(),
    ) -> list[RiskSignal]:
        """Deterministic signals of one caller utterance, including phrases split across the previous utterance.

        Pure: nothing about a call changes. The evaluation harness also uses it to measure what the rules recognise in
        turns the assistant never heard because it had already hung up.
        """
        detector = self._signals_for(cfg.owner_name)
        new = detector.detect(text, turn_id)
        if previous_text:
            seen = known | {s.code for s in new}
            for s in detector.detect(f"{sanitize_text(previous_text)}. {text}", turn_id):
                if s.code not in seen:
                    s.evidence_turn_ids = [i for i in (previous_turn_id, turn_id) if i]
                    new.append(s)
        return new

    # ================================================================== caller turn
    def on_caller_turn(self, ctx_in: ConversationContext, cfg: EngineConfig, inp: CallerInput) -> EngineResult:
        ctx = ctx_in.model_copy(deep=True)
        result = EngineResult(ctx=ctx, final_state=ctx.state)
        if not self.accepts_caller_input(ctx):
            result.notes.append("call_not_active")
            return result

        text = sanitize_text(inp.text)
        takeover = ctx.state is CallState.OWNER_TAKEOVER
        ctx.seq += 1
        turn_id = f"turn_{ctx.seq}"
        ctx.silence_count = 0
        ctx.caller_turns += 1
        ctx.last_caller_turn_id = turn_id
        ctx.assistant_speaking = False
        ctx.speaking_turn_id = None

        # 1. language ---------------------------------------------------------------------------------------
        t = time.perf_counter()
        det = self.detector.detect(
            text,
            hint=inp.language_hint,
            hint_confidence=inp.hint_confidence,
            forced=self._forced_language(cfg),
        )
        reply_lang = self._resolve_language(ctx, cfg, det)
        result.timings_ms["language_detect_ms"] = _ms(t)
        if det.language != UNKNOWN:
            ctx.turn_languages.append(det.profile)
        for code in det.languages:
            if code not in ctx.detected_languages:
                ctx.detected_languages.append(code)
        if reply_lang != ctx.language:
            result.language_changed = {
                "from": ctx.language,
                "to": reply_lang,
                "profile": det.profile,
                "confidence": det.confidence,
            }
            ctx.language = reply_lang
        ctx.language_profile = self._call_profile(ctx, det)

        # 2. deterministic signals + claims + risk -------------------------------------------------------------
        t = time.perf_counter()
        new = self.detect_signals(
            cfg,
            text,
            turn_id,
            previous_text=inp.previous_text,
            previous_turn_id=inp.previous_turn_id,
            known=frozenset(s.code for s in ctx.signals),
        )
        have = {s.code for s in new} | {s.code for s in ctx.signals}
        for code in inp.model_signal_codes:
            if code in MODEL_ALLOWED_SIGNALS and code not in have:
                definition = self.policy.signals[code]
                new.append(
                    RiskSignal(
                        code=code,
                        kind=definition.kind,
                        severity=min(definition.severity, SignalSeverity.HIGH, key=_SEVERITY_ORDER.index),
                        weight=min(definition.weight, MODEL_SIGNAL_WEIGHT_CAP),
                        evidence_turn_ids=[turn_id],
                        description=f"{definition.description} (model-assisted)",
                    )
                )
        ctx.signals = merge_signals(ctx.signals, new)
        claims = extract_claims(text)
        name, org, role = claims.merged_into(
            ctx.caller_claim.name, ctx.caller_claim.organization, ctx.caller_claim.role
        )
        ctx.caller_claim = CallerClaim(name=name, organization=org, role=role)
        if claims.purpose_phrase and not ctx.purpose:
            ctx.purpose = claims.purpose_phrase
        ctx.low_confidence_streak = (
            ctx.low_confidence_streak + 1 if (inp.stt_confidence is not None and inp.stt_confidence < 0.55) else 0
        )
        risk = self.risk_engine.assess(
            CallRiskContext(
                call_id=cfg.call_id,
                caller_turns=ctx.caller_turns,
                detected_languages=list(ctx.detected_languages),
                language_profile=ctx.language_profile,
                language_uncertain=det.uncertain,
                min_stt_confidence=inp.stt_confidence,
                caller_claim=ctx.caller_claim,
                stated_purpose=ctx.purpose,
                strictness=cfg.strictness,
            ),
            ctx.signals,
            now=self.clock.now(),
        )
        result.timings_ms["policy_ms"] = _ms(t)

        caller_turn = CallTurn(
            id=turn_id,
            call_id=cfg.call_id,
            seq=ctx.seq,
            speaker=Speaker.CALLER,
            text=text,
            language=det.language,
            language_confidence=det.confidence,
            language_profile=det.profile,
            segments=det.segments,
            is_final=True,
            confidence=inp.stt_confidence,
            source=inp.source,
            created_at=self.clock.now(),
        )
        result.caller_turn = caller_turn

        # While the owner is on the line the assistant listens and keeps assessing, but does not speak.
        if takeover:
            ctx.risk = risk
            caller_turn.state_after = ctx.state
            result.risk = risk
            result.notes.append("owner_on_line")
            return result

        # 3. deterministic decision -------------------------------------------------------------------------
        t = time.perf_counter()
        self._move(ctx, CallState.ASSESSING, result.state_path)
        decision = self._decide(ctx, cfg, risk, new, det, inp, text)
        if decision.action_override is not None or decision.attention is not None:
            risk = risk.model_copy(
                update={
                    "recommended_action": decision.action_override or risk.recommended_action,
                    "requires_owner_attention": (
                        risk.requires_owner_attention if decision.attention is None else decision.attention
                    ),
                }
            )
        for target in decision.targets:
            self._move(ctx, target, result.state_path)
        if decision.escalate:
            result.escalation = self._new_escalation(ctx, cfg, risk, text)
            ctx.escalation_id = result.escalation.id
            ctx.escalated_at = result.escalation.created_at
        ctx.risk = risk
        if decision.action_taken:
            ctx.action_taken = decision.action_taken
        result.timings_ms["decision_ms"] = _ms(t)

        # 4. reply -------------------------------------------------------------------------------------------
        t = time.perf_counter()
        plan, keys = self._say(ctx, cfg, decision.keys, reply_lang, result)
        turn = self._assistant_turn(ctx, cfg, plan, keys, reply_lang)
        result.timings_ms["plan_ms"] = _ms(t)

        if decision.end_reason:
            ctx.ended_reason = decision.end_reason
        turn.state_after = ctx.state
        caller_turn.state_after = ctx.state
        result.assistant_turn = turn
        result.template_keys = keys
        result.risk = risk
        result.end_reason = decision.end_reason
        result.final_state = ctx.state
        return result

    # ------------------------------------------------------------------ decision table
    def _decide(
        self,
        ctx: ConversationContext,
        cfg: EngineConfig,
        risk: RiskAssessment,
        new: list[RiskSignal],
        det: Detection,
        inp: CallerInput,
        text: str,
    ) -> _Decision:
        limits = self.policy.limits
        ever = {s.code for s in ctx.signals}
        new_codes = {s.code for s in new}
        new_protected = bool(new_codes & self._protected)
        any_protected = bool(ever & self._protected)
        injection = bool(ever & INJECTION_CODES)
        action = risk.recommended_action
        S_ = CallState

        # (1) refuse and end: protected request, injection, payment/threat patterns ----------------------------
        if action is RecommendedAction.REFUSE_AND_END:
            refusal = "injection_refuse" if injection else ("refuse_sensitive" if any_protected else None)
            if cfg.escalation.auto_end_high_risk:
                keys = ([refusal] if refusal else []) + ["end_scam"]
                targets = ([S_.REFUSE_SENSITIVE_REQUEST] if refusal else []) + [S_.END_SPAM]
                return _Decision(
                    keys,
                    targets,
                    end_reason="refused_and_ended" if refusal else "high_risk_ended",
                    action_taken="refused_and_ended" if refusal else "ended_high_risk_call",
                )
            ctx.refusals += 1
            return _Decision(
                [refusal or "probe_deflect"],
                [S_.REFUSE_SENSITIVE_REQUEST, S_.SAFE_CONTINUE],
                attention=True,
                action_taken="refused",
            )

        # (2) unwanted calls: telemarketing, abuse ----------------------------------------------------------------
        if action is RecommendedAction.END_SPAM:
            abusive = S.HARASSMENT_OR_ABUSE in ever
            return _Decision(
                ["end_scam" if abusive else "end_spam"],
                [S_.END_SPAM],
                end_reason="abusive_caller" if abusive else "spam_ended",
                action_taken="ended_unwanted_call",
            )

        # (3) legitimate or urgent: alert the owner, never hand anything over ---------------------------------------
        if action is RecommendedAction.ESCALATE_TO_OWNER:
            alert = risk.category in cfg.escalation.escalate_categories
            if alert and not ctx.escalation_closed:
                first = ctx.escalation_id is None
                declining = (
                    (["decline_personal"] if new_codes <= PROBE_CODES | {S.URGENCY_PRESSURE} else ["refuse_sensitive"])
                    if new_protected
                    else []
                )
                keys = declining + (["escalate_hold"] if first else ["escalate_waiting"])
                targets = ([S_.REFUSE_SENSITIVE_REQUEST] if new_protected else []) + [S_.ESCALATE]
                return _Decision(keys, targets, escalate=first, attention=True, action_taken="escalated_to_owner")
            if not alert:
                return self._take_message(ctx, attention=True)
            if new_protected:  # the owner already decided, but a protected request is still never left unanswered
                keys = ["decline_personal"] if new_codes <= PROBE_CODES | {S.URGENCY_PRESSURE} else ["refuse_sensitive"]
                return _Decision(
                    keys, [S_.REFUSE_SENSITIVE_REQUEST, S_.SAFE_CONTINUE], attention=True, action_taken="refused"
                )
            # The owner already chose (or their window expired): carry on collecting details below, no second alert.

        # (4) owner probes: deflect once, then end -------------------------------------------------------------------
        if new_codes & PROBE_CODES:
            ctx.refusals += 1
            if ctx.refusals > limits.max_probe_deflections:
                return _Decision(
                    ["probe_deflect", "end_scam"],
                    [S_.REFUSE_SENSITIVE_REQUEST, S_.END_SPAM],
                    end_reason="refused_and_ended",
                    action_override=RecommendedAction.REFUSE_AND_END,
                    attention=False,
                    action_taken="refused_and_ended",
                )
            return _Decision(
                ["probe_deflect"],
                [S_.REFUSE_SENSITIVE_REQUEST, S_.SAFE_CONTINUE],
                action_taken="deflected_private_question",
            )

        # (5) a language Sparta cannot speak yet ----------------------------------------------------------------------
        if not det.supported and not det.uncertain and det.language != UNKNOWN and not new:
            tries = ctx.clarify_attempts.get("language", 0)
            if tries < limits.max_clarify_attempts:
                ctx.clarify_attempts["language"] = tries + 1
                return _Decision(["unsupported_language"], [S_.CLARIFY], action_taken="asked_to_switch_language")
            return _Decision(
                ["farewell_message"],
                [S_.SAFE_CONTINUE],
                end_reason="unsupported_language",
                action_override=RecommendedAction.HUMAN_REVIEW,
                attention=True,
                action_taken="took_message_unsupported_language",
            )

        # (6) transcript too poor to act on ---------------------------------------------------------------------
        poor_audio = (inp.stt_confidence is not None and inp.stt_confidence < 0.55) or (
            det.language == UNKNOWN and det.token_count > 0
        )
        if poor_audio and not new and ctx.clarify_attempts.get("repeat", 0) < limits.max_clarify_attempts:
            ctx.clarify_attempts["repeat"] = ctx.clarify_attempts.get("repeat", 0) + 1
            return _Decision(["clarify_repeat"], [S_.CLARIFY], action_taken="asked_to_repeat")

        # (7) collect who/why (max two attempts per field), then take a message -------------------------------------
        missing = self._next_missing(ctx, risk)
        if missing:
            ctx.clarify_attempts[missing] = ctx.clarify_attempts.get(missing, 0) + 1
            state = S_.IDENTIFY_PURPOSE if missing == "purpose" else S_.IDENTIFY_CALLER
            return _Decision(
                [f"ask_{'org' if missing == 'organization' else missing}"],
                [state],
                action_taken=f"asked_for_{missing}",
            )
        return self._take_message(ctx, attention=risk.requires_owner_attention)

    @staticmethod
    def _take_message(ctx: ConversationContext, attention: bool) -> _Decision:
        ctx.safe_turns += 1
        if ctx.safe_turns == 1:
            return _Decision(
                ["take_message"], [CallState.SAFE_CONTINUE], attention=attention, action_taken="took_message"
            )
        if ctx.safe_turns == 2:
            return _Decision(
                ["safe_continue"], [CallState.SAFE_CONTINUE], attention=attention, action_taken="took_message"
            )
        return _Decision(
            ["farewell_message"],
            [CallState.SAFE_CONTINUE],
            end_reason="message_taken",
            attention=attention,
            action_taken="took_message",
        )

    def _next_missing(self, ctx: ConversationContext, risk: RiskAssessment) -> str | None:
        limit = self.policy.limits.max_clarify_attempts
        tries = ctx.clarify_attempts
        claim = ctx.caller_claim
        if not claim.name and tries.get("name", 0) < limit:
            return "name"
        if not (ctx.purpose or risk.purpose) and tries.get("purpose", 0) < limit:
            return "purpose"
        vague = risk.category in (CallCategory.UNKNOWN, CallCategory.TELEMARKETING)
        if not claim.organization and vague and tries.get("organization", 0) < 1 and ctx.caller_turns <= 3:
            return "organization"
        return None

    def _new_escalation(
        self, ctx: ConversationContext, cfg: EngineConfig, risk: RiskAssessment, text: str
    ) -> Escalation:
        return Escalation(
            id=f"esc_{cfg.call_id[-8:]}_{ctx.seq}",
            call_id=cfg.call_id,
            reason=risk.purpose or "Possible legitimate call",
            status=EscalationStatus.REQUESTED,
            created_at=self.clock.now(),
            important_lines=[mask_digits(text)[:160]],
        )

    # ================================================================== silence / owner / timeouts
    def on_silence(self, ctx_in: ConversationContext, cfg: EngineConfig) -> EngineResult:
        ctx = ctx_in.model_copy(deep=True)
        result = EngineResult(ctx=ctx, final_state=ctx.state)
        if not self.accepts_caller_input(ctx) or ctx.state is CallState.OWNER_TAKEOVER:
            result.notes.append("silence_ignored")
            return result
        ctx.assistant_speaking = False
        ctx.silence_count += 1
        closing = ctx.silence_count >= 2
        if closing:
            self._move(ctx, CallState.END_SILENCE, result.state_path)
            ctx.ended_reason = "silence"
            ctx.action_taken = "ended_after_silence"
        else:
            ctx.action_taken = "reprompted_after_silence"
        meaningful = bool(ctx.signals) or bool(ctx.caller_claim.name) or bool(ctx.purpose)
        risk = self.risk_engine.assess(
            CallRiskContext(
                call_id=cfg.call_id,
                caller_turns=ctx.caller_turns,
                detected_languages=list(ctx.detected_languages),
                language_profile=ctx.language_profile,
                caller_claim=ctx.caller_claim,
                stated_purpose=ctx.purpose,
                strictness=cfg.strictness,
                silent=closing and not meaningful,
            ),
            ctx.signals,
            now=self.clock.now(),
        )
        ctx.risk = risk
        key = "close_silence" if closing else "reprompt_silence"
        plan, keys = self._say(ctx, cfg, [key], ctx.language, result)
        turn = self._assistant_turn(ctx, cfg, plan, keys, ctx.language)
        turn.state_after = ctx.state
        result.assistant_turn = turn
        result.template_keys = keys
        result.risk = risk
        result.end_reason = "silence" if closing else None
        result.final_state = ctx.state
        return result

    def on_owner_action(self, ctx_in: ConversationContext, cfg: EngineConfig, action: OwnerActionType) -> EngineResult:
        ctx = ctx_in.model_copy(deep=True)
        result = EngineResult(ctx=ctx, final_state=ctx.state)
        if ctx.ended_reason is not None or not (is_active(ctx.state) or ctx.state is CallState.OWNER_TAKEOVER):
            result.notes.append("call_not_active")
            return result
        keys: list[str]
        if action is OwnerActionType.TAKEOVER:
            self._move(ctx, CallState.OWNER_TAKEOVER, result.state_path)
            ctx.owner_decision = OwnerActionType.TAKEOVER
            ctx.action_taken = "owner_took_over"
            keys = ["owner_takeover"]
        elif action is OwnerActionType.CONTINUE:
            self._move(ctx, CallState.IDENTIFY_PURPOSE, result.state_path)
            ctx.owner_decision = OwnerActionType.CONTINUE
            ctx.escalation_closed = True
            ctx.safe_turns = 0
            ctx.action_taken = "owner_let_sparta_continue"
            keys = ["owner_continue"]
        elif action in (OwnerActionType.END, OwnerActionType.BLOCK):
            ctx.owner_decision = action
            ctx.ended_reason = "blocked_by_owner" if action is OwnerActionType.BLOCK else "owner_ended"
            ctx.action_taken = "owner_blocked_caller" if action is OwnerActionType.BLOCK else "owner_ended_call"
            keys = ["end_scam" if action is OwnerActionType.BLOCK else "owner_ended"]
            result.end_reason = ctx.ended_reason
        else:
            result.notes.append("no_engine_effect")
            return result
        plan, keys = self._say(ctx, cfg, keys, ctx.language, result)
        turn = self._assistant_turn(ctx, cfg, plan, keys, ctx.language)
        turn.state_after = ctx.state
        result.assistant_turn = turn
        result.template_keys = keys
        result.risk = ctx.risk
        result.final_state = ctx.state
        return result

    def on_owner_timeout(self, ctx_in: ConversationContext, cfg: EngineConfig) -> EngineResult:
        """The owner did not respond to an escalation in time: take a message instead of leaving the caller hanging."""
        ctx = ctx_in.model_copy(deep=True)
        result = EngineResult(ctx=ctx, final_state=ctx.state)
        if ctx.state is not CallState.ESCALATE or ctx.ended_reason is not None:
            result.notes.append("not_waiting_for_owner")
            return result
        self._move(ctx, CallState.SAFE_CONTINUE, result.state_path)
        ctx.escalation_closed = True
        ctx.safe_turns = 1
        ctx.action_taken = "owner_unavailable_took_message"
        plan, keys = self._say(ctx, cfg, ["take_message"], ctx.language, result)
        turn = self._assistant_turn(ctx, cfg, plan, keys, ctx.language)
        turn.state_after = ctx.state
        result.assistant_turn = turn
        result.template_keys = keys
        result.risk = ctx.risk
        result.final_state = ctx.state
        return result

    def on_limit_reached(self, ctx_in: ConversationContext, cfg: EngineConfig, reason: str) -> EngineResult:
        """Maximum call duration reached: say goodbye and end."""
        ctx = ctx_in.model_copy(deep=True)
        result = EngineResult(ctx=ctx, final_state=ctx.state)
        if ctx.ended_reason is not None or ctx.state in ENDING_STATES:
            result.notes.append("already_ending")
            return result
        ctx.ended_reason = reason
        ctx.action_taken = "ended_at_duration_limit"
        plan, keys = self._say(ctx, cfg, ["call_limit"], ctx.language, result)
        turn = self._assistant_turn(ctx, cfg, plan, keys, ctx.language)
        turn.state_after = ctx.state
        result.assistant_turn = turn
        result.template_keys = keys
        result.risk = ctx.risk
        result.end_reason = reason
        result.final_state = ctx.state
        return result


def risk_changed(old: RiskAssessment | None, new: RiskAssessment | None) -> bool:
    if new is None:
        return False
    if old is None:
        return True
    return (
        old.risk_level != new.risk_level
        or old.recommended_action != new.recommended_action
        or old.category != new.category
        or abs(old.risk_score - new.risk_score) > 1e-9
        or {s.code for s in old.signals} != {s.code for s in new.signals}
        or old.requires_owner_attention != new.requires_owner_attention
    )


__all__ = [
    "CallerInput",
    "ConversationEngine",
    "EngineConfig",
    "EngineResult",
    "risk_changed",
    "sanitize_text",
]
