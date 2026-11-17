"""Tracing and usage/cost estimation.

Traces carry identifiers and timings only, never transcript text or numbers. When OpenTelemetry is not configured
the code still produces a valid, random trace id so every call has a *safe diagnostic trace ID* clients can quote.
"""

import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sparta.config import Settings

_TRACER_NAME = "sparta"
_configured = False


def setup_tracing(settings: "Settings") -> None:
    """Configure OpenTelemetry once. Exporting needs ``SPARTA_OTLP_ENDPOINT`` and the ``otlp`` extra."""
    global _configured  # noqa: PLW0603
    if _configured or not settings.otel_enabled:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    if settings.otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)))
        except ImportError:  # the optional exporter is not installed: keep tracing local, never crash startup
            pass
    trace.set_tracer_provider(provider)
    _configured = True


def new_trace_id() -> str:
    """Current span's trace id if one is active and valid, otherwise a fresh random 128-bit id."""
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        return f"{ctx.trace_id:032x}"
    return secrets.token_hex(16)


@contextmanager
def span(name: str, **attributes: str | int | float | bool) -> "Iterator[None]":
    """A span with identifier/timing attributes only. Never pass transcript text or numbers here."""
    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield


@dataclass(frozen=True)
class UnitCosts:
    """Estimated unit prices in USD. Defaults are zero (simulator); production sets real prices via settings/env.

    These are *estimates for guardrails and dashboards*, not billing data.
    """

    stt_per_audio_hour: float = 0.0
    tts_per_million_chars: float = 0.0
    llm_per_million_prompt_tokens: float = 0.0
    llm_per_million_completion_tokens: float = 0.0
    telephony_per_minute: float = 0.0


def estimate_cost(
    costs: UnitCosts,
    *,
    audio_seconds: float = 0.0,
    tts_chars: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    call_minutes: float = 0.0,
) -> float:
    total = (
        audio_seconds / 3600.0 * costs.stt_per_audio_hour
        + tts_chars / 1_000_000.0 * costs.tts_per_million_chars
        + prompt_tokens / 1_000_000.0 * costs.llm_per_million_prompt_tokens
        + completion_tokens / 1_000_000.0 * costs.llm_per_million_completion_tokens
        + call_minutes * costs.telephony_per_minute
    )
    return round(total, 6)
