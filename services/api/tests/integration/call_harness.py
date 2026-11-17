"""Test harness for end-to-end call-service tests: hermetic container + virtual clock + deterministic ids."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sparta.clock import VirtualClock
from sparta.config import Settings
from sparta.domain.enums import TurnSource
from sparta.domain.models import CallDetail
from sparta.services.container import Container
from sparta.services.dto import CreateCallRequest, Principal, TurnResult
from sparta.services.notifier import RecordingPushNotifier

OWNER = Principal(id="owner-1", display_name="Atharv")
OTHER = Principal(id="owner-2", display_name="Meera")


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "log_json": False,
        "database_url": "sqlite+aiosqlite:///:memory:",
        "auto_migrate": False,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@asynccontextmanager
async def running_container(**overrides: object) -> AsyncIterator[Container]:
    container = await Container.build(make_settings(**overrides), hermetic=True, notifier=RecordingPushNotifier())
    await container.start()
    try:
        yield container
    finally:
        await container.stop()


class Harness:
    """Drives one owner's calls through the real ``CallService``."""

    def __init__(self, container: Container, principal: Principal = OWNER) -> None:
        self.c = container
        self.p = principal
        assert isinstance(container.clock, VirtualClock)
        self.clock: VirtualClock = container.clock

    async def start(
        self,
        *,
        number: str | None = "+919876543210",
        label: str | None = None,
        language_mode: str = "auto",
        timers: str = "off",
        network: str = "ideal",
        scenario_id: str | None = None,
    ) -> CallDetail:
        return await self.c.calls.create_call(
            self.p,
            CreateCallRequest(
                caller_number=number,
                caller_label=label,
                language_mode=language_mode,
                silence_timers=timers,  # type: ignore[arg-type]
                network_profile=network,  # type: ignore[arg-type]
                scenario_id=scenario_id,
            ),
            simulator=True,
        )

    async def idle(self, call_id: str | None = None, rounds: int = 400) -> None:
        """Wait (real time) until background call work has gone quiet: DB writes run on a worker thread."""
        stable = 0
        for _ in range(rounds):
            await asyncio.sleep(0.004)
            runtimes = (
                [self.c.calls._runtimes[call_id]]
                if call_id in self.c.calls._runtimes
                else ([] if call_id else list(self.c.calls._runtimes.values()))
            )
            busy = any(rt.lock.locked() for rt in runtimes)
            stable = 0 if busy else stable + 1
            if stable >= 4:
                return
        raise AssertionError("call work did not go idle")

    async def advance(self, seconds: float, call_id: str | None = None) -> None:
        """Move virtual time forward, then let whatever the timers triggered finish."""
        await self.clock.advance(seconds)
        await self.idle(call_id)

    async def settle(self, call_id: str) -> None:
        """Let the assistant finish speaking (and hang up, when the call is ending), including the DB work."""
        rt = self.c.calls._runtimes.get(call_id)
        if rt is None:
            return
        remaining = rt.speaking_until - self.clock.monotonic()
        if remaining > 0:
            await self.clock.advance(remaining + 0.001)
        for _ in range(600):  # real-time polling: SQLite work happens on a worker thread
            current = self.c.calls._runtimes.get(call_id)
            if current is None or (current.playback_id is None and not current.pending_finalize):
                break
            await asyncio.sleep(0.005)
        else:
            raise AssertionError("call did not settle")
        await self.idle(call_id)

    async def say(self, call_id: str, text: str, *, settle: bool = True, **kwargs: object) -> TurnResult:
        await self.settle(call_id)
        result = await self.c.calls.submit_turn(self.p, call_id, text, source=TurnSource.SCRIPTED, **kwargs)  # type: ignore[arg-type]
        if settle:
            await self.settle(call_id)
        return result

    async def detail(self, call_id: str) -> CallDetail:
        return await self.c.calls.get_call(self.p, call_id)
