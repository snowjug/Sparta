"""The call service feeds provider audio through the recognition pipeline and keeps the call consistent."""

import asyncio
from dataclasses import replace

import pytest
from call_harness import OWNER, Harness
from tests.audio_fakes import RATE, SILENT, VOICED, FakeStt, Script

from sparta.domain.enums import CallStatus, Speaker, TurnSource
from sparta.services.audio_pipeline import AudioPipeline
from sparta.telephony.simulator import SIMULATOR_CAPABILITIES

pytestmark = pytest.mark.asyncio


def event_types(events) -> list[str]:
    return [e.type for e in events]


@pytest.fixture
def media_call(h: Harness):
    """A simulated call whose provider claims to deliver caller audio, recognised by a scripted engine."""

    def configure(stt: FakeStt) -> FakeStt:
        calls = h.c.calls
        calls.stt = stt  # type: ignore[assignment]
        calls.sim_telephony.capabilities = replace(SIMULATOR_CAPABILITIES, receives_caller_audio=True)  # type: ignore[misc]
        return stt

    return configure


async def speak(h: Harness, call_id: str, voiced_ms: int, silence_ms: int = 700) -> None:
    for _ in range(voiced_ms // 20):
        await h.c.calls.caller_audio(call_id, VOICED, RATE)
    for _ in range(silence_ms // 20):
        await h.c.calls.caller_audio(call_id, SILENT, RATE)


async def test_spoken_audio_becomes_a_provider_stt_turn_that_the_engine_screens(h: Harness, media_call):
    media_call(FakeStt(Script(text="Please tell me the OTP you just received", language="en-IN", confidence=0.88)))
    created = await h.start()
    await h.settle(created.id)
    rt = h.c.calls._runtimes[created.id]
    assert isinstance(rt.pipeline, AudioPipeline) and h.c.calls.audio_expected(created.id)

    await speak(h, created.id, voiced_ms=500)
    await rt.pipeline.drain()
    await h.settle(created.id)

    detail = await h.detail(created.id)
    caller = [t for t in detail.turns if t.speaker is Speaker.CALLER]
    assert [t.text for t in caller] == ["Please tell me the OTP you just received"]
    assert caller[0].source is TurnSource.PROVIDER_STT and caller[0].language_confidence is not None
    assert detail.risk_level.value == "high" and detail.status is CallStatus.ENDED
    assert detail.metrics  # the call still finalises normally (summary, metrics)


async def test_speaking_over_the_assistant_barges_in_through_the_pipeline(h: Harness, media_call):
    media_call(FakeStt())
    created = await h.start()  # the greeting is playing
    await speak(h, created.id, voiced_ms=300, silence_ms=0)
    await asyncio.sleep(0.05)
    types = event_types(await h.c.calls.events(OWNER, created.id, 0))
    assert "assistant.interrupted" in types
    detail = await h.detail(created.id)
    assert detail.turns[0].interrupted
    await h.c.calls.end_internal(created.id, "test_done")


async def test_the_silence_timer_waits_while_the_caller_is_speaking(h: Harness, media_call):
    media_call(FakeStt(Script(text="Hello, this is Suresh from the society office")))
    created = await h.start(timers="preferences")
    await h.settle(created.id)
    await h.advance(5.0, created.id)
    await speak(h, created.id, voiced_ms=300, silence_ms=0)  # the caller starts talking 5 s into the 8 s silence timer
    await h.advance(4.0, created.id)  # past the original deadline: no "are you still there?"
    assistant_turns = [t for t in (await h.detail(created.id)).turns if t.speaker is Speaker.ASSISTANT]
    assert len(assistant_turns) == 1
    await h.c.calls.end_internal(created.id, "test_done")


async def test_noise_without_words_returns_to_waiting_and_the_silence_timer_resumes(h: Harness, media_call):
    media_call(FakeStt(Script(text="")))
    created = await h.start(timers="preferences")
    await h.settle(created.id)
    rt = h.c.calls._runtimes[created.id]
    await speak(h, created.id, voiced_ms=300)
    await rt.pipeline.drain()
    await h.idle(created.id)
    await h.advance(8.5, created.id)  # the timer was re-armed after the empty transcript
    await h.settle(created.id)
    assistant_turns = [t for t in (await h.detail(created.id)).turns if t.speaker is Speaker.ASSISTANT]
    assert len(assistant_turns) == 2
    await h.c.calls.end_internal(created.id, "test_done")


async def test_ending_the_call_closes_the_pipeline_and_later_audio_is_ignored(h: Harness, media_call):
    stt = media_call(FakeStt())
    created = await h.start()
    pipeline = h.c.calls._runtimes[created.id].pipeline
    await speak(h, created.id, voiced_ms=200, silence_ms=0)
    await h.c.calls.end_internal(created.id, "caller_hung_up")
    assert pipeline._closed and stt.streams and stt.streams[0].stopped
    await h.c.calls.caller_audio(created.id, VOICED, RATE)  # the runtime is gone: a harmless no-op


async def test_real_audio_with_a_simulated_recogniser_is_reported_not_silently_dropped(h: Harness):
    h.c.calls.sim_telephony.capabilities = replace(SIMULATOR_CAPABILITIES, receives_caller_audio=True)  # type: ignore[misc]
    created = await h.start()
    await h.idle(created.id)
    rt = h.c.calls._runtimes[created.id]
    assert rt.pipeline is None and not h.c.calls.audio_expected(created.id)
    events = await h.c.calls.events(OWNER, created.id, 0)
    problems = [e for e in events if e.type == "provider.error"]
    assert problems and problems[0].data["degraded"] is True
    assert "speech recognition is simulated" in problems[0].data["message"]
    await h.c.calls.end_internal(created.id, "test_done")
