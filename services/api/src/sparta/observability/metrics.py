"""In-process metrics (Prometheus text exposition) and a bounded sample store for percentiles.

Telemetry never carries call content: label values are restricted to short identifiers (provider, stage, outcome).
"""

import re
import threading
from collections import defaultdict, deque
from collections.abc import Iterable

LabelKey = tuple[tuple[str, str], ...]
DEFAULT_BUCKETS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
_SAFE_LABEL = re.compile(r"[^A-Za-z0-9_.:\-]")
RESERVOIR = 2048


def _key(labels: dict[str, str]) -> LabelKey:
    return tuple(sorted((k, _SAFE_LABEL.sub("_", str(v))[:48]) for k, v in labels.items()))


def percentile(values: Iterable[float], pct: float) -> float | None:
    data = sorted(values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    rank = (len(data) - 1) * pct / 100.0
    lo, hi = int(rank), min(int(rank) + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (rank - lo)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, LabelKey], float] = defaultdict(float)
        self._hist_count: dict[tuple[str, LabelKey], int] = defaultdict(int)
        self._hist_sum: dict[tuple[str, LabelKey], float] = defaultdict(float)
        self._hist_buckets: dict[tuple[str, LabelKey], list[int]] = {}
        self._samples: dict[tuple[str, LabelKey], deque[float]] = defaultdict(lambda: deque(maxlen=RESERVOIR))
        self._gauges: dict[tuple[str, LabelKey], float] = {}

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[(name, _key(labels))] += value

    def gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[(name, _key(labels))] = value

    def observe(self, name: str, value: float, **labels: str) -> None:
        k = (name, _key(labels))
        with self._lock:
            self._hist_count[k] += 1
            self._hist_sum[k] += value
            buckets = self._hist_buckets.setdefault(k, [0] * len(DEFAULT_BUCKETS_MS))
            for i, bound in enumerate(DEFAULT_BUCKETS_MS):
                if value <= bound:
                    buckets[i] += 1
            self._samples[k].append(value)

    def counter(self, name: str, **labels: str) -> float:
        with self._lock:
            return self._counters.get((name, _key(labels)), 0.0)

    def samples(self, name: str, **labels: str) -> list[float]:
        with self._lock:
            return list(self._samples.get((name, _key(labels)), ()))

    def quantiles(self, name: str, **labels: str) -> dict[str, float | None]:
        values = self.samples(name, **labels)
        return {"count": float(len(values)), "p50": percentile(values, 50), "p95": percentile(values, 95)}

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counters": {_fmt(n, k): v for (n, k), v in self._counters.items()},
                "gauges": {_fmt(n, k): v for (n, k), v in self._gauges.items()},
                "histograms": {
                    _fmt(n, k): {"count": c, "sum": round(self._hist_sum[(n, k)], 3)}
                    for (n, k), c in self._hist_count.items()
                },
            }

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{_labels(labels)} {value}")
            for (name, labels), value in sorted(self._gauges.items()):
                lines.append(f"{name}{_labels(labels)} {value}")
            for (name, labels), count in sorted(self._hist_count.items()):
                buckets = self._hist_buckets[(name, labels)]
                for bound, n in zip(DEFAULT_BUCKETS_MS, buckets, strict=True):
                    lines.append(f"{name}_bucket{_labels(labels, le=str(bound))} {n}")
                lines.append(f"{name}_bucket{_labels(labels, le='+Inf')} {count}")
                lines.append(f"{name}_sum{_labels(labels)} {self._hist_sum[(name, labels)]}")
                lines.append(f"{name}_count{_labels(labels)} {count}")
        return "\n".join(lines) + "\n"


def _labels(labels: LabelKey, **extra: str) -> str:
    pairs = [*labels, *extra.items()]
    return "{" + ",".join(f'{k}="{v}"' for k, v in pairs) + "}" if pairs else ""


def _fmt(name: str, labels: LabelKey) -> str:
    return name + (_labels(labels) if labels else "")


# Metric names used across the product (kept here so dashboards and docs have one source of truth).
CALLS_TOTAL = "sparta_calls_total"
CALL_MINUTES = "sparta_call_minutes_total"
STAGE_LATENCY_MS = "sparta_stage_latency_ms"
RISK_ENGINE_MS = "sparta_risk_engine_ms"
ESCALATIONS_TOTAL = "sparta_escalations_total"
PROVIDER_REQUESTS = "sparta_provider_requests_total"
PROVIDER_ERRORS = "sparta_provider_errors_total"
PROVIDER_LATENCY_MS = "sparta_provider_latency_ms"
TOKENS_TOTAL = "sparta_llm_tokens_total"
AUDIO_SECONDS = "sparta_audio_seconds_total"
FEEDBACK_TOTAL = "sparta_feedback_total"
VALIDATOR_FALLBACKS = "sparta_validator_fallbacks_total"
COST_USD = "sparta_estimated_cost_usd_total"
TRANSCRIPT_CONFIDENCE = "sparta_transcript_confidence"
LANGUAGE_CONFIDENCE = "sparta_language_confidence"
CALL_FAILURES = "sparta_call_failures_total"
RATE_LIMITED = "sparta_rate_limited_total"
MEDIA_REJECTED = "sparta_media_rejected_total"
