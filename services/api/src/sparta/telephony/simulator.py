"""SimulatorTelephonyProvider: a complete, credential-free telephony adapter for development, demos and tests.

It is a supported mode, not a hidden fake. Every capability it advertises is *simulated* and labelled as such:
playback is timing-only, takeover is a labelled simulation, and no cellular call or audio is involved.
"""

import asyncio
import itertools
import logging

from sparta.clock import Clock, SystemClock
from sparta.domain.enums import ProviderKind
from sparta.domain.models import SpeechPlan
from sparta.telephony.base import (
    Playback,
    ProviderCallRef,
    ProviderStatus,
    TelephonyCapabilities,
    TelephonyEventSink,
    TransferResult,
)

log = logging.getLogger("sparta.telephony.simulator")

SIMULATOR_CAPABILITIES = TelephonyCapabilities(
    can_answer=True,
    can_play_audio=True,
    can_stop_playback=True,
    can_transfer=True,
    can_hangup=True,
    receives_caller_audio=False,
    two_way_audio=False,
    dtmf=False,
    simulated=True,
    live_calls_supported=False,
    note="Built-in simulator. No real phone call or audio is involved; takeover is a labelled simulation.",
)


class SimulatorTelephonyProvider:
    name = "simulator"
    kind = ProviderKind.SIMULATOR
    capabilities = SIMULATOR_CAPABILITIES

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._sink: TelephonyEventSink | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._counter = itertools.count(1)

    def bind(self, sink: TelephonyEventSink) -> None:
        self._sink = sink

    async def answer(self, call: ProviderCallRef) -> None:
        return None

    async def play(self, call: ProviderCallRef, plan: SpeechPlan) -> Playback:
        playback_id = f"pb_{call.call_id[-8:]}_{next(self._counter)}"
        duration = max(plan.est_duration_ms, 1)
        self._tasks[playback_id] = asyncio.create_task(self._finish(call.call_id, playback_id, duration))
        await asyncio.sleep(0)  # arm the completion timer now, so a virtual clock measures from this moment
        return Playback(playback_id=playback_id, call_id=call.call_id, duration_ms=duration, simulated=True)

    async def _finish(self, call_id: str, playback_id: str, duration_ms: int) -> None:
        try:
            await self._clock.sleep(duration_ms / 1000.0)
            if self._sink is not None:
                await self._sink.playback_finished(call_id, playback_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # a sink bug must not kill the event loop task silently
            log.exception("simulated playback completion failed")
        finally:
            self._tasks.pop(playback_id, None)

    async def stop_playback(self, call: ProviderCallRef, playback_id: str) -> None:
        task = self._tasks.pop(playback_id, None)
        if task is not None:
            task.cancel()

    async def hangup(self, call: ProviderCallRef, reason: str) -> None:
        for playback_id in [p for p in self._tasks if call.call_id[-8:] in p]:
            await self.stop_playback(call, playback_id)

    async def transfer(self, call: ProviderCallRef, destination: str | None) -> TransferResult:
        return TransferResult(accepted=True, simulated=True, detail="Simulated bridge to the owner. No real call.")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider=self.name, kind=self.kind, healthy=True, simulated=True, detail=self.capabilities.note
        )

    async def aclose(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()
