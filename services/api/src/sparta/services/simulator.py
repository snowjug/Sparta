"""Simulator Lab service: curated and custom scenarios, server-side autoplay and deterministic replay.

Autoplay drives a scripted caller in real time so the owner can watch a call unfold over the live socket. Replay runs the
same script inside a throw-away container (in-memory database, virtual clock, deterministic ids) so it is repeatable
and can never touch the owner's calls: the same input yields the same checksum.
"""

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Coroutine
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any, TypeVar

from sparta.clock import Clock, VirtualClock
from sparta.config import Settings
from sparta.db.session import Database
from sparta.domain.enums import CallStatus, TurnSource
from sparta.domain.models import CallDetail, LiveEvent
from sparta.providers.stt.simulator import partial_events
from sparta.services.calls import CallService
from sparta.services.dto import CreateCallRequest, Principal
from sparta.services.errors import Conflict, InvalidInput, NotFound
from sparta.services.ids import IdFactory
from sparta.services.providers import ProviderSet
from sparta.services.views import (
    CreateScenarioRequest,
    ProviderOption,
    ReplayRequest,
    ReplayResult,
    ScenarioDetail,
    ScenarioSummary,
    ScenarioTurn,
)

if TYPE_CHECKING:
    from sparta.services.container import Container

log = logging.getLogger("sparta.simulator")
T = TypeVar("T")

CURATED_PACKAGE = "sparta.simulator.scenarios"
VOLATILE_KEYS = frozenset({"latency", "trace_id", "metrics", "interruption_ms"})
CHECKSUM_COVERS = (
    "SHA-256 over the call (turns, languages, risk and evidence, escalations, owner actions, summary, timeline) and its "
    "ordered event log, using virtual timestamps. Wall-clock measurements (latency breakdowns, interruption timings, "
    "aggregate metrics) and the trace id are excluded because they differ between runs by nature."
)
PARTIAL_STEP_S = 0.12
MAX_CUSTOM_SCENARIOS = 50
LANGUAGE_TAG = re.compile(r"[a-z]{2,3}(-[A-Z][A-Za-z]{1,3})?")


@lru_cache
def curated_scenarios() -> dict[str, ScenarioDetail]:
    raw = json.loads(resources.files(CURATED_PACKAGE).joinpath("curated.json").read_text(encoding="utf-8"))
    out: dict[str, ScenarioDetail] = {}
    for item in raw:
        turns = [ScenarioTurn.model_validate(t) for t in item["turns"]]
        out[item["id"]] = ScenarioDetail(
            id=item["id"],
            title=item["title"],
            description=item.get("description", ""),
            language_profile=item["language_profile"],
            languages=item.get("languages", []),
            tags=item.get("tags", []),
            turn_count=len(turns),
            expected_action=item.get("expected_action"),
            custom=False,
            caller_number=item.get("caller_number"),
            caller_label=item.get("caller_label"),
            turns=turns,
        )
    return out


