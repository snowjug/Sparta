"""Injectable clocks. All timers and timestamps in call handling go through a ``Clock`` for deterministic tests."""

import asyncio
import heapq
import itertools
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class VirtualClock:
    """Manually advanced clock. ``sleep`` resolves only when ``advance`` moves time past the deadline."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._mono = 0.0
        self._waiters: list[tuple[float, int, asyncio.Future[None]]] = []
        self._counter = itertools.count()

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (self._mono + seconds, next(self._counter), fut))
        await fut

    async def advance(self, seconds: float) -> None:
        target = self._mono + seconds
        while self._waiters and self._waiters[0][0] <= target:
            deadline, _, fut = heapq.heappop(self._waiters)
            self._now += timedelta(seconds=deadline - self._mono)
            self._mono = deadline
            if not fut.done():
                fut.set_result(None)
            await asyncio.sleep(0)
        self._now += timedelta(seconds=target - self._mono)
        self._mono = target
        await asyncio.sleep(0)
