"""Periodic background work: close abandoned calls, apply retention, publish a gauge. Failures never stop the loop."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from sparta.services.calls import CallService
from sparta.services.retention import RetentionService

log = logging.getLogger("sparta.jobs")


class BackgroundJobs:
    def __init__(
        self,
        *,
        calls: CallService,
        retention: RetentionService,
        reaper_interval_s: float,
        retention_interval_s: float,
    ) -> None:
        self._calls = calls
        self._retention = retention
        self._reaper_interval_s = reaper_interval_s
        self._retention_interval_s = retention_interval_s
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop("reaper", self._reaper_interval_s, self._reap), name="sparta-reaper"),
            asyncio.create_task(
                self._loop("retention", self._retention_interval_s, self._apply_retention), name="sparta-retention"
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def _reap(self) -> None:
        ended = await self._calls.reap_abandoned()
        if ended:
            log.info("closed abandoned calls", extra={"count": ended})
        self._calls.metrics.gauge("sparta_active_calls", float(self._calls.active_runtime_count()))

    async def _apply_retention(self) -> None:
        await self._retention.run_once()

    @staticmethod
    async def _loop(name: str, interval_s: float, job: Callable[[], Awaitable[None]]) -> None:
        while True:
            await asyncio.sleep(max(1.0, interval_s))
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("background job failed", extra={"job": name})
