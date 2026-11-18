"""ResilientCaller and CircuitBreaker: retries, back-off, timeouts, breaker states and sanitised errors."""

import asyncio

import pytest

from sparta.observability.metrics import PROVIDER_ERRORS, PROVIDER_LATENCY_MS, PROVIDER_REQUESTS, Metrics
from sparta.providers.base import (
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from sparta.providers.resilience import MAX_BACKOFF_S, BreakerState, CircuitBreaker, ResilientCaller

from .helpers import FastClock

SECRET = "sk-live-0123456789abcdef"


def caller(clock: FastClock, metrics: Metrics | None = None, **kw) -> ResilientCaller:
    kw.setdefault("timeout_s", 1.0)
    kw.setdefault("max_retries", 2)
    return ResilientCaller("prov", "stage", clock=clock, metrics=metrics or Metrics(), **kw)


class Flaky:
    """Fails with the queued errors in order, then succeeds."""

    def __init__(self, *failures: BaseException) -> None:
        self.failures = list(failures)
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


def transient() -> ProviderError:
    return ProviderError("prov", "stage", "service unavailable (HTTP 503)", retryable=True, status=503)


# ------------------------------------------------------------------------------------------------ breaker
def test_breaker_opens_after_consecutive_failures_and_blocks_calls(fast_clock):
    breaker = CircuitBreaker(failure_threshold=3, reset_after_s=30, clock=fast_clock)
    for _ in range(2):
        breaker.failure()
    assert breaker.state is BreakerState.CLOSED and breaker.allow()
    breaker.failure()
    assert breaker.state is BreakerState.OPEN and not breaker.allow()


def test_a_success_resets_the_consecutive_failure_count(fast_clock):
    breaker = CircuitBreaker(failure_threshold=3, clock=fast_clock)
    breaker.failure()
    breaker.failure()
    breaker.success()
    breaker.failure()
    breaker.failure()
    assert breaker.state is BreakerState.CLOSED


def test_half_open_admits_exactly_one_probe_and_a_success_closes_the_breaker(fast_clock):
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=30, clock=fast_clock)
    breaker.failure()
    fast_clock.t += 29.9
    assert breaker.state is BreakerState.OPEN and not breaker.allow()
    fast_clock.t += 0.2
    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.allow() is True
    assert breaker.allow() is False  # the probe is in flight: everyone else still fails fast
    breaker.success()
    assert breaker.state is BreakerState.CLOSED and breaker.allow()


def test_a_failed_probe_reopens_the_breaker_for_another_full_cool_down(fast_clock):
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=30, clock=fast_clock)
    breaker.failure()
    fast_clock.t += 31
    assert breaker.allow()
    breaker.failure()
    assert breaker.state is BreakerState.OPEN
    fast_clock.t += 29
    assert breaker.state is BreakerState.OPEN
    fast_clock.t += 2
    assert breaker.state is BreakerState.HALF_OPEN


# ------------------------------------------------------------------------------------------------ retries
async def test_success_is_returned_and_measured(fast_clock):
    metrics = Metrics()

    async def fn() -> str:
        return "hello"

    assert await caller(fast_clock, metrics).call(fn) == "hello"
    assert metrics.counter(PROVIDER_REQUESTS, provider="prov", stage="stage") == 1
    assert len(metrics.samples(PROVIDER_LATENCY_MS, provider="prov", stage="stage")) == 1
    assert fast_clock.sleeps == []


async def test_retryable_failures_are_retried_with_capped_exponential_backoff(fast_clock):
    fn = Flaky(transient(), transient())
    assert await caller(fast_clock, max_retries=2, backoff_base_s=0.2).call(fn) == "ok"
    assert fn.calls == 3
    assert fast_clock.sleeps == [0.2, 0.4]


async def test_backoff_never_exceeds_the_cap(fast_clock):
    fn = Flaky(*[transient() for _ in range(6)])
    with pytest.raises(ProviderError):
        await caller(fast_clock, max_retries=5, backoff_base_s=1.0).call(fn)
    assert fast_clock.sleeps == [1.0, 2.0, 2.0, 2.0, 2.0] and max(fast_clock.sleeps) == MAX_BACKOFF_S


async def test_retry_after_is_honoured_but_bounded(fast_clock):
    hint = ProviderError("prov", "stage", "rate limited", retryable=True, status=429, retry_after_s=1.25)
    hostile = ProviderError("prov", "stage", "rate limited", retryable=True, status=429, retry_after_s=3600)
    await caller(fast_clock).call(Flaky(hint, hostile))
    assert fast_clock.sleeps == [1.25, MAX_BACKOFF_S]


async def test_non_retryable_errors_are_raised_immediately(fast_clock):
    metrics = Metrics()
    fn = Flaky(ProviderRejected("prov", "stage", "authentication failed", status=401))
    with pytest.raises(ProviderRejected) as err:
        await caller(fast_clock, metrics).call(fn)
    assert fn.calls == 1 and fast_clock.sleeps == [] and err.value.status == 401
    assert metrics.counter(PROVIDER_ERRORS, provider="prov", stage="stage", kind="ProviderRejected") == 1


