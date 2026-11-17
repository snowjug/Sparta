"""Timeouts, bounded retries, circuit breaking and sanitised errors for every external provider call.

* a per-attempt timeout (``ProviderTimeout``),
* retries only for retryable failures, with capped exponential backoff and ``Retry-After`` honoured (but bounded),
* a circuit breaker that fails fast while a provider is down and probes it again after a cool-down,
* every unexpected exception becomes a :class:`ProviderError` whose message never contains response bodies or secrets,
* metrics and a trace id on every attempt.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeVar

from sparta.clock import Clock, SystemClock
from sparta.observability.metrics import PROVIDER_ERRORS, PROVIDER_LATENCY_MS, PROVIDER_REQUESTS, Metrics
from sparta.providers.base import ProviderError, ProviderTimeout, ProviderUnavailable

T = TypeVar("T")
log = logging.getLogger("sparta.providers")
MAX_BACKOFF_S = 2.0


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Opens after ``failure_threshold`` consecutive failures; allows one probe after ``reset_after_s``."""

    def __init__(self, failure_threshold: int = 5, reset_after_s: float = 30.0, clock: Clock | None = None) -> None:
        self.failure_threshold = failure_threshold
        self.reset_after_s = reset_after_s
        self._clock = clock or SystemClock()
        self._failures = 0
        self._opened_at: float | None = None
        self._probing = False

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.CLOSED
        if self._clock.monotonic() - self._opened_at >= self.reset_after_s:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def allow(self) -> bool:
        state = self.state
        if state is BreakerState.CLOSED:
            return True
        if state is BreakerState.HALF_OPEN and not self._probing:
            self._probing = True
            return True
        return False

    def success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probing = False

    def failure(self) -> None:
        self._failures += 1
        self._probing = False
        if self._failures >= self.failure_threshold or self._opened_at is not None:
            self._opened_at = self._clock.monotonic()


class ResilientCaller:
    def __init__(
        self,
        provider: str,
        stage: str,
        *,
        timeout_s: float = 6.0,
        max_retries: int = 2,
        backoff_base_s: float = 0.2,
        breaker: CircuitBreaker | None = None,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.provider = provider
        self.stage = stage
        self.timeout_s = timeout_s
        self.max_retries = max(0, max_retries)
        self.backoff_base_s = backoff_base_s
        self.clock = clock or SystemClock()
        self.breaker = breaker or CircuitBreaker(clock=self.clock)
        self.metrics = metrics or Metrics()

    async def call(self, fn: Callable[[], Awaitable[T]], *, trace_id: str = "") -> T:
        if not self.breaker.allow():
            self.metrics.inc(PROVIDER_ERRORS, provider=self.provider, stage=self.stage, kind="circuit_open")
            raise ProviderUnavailable(self.provider, self.stage, "temporarily unavailable (circuit open)")
        last: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            started = self.clock.monotonic()
            self.metrics.inc(PROVIDER_REQUESTS, provider=self.provider, stage=self.stage)
            try:
                result = await asyncio.wait_for(fn(), timeout=self.timeout_s)
            except TimeoutError:
                last = ProviderTimeout(self.provider, self.stage, self.timeout_s)
            except ProviderError as exc:
                last = exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    "provider call failed",
                    extra={
                        "provider": self.provider,
                        "stage": self.stage,
                        "error_type": type(exc).__name__,
                        "trace_id": trace_id,
                    },
                )
                last = ProviderError(self.provider, self.stage, "provider call failed", retryable=True)
            else:
                self.breaker.success()
                self.metrics.observe(
                    PROVIDER_LATENCY_MS,
                    (self.clock.monotonic() - started) * 1000,
                    provider=self.provider,
                    stage=self.stage,
                )
                return result

            kind = type(last).__name__
            self.metrics.inc(PROVIDER_ERRORS, provider=self.provider, stage=self.stage, kind=kind)
            if not last.retryable or attempt >= self.max_retries:
                break
            delay = min(MAX_BACKOFF_S, last.retry_after_s or self.backoff_base_s * (2**attempt))
            await self.clock.sleep(delay)
        self.breaker.failure()
        assert last is not None
        raise last

    async def call_or(
        self, fn: Callable[[], Awaitable[T]], default: T, *, trace_id: str = ""
    ) -> tuple[T, ProviderError | None]:
        """Graceful degradation: return ``default`` plus the error instead of raising."""
        try:
            return await self.call(fn, trace_id=trace_id), None
        except ProviderError as exc:
            return default, exc
