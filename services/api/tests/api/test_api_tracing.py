"""Spans carry identifiers and timings, never content; a call takes the trace id of the request that created it."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from conftest import SCAM, ApiEnv
from sparta.observability import tracing
from sparta.providers.base import ProviderError
from sparta.providers.resilience import ResilientCaller

API = "/api/v1"


@pytest.fixture
def exporter(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "tracer", lambda: provider.get_tracer("sparta-test"))
    return exporter


def everything_exported(exporter: InMemorySpanExporter) -> str:
    """All names, attribute keys and values and event texts of the finished spans, as one string."""
    parts: list[str] = []
    for finished in exporter.get_finished_spans():
        parts.append(finished.name)
        parts += [f"{k}={v}" for k, v in (finished.attributes or {}).items()]
        for event in finished.events:
            parts.append(event.name)
            parts += [f"{k}={v}" for k, v in (event.attributes or {}).items()]
        if finished.status.description:
            parts.append(finished.status.description)
    return "\n".join(parts)


async def test_every_http_request_is_a_server_span_named_by_its_route_template(env: ApiEnv, exporter):
    created = await env.new_call(caller_number="+919876543210", caller_label="Spam Sam")
    exporter.clear()
    response = await env.client.get(f"{API}/calls/{created['id']}", params={"q": "secret-search-term"})
    assert response.status_code == 200

    (request_span,) = [s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER]
    assert request_span.name == f"GET {API}/calls/{{call_id}}"
    assert request_span.attributes["http.route"] == f"{API}/calls/{{call_id}}"
    assert request_span.attributes["http.response.status_code"] == 200
    assert request_span.attributes["sparta.request_id"] == response.headers["x-request-id"]
    exported = everything_exported(exporter)
    for private in (created["id"], "secret-search-term", "9876543210", "Spam Sam"):
        assert private not in exported, private


async def test_a_server_error_marks_the_span_and_a_client_error_does_not(env: ApiEnv, exporter):
    missing = await env.client.get(f"{API}/calls/call_does_not_exist")
    assert missing.status_code == 404
    (request_span,) = [s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER]
    assert request_span.attributes["http.response.status_code"] == 404
    assert request_span.status.status_code is StatusCode.UNSET


async def test_a_call_takes_the_trace_id_of_the_request_that_created_it(env: ApiEnv, exporter):
    created = await env.new_call(caller_number="+919876543210")
    (request_span,) = [
        s
        for s in exporter.get_finished_spans()
        if s.kind is SpanKind.SERVER and s.attributes["http.route"] == f"{API}/calls"
    ]
    assert created["trace_id"] == f"{request_span.context.trace_id:032x}"
    again = (await env.client.get(f"{API}/calls/{created['id']}")).json()
    assert again["trace_id"] == created["trace_id"]


async def test_the_engine_step_is_a_span_without_any_caller_text(env: ApiEnv, exporter):
    created = await env.new_call(caller_number="+919876543210")
    await env.say(created["id"], SCAM)
    await env.advance(60)
    steps = [s for s in exporter.get_finished_spans() if s.name == "engine.on_caller_turn"]
    assert len(steps) == 1
    assert steps[0].attributes["sparta.risk_level"] == "high" and steps[0].attributes["call_id"] == created["id"]
    exported = everything_exported(exporter)
    for content in ("OTP", "Rahul", "State Bank", "9876543210", "sent to your phone"):
        assert content not in exported, content


async def test_a_failing_provider_call_records_the_error_class_and_never_its_message(exporter):
    caller = ResilientCaller("fake-provider", "stt", max_retries=0, timeout_s=1.0)

    async def boom() -> str:
        raise RuntimeError("the caller said OTP 482913 and lives at 42 Lake View Road")

    with pytest.raises(ProviderError):
        await caller.call(boom)
    (provider_span,) = exporter.get_finished_spans()
    assert provider_span.name == "provider.call"
    assert provider_span.attributes["provider"] == "fake-provider" and provider_span.attributes["stage"] == "stt"
    assert provider_span.status.status_code is StatusCode.ERROR
    assert provider_span.attributes["error.type"] == "ProviderError"
    exported = everything_exported(exporter)
    assert "482913" not in exported and "Lake View" not in exported and "RuntimeError" not in provider_span.name


async def test_a_successful_provider_call_is_a_plain_span(exporter):
    caller = ResilientCaller("fake-provider", "tts")

    async def fine() -> int:
        return 7

    assert await caller.call(fine) == 7
    (provider_span,) = exporter.get_finished_spans()
    assert provider_span.status.status_code is StatusCode.UNSET and "error.type" not in provider_span.attributes