async def test_exhausted_retries_raise_the_last_error_and_count_one_breaker_failure(fast_clock):
    breaker = CircuitBreaker(failure_threshold=2, clock=fast_clock)
    fn = Flaky(*[transient() for _ in range(10)])
    c = caller(fast_clock, breaker=breaker, max_retries=2)
    with pytest.raises(ProviderError) as err:
        await c.call(fn)
    assert fn.calls == 3 and err.value.status == 503 and err.value.retryable
    assert breaker.state is BreakerState.CLOSED  # one logical call = one failure, however many attempts
    with pytest.raises(ProviderError):
        await c.call(fn)
    assert breaker.state is BreakerState.OPEN


# ------------------------------------------------------------------------------------------------ timeouts
async def test_a_slow_call_times_out_and_is_retried_as_retryable(fast_clock):
    calls = 0

    async def slow() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(5)
        return "late"

    with pytest.raises(ProviderTimeout) as err:
        await caller(fast_clock, timeout_s=0.01, max_retries=1).call(slow)
    assert calls == 2 and err.value.retryable and "timed out after 0.01s" in err.value.message


async def test_a_timeout_followed_by_success_recovers(fast_clock):
    attempts = 0

    async def sometimes_slow() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.sleep(5)
        return "ok"

    assert await caller(fast_clock, timeout_s=0.01).call(sometimes_slow) == "ok" and attempts == 2


# ------------------------------------------------------------------------------------------------ sanitising
async def test_unexpected_exceptions_are_sanitised_and_retried(fast_clock):
    fn = Flaky(RuntimeError(f"POST https://x/?key={SECRET} body=my otp is 482913"))
    assert await caller(fast_clock).call(fn) == "ok" and fn.calls == 2

    always = Flaky(*[RuntimeError(f"leaks {SECRET}") for _ in range(5)])
    with pytest.raises(ProviderError) as err:
        await caller(fast_clock).call(always)
    assert SECRET not in str(err.value) and SECRET not in repr(err.value)
    assert err.value.message == "provider call failed" and err.value.retryable
    assert err.value.__cause__ is None and err.value.__context__ is None


async def test_unexpected_exception_logs_only_its_type(fast_clock, caplog):
    caplog.set_level("WARNING", logger="sparta.providers")
    with pytest.raises(ProviderError):
        await caller(fast_clock, max_retries=0).call(Flaky(ValueError(f"contains {SECRET}")), trace_id="trace-1")
    assert SECRET not in caplog.text and "ValueError" in "".join(str(r.__dict__) for r in caplog.records)


async def test_cancellation_is_never_swallowed_or_counted_as_a_failure(fast_clock):
    breaker = CircuitBreaker(failure_threshold=1, clock=fast_clock)
    c = caller(fast_clock, breaker=breaker, timeout_s=5)
    started = asyncio.Event()

    async def hang() -> str:
        started.set()
        await asyncio.sleep(30)
        return "never"

    task = asyncio.create_task(c.call(hang))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert breaker.state is BreakerState.CLOSED


# ------------------------------------------------------------------------------------------------ breaker use
async def test_an_open_circuit_fails_fast_without_calling_the_provider(fast_clock):
    metrics = Metrics()
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=30, clock=fast_clock)
    c = caller(fast_clock, metrics, breaker=breaker, max_retries=0)
    failing = Flaky(transient())
    with pytest.raises(ProviderError):
        await c.call(failing)

    untouched = Flaky()
    with pytest.raises(ProviderUnavailable) as err:
        await c.call(untouched)
    assert untouched.calls == 0 and not err.value.retryable and "circuit open" in err.value.message
    assert metrics.counter(PROVIDER_ERRORS, provider="prov", stage="stage", kind="circuit_open") == 1


async def test_after_the_cool_down_one_probe_closes_the_circuit_again(fast_clock):
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=30, clock=fast_clock)
    c = caller(fast_clock, breaker=breaker, max_retries=0)
    with pytest.raises(ProviderError):
        await c.call(Flaky(transient()))
    fast_clock.t += 31
    assert breaker.state is BreakerState.HALF_OPEN
    assert await c.call(Flaky()) == "ok"
    assert breaker.state is BreakerState.CLOSED


async def test_a_failing_probe_keeps_the_circuit_open(fast_clock):
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=30, clock=fast_clock)
    c = caller(fast_clock, breaker=breaker, max_retries=0)
    with pytest.raises(ProviderError):
        await c.call(Flaky(transient()))
    fast_clock.t += 31
    with pytest.raises(ProviderError):
        await c.call(Flaky(transient()))
    with pytest.raises(ProviderUnavailable):
        await c.call(Flaky())


async def test_call_or_degrades_gracefully_to_the_default(fast_clock):
    value, error = await caller(fast_clock, max_retries=0).call_or(
        Flaky(ProviderRejected("prov", "stage", "blocked")), "fallback"
    )
    assert value == "fallback" and isinstance(error, ProviderRejected)
    value, error = await caller(fast_clock).call_or(Flaky(), "fallback")
    assert value == "ok" and error is None
