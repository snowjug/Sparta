"""Fixed-window rate limiting on top of the shared key-value store (works across instances with Redis)."""

from dataclasses import dataclass

from sparta.clock import Clock, SystemClock
from sparta.observability.metrics import RATE_LIMITED, Metrics
from sparta.services.kv import KeyValueStore


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int


class RateLimiter:
    def __init__(self, kv: KeyValueStore, *, clock: Clock | None = None, metrics: Metrics | None = None) -> None:
        self._kv = kv
        self._clock = clock or SystemClock()
        self._metrics = metrics or Metrics()

    async def hit(self, bucket: str, key: str, limit: int, window_s: int = 60) -> RateDecision:
        now = int(self._clock.now().timestamp())
        window = now // window_s
        count = await self._kv.incr(f"rl:{bucket}:{key}:{window}", window_s + 1)
        retry_after = max(1, (window + 1) * window_s - now)
        if count > limit:
            self._metrics.inc(RATE_LIMITED, bucket=bucket)
            return RateDecision(False, limit, 0, retry_after)
        return RateDecision(True, limit, limit - count, retry_after)