def _summary(detail: ScenarioDetail) -> ScenarioSummary:
    return ScenarioSummary.model_validate(detail.model_dump(exclude={"turns", "caller_number", "caller_label"}))


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def behaviour_checksum(call: CallDetail, events: list[LiveEvent]) -> str:
    payload = {
        "call": _strip_volatile(call.model_dump(mode="json")),
        "events": [_strip_volatile(e.model_dump(mode="json")) for e in events],
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ReplayDriver:
    """Runs a scripted scenario in virtual time. Time advances only by amounts the script or the simulation defines
    (gaps, the assistant's speaking time, simulated network latency), never by how long the host took."""

    def __init__(self, container: "Container", principal: Principal) -> None:
        assert isinstance(container.clock, VirtualClock)
        self.c = container
        self.clock: VirtualClock = container.clock
        self.p = principal

    async def _idle(self, call_id: str, rounds: int = 1500) -> None:
        stable = 0
        for _ in range(rounds):
            await asyncio.sleep(0.004)
            busy = self.c.calls.is_busy(call_id)
            stable = 0 if busy else stable + 1
            if stable >= 4:
                return
        raise TimeoutError("the replayed call did not go quiet")

    async def _advance(self, call_id: str, seconds: float) -> None:
        if seconds > 0:
            await self.clock.advance(seconds)
        await self._idle(call_id)

    async def _finish_speaking(self, call_id: str) -> None:
        remaining = self.c.calls.speaking_remaining_s(call_id)
        if remaining:
            await self._advance(call_id, remaining)
        else:
            await self._idle(call_id)

    async def _drive(self, coro: Coroutine[Any, Any, T]) -> T:
        """Await ``coro`` while granting exactly the simulated network latency it asks the virtual clock for."""
        task = asyncio.ensure_future(coro)
        for _ in range(40_000):
            if task.done():
                break
            delta = self.clock.next_delta("net")
            if delta is not None:
                await self.clock.advance(delta)
            else:
                await asyncio.sleep(0.002)
        else:
            task.cancel()
            raise TimeoutError("the replayed step did not finish")
        return await task

    async def run(
        self, scenario: ScenarioDetail, language_mode: str, network_profile: str
    ) -> tuple[CallDetail, list[LiveEvent]]:
        calls = self.c.calls
        created = await self._drive(
            calls.create_call(
                self.p,
                CreateCallRequest(
                    caller_number=scenario.caller_number,
                    caller_label=scenario.caller_label,
                    language_mode=language_mode,
                    network_profile=network_profile,
                    scenario_id=scenario.id,
                    silence_timers="off",
                ),
                simulator=True,
            )
        )
        call_id = created.id
        for turn in scenario.turns:
            if calls.speaking_remaining_s(call_id) is None:
                break  # the call ended: nothing left to play
            if turn.kind == "speech" and turn.barge_in:
                await self._advance(call_id, turn.delay_ms / 1000.0)
            else:
                await self._finish_speaking(call_id)
                await self._advance(call_id, turn.delay_ms / 1000.0)
            if calls.speaking_remaining_s(call_id) is None:
                break
            try:
                if turn.kind == "silence":
                    await self._drive(calls.silence(self.p, call_id))
                else:
                    for partial in partial_events(turn.text, turn.language)[:-1]:
                        await calls.submit_partial(self.p, call_id, partial.text, turn.language)
                    await self._drive(
                        calls.submit_turn(
                            self.p,
                            call_id,
                            turn.text,
                            source=TurnSource.SCRIPTED,
                            language_hint=turn.language,
                            stt_confidence=turn.stt_confidence,
                        )
                    )
            except Conflict:
                break
        if calls.speaking_remaining_s(call_id) is not None:
            await self._finish_speaking(call_id)
        return await calls.get_call(self.p, call_id), await calls.events(self.p, call_id, 0)


class SimulatorService:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        clock: Clock,
        ids: IdFactory,
        calls: CallService,
        providers: ProviderSet,
        replay_factory: Callable[[], Awaitable["Container"]],
    ) -> None:
        self.settings, self.db, self.clock, self.ids = settings, db, clock, ids
        self.calls, self.providers, self._replay_factory = calls, providers, replay_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._replay_slots = asyncio.Semaphore(2)
        calls.finalize_hooks.append(self._on_call_finished)

    # ======================================================================================== scenarios
    async def _custom(self, principal: Principal) -> list[ScenarioDetail]:
        async with self.db.uow() as repo:
            rows = await repo.list_scenarios(principal.id)
        out: list[ScenarioDetail] = []
        for data in rows:
            turns = [ScenarioTurn.model_validate(t) for t in data.get("turns", [])]
            out.append(
                ScenarioDetail(
                    id=data["id"],
                    title=data.get("title", "Custom scenario"),
                    description=data.get("description", ""),
                    language_profile=data.get("language_profile", "mixed"),
                    languages=sorted({t.language for t in turns if t.language}),
                    tags=["custom"],
                    turn_count=len(turns),
                    expected_action=data.get("expected_action"),
                    custom=True,
                    turns=turns,
                )
            )
        return out

    async def list_scenarios(self, principal: Principal) -> list[ScenarioSummary]:
        return [_summary(s) for s in [*curated_scenarios().values(), *await self._custom(principal)]]

    async def get_scenario(self, principal: Principal, scenario_id: str) -> ScenarioDetail:
        curated = curated_scenarios().get(scenario_id)
        if curated is not None:
            return curated
        async with self.db.uow() as repo:
            data = await repo.get_scenario(principal.id, scenario_id)
        if data is None:
            raise NotFound("Scenario not found.")
        turns = [ScenarioTurn.model_validate(t) for t in data.get("turns", [])]
        return ScenarioDetail(
            id=data["id"],
            title=data.get("title", "Custom scenario"),
            description=data.get("description", ""),
            language_profile=data.get("language_profile", "mixed"),
            languages=sorted({t.language for t in turns if t.language}),
            tags=["custom"],
            turn_count=len(turns),
            expected_action=data.get("expected_action"),
            custom=True,
            turns=turns,
        )

    async def create_scenario(self, principal: Principal, req: CreateScenarioRequest) -> ScenarioSummary:
        for turn in req.turns:
            if turn.language and not LANGUAGE_TAG.fullmatch(turn.language):
                raise InvalidInput(f"'{turn.language}' is not a valid language tag (for example hi-IN).")
        now = self.clock.now()
        async with self.db.uow() as repo:
            await repo.ensure_user(principal.id, principal.display_name or principal.id, now)
            if len(await repo.list_scenarios(principal.id)) >= MAX_CUSTOM_SCENARIOS:
                raise Conflict(f"You can keep up to {MAX_CUSTOM_SCENARIOS} custom scenarios. Delete one first.")
            scenario_id = self.ids.new("scn")
            await repo.save_scenario(
                principal.id,
                scenario_id,
                {
                    "title": req.title,
                    "description": req.description,
                    "language_profile": req.language_profile,
                    "expected_action": req.expected_action,
                    "turns": [t.model_dump(mode="json") for t in req.turns],
                },
                now,
            )
        return _summary(await self.get_scenario(principal, scenario_id))

    # ========================================================================================= providers
    def providers_list(self) -> list[ProviderOption]:
        s = self.settings
        azure_speech_ready = bool(s.azure_speech_key and s.azure_speech_region)
        azure_speech_reason = (
            "" if azure_speech_ready else "Set SPARTA_AZURE_SPEECH_KEY and SPARTA_AZURE_SPEECH_REGION."
        )
        openai_ready = bool(s.azure_openai_endpoint and s.azure_openai_key and s.azure_openai_deployment)
        acs_ready = bool(s.acs_connection_string and s.acs_callback_base_url)
        return [
            ProviderOption(
                id="telephony:simulator",
                kind="telephony",
                active=s.telephony_provider == "simulator",
                available=True,
                simulated=True,
                label="Built-in telephony simulator",
                reason="No phone call or audio is involved; takeover is a labelled simulation.",
            ),
            ProviderOption(
                id="telephony:azure",
                kind="telephony",
                active=s.telephony_provider == "azure",
                available=acs_ready,
                simulated=False,
                label="Azure Communication Services",
                reason=""
                if acs_ready
                else "Needs SPARTA_ACS_CONNECTION_STRING and a public HTTPS SPARTA_ACS_CALLBACK_BASE_URL.",
            ),
            ProviderOption(
                id="stt:simulator",
                kind="stt",
                active=s.stt_provider == "simulator",
                available=True,
                simulated=True,
                label="Simulated speech-to-text",
                reason="Cannot transcribe audio: use typed turns, the browser microphone, or a transcript hint.",
            ),
            ProviderOption(
                id="stt:azure",
                kind="stt",
                active=s.stt_provider == "azure",
                available=azure_speech_ready,
                simulated=False,
                label="Azure AI Speech (fast transcription)",
                reason=azure_speech_reason,
            ),
            ProviderOption(
                id="tts:simulator",
                kind="tts",
                active=s.tts_provider == "simulator",
                available=True,
                simulated=True,
                label="Simulated text-to-speech",
                reason="Timing only: no audio is produced.",
            ),
            ProviderOption(
                id="tts:azure",
                kind="tts",
                active=s.tts_provider == "azure",
                available=azure_speech_ready,
                simulated=False,
                label="Azure AI Speech (neural voices)",
                reason=azure_speech_reason,
            ),
            ProviderOption(
                id="llm:rules",
                kind="llm",
                active=s.llm_provider == "rules",
                available=True,
                simulated=False,
                label="Deterministic rules (no model)",
                reason="Every decision and reply comes from the reviewed policy.",
            ),
            ProviderOption(
                id="llm:azure_openai",
                kind="llm",
                active=s.llm_provider == "azure_openai",
                available=openai_ready,
                simulated=False,
                label="Azure OpenAI (advisory signals, summaries)",
                reason="" if openai_ready else "Set SPARTA_AZURE_OPENAI_ENDPOINT, _KEY and _DEPLOYMENT.",
            ),
        ]

    # ===================================================================================== create / play
    async def create_call(self, principal: Principal, req: CreateCallRequest) -> CallDetail:
        scenario = await self.get_scenario(principal, req.scenario_id) if req.scenario_id else None
        if req.autoplay and scenario is None:
            raise InvalidInput("Autoplay needs a scenario_id.")
        update: dict[str, Any] = {}
        if scenario is not None:
            if not req.caller_number and scenario.caller_number:
                update["caller_number"] = scenario.caller_number
            if not req.caller_label and scenario.caller_label:
                update["caller_label"] = scenario.caller_label
        if req.autoplay:
            update["silence_timers"] = "off"  # the script decides when the caller is silent
        call_req = req.model_copy(update=update) if update else req
        detail = await self.calls.create_call(principal, call_req, simulator=True)
        if req.autoplay and scenario is not None and detail.status is CallStatus.ACTIVE:
            task = asyncio.create_task(self._autoplay(principal, detail.id, scenario))
            self._tasks[detail.id] = task
            task.add_done_callback(self._forget_task(detail.id))
        return detail

    def _forget_task(self, call_id: str) -> Callable[[asyncio.Task[None]], None]:
        def forget(_task: asyncio.Task[None]) -> None:
            self._tasks.pop(call_id, None)

        return forget

    def _on_call_finished(self, call_id: str) -> None:
        task = self._tasks.get(call_id)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _wait_for_assistant(self, call_id: str) -> bool:
        """Wait for the assistant to stop speaking. ``False`` when the call is over."""
        while True:
            remaining = self.calls.speaking_remaining_s(call_id)
            if remaining is None:
                return False
            if remaining <= 0:
                return True
            await self.clock.sleep(min(remaining, 0.25) + 0.01)

    async def _autoplay(self, principal: Principal, call_id: str, scenario: ScenarioDetail) -> None:
        try:
            for turn in scenario.turns:
                await self.clock.sleep(turn.delay_ms / 1000.0)
                if not (turn.kind == "speech" and turn.barge_in) and not await self._wait_for_assistant(call_id):
                    return
                if self.calls.speaking_remaining_s(call_id) is None:
                    return
                if turn.kind == "silence":
                    await self.calls.silence(principal, call_id)
                    continue
                for partial in partial_events(turn.text, turn.language)[:-1]:
                    await self.calls.submit_partial(principal, call_id, partial.text, turn.language)
                    await self.clock.sleep(PARTIAL_STEP_S)
                await self.calls.submit_turn(
                    principal,
                    call_id,
                    turn.text,
                    source=TurnSource.SCRIPTED,
                    language_hint=turn.language,
                    stt_confidence=turn.stt_confidence,
                )
        except (Conflict, NotFound):
            return  # the call ended (or was taken over and closed) while the script was still playing
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scenario autoplay failed")

    # ============================================================================================ replay
    async def replay(self, principal: Principal, req: ReplayRequest) -> ReplayResult:
        scenario = await self.get_scenario(principal, req.scenario_id)
        async with self.db.uow() as repo:
            prefs = await repo.get_preferences(principal.id)
            profile = await repo.get_assistant_profile(principal.id)
        mode = self.calls.validate_language_mode(req.language_mode, prefs)
        async with self._replay_slots:
            container = await self._replay_factory()
            try:
                async with container.db.uow() as repo:
                    await repo.ensure_user(principal.id, principal.display_name or principal.id, container.clock.now())
                    await repo.save_preferences(principal.id, prefs, container.clock.now())
                    if profile is not None:
                        await repo.save_assistant_profile(principal.id, profile, container.clock.now())
                driver = ReplayDriver(container, principal)
                call, events = await driver.run(scenario, mode, req.network_profile)
            finally:
                await container.stop()
        return ReplayResult(
            call=call, events=events, checksum=behaviour_checksum(call, events), checksum_covers=CHECKSUM_COVERS
        )

    async def stop(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()
