"""Caller audio -> utterances -> turns, with a real energy VAD and a scripted recogniser."""

import asyncio

from tests.audio_fakes import RATE, SILENT, VOICED, FakeSink, FakeStream, FakeStt, Script

from sparta.providers.base import ProviderRejected, ProviderUnavailable, TranscriptEvent
from sparta.providers.vad.energy import EnergyVad
from sparta.services.audio_pipeline import AudioPipeline, PipelineConfig


def make(stt: FakeStt | None = None, sink: FakeSink | None = None, **cfg) -> tuple[AudioPipeline, FakeStt, FakeSink]:
    stt = stt or FakeStt()
    sink = sink or FakeSink()
    pipeline = AudioPipeline(
        call_id="call_1",
        sink=sink,
        stt=stt,
        vad=EnergyVad(),
        locales=lambda: (["en-IN", "hi-IN", "kn-IN"], "en-IN"),
        trace_id="trace",
        config=PipelineConfig(**cfg) if cfg else None,
    )
    return pipeline, stt, sink


async def say(pipeline: AudioPipeline, voiced_ms: int, silence_ms: int = 700) -> None:
    for _ in range(voiced_ms // 20):
        await pipeline.feed(VOICED, RATE)
    for _ in range(silence_ms // 20):
        await pipeline.feed(SILENT, RATE)


async def test_one_utterance_becomes_one_turn_and_keeps_the_audio_before_the_detected_start():
    pipeline, stt, sink = make()
    for _ in range(15):  # 300 ms of silence first
        await pipeline.feed(SILENT, RATE)
    await say(pipeline, voiced_ms=600)
    await pipeline.drain()
    assert sink.turns == [
        {"text": "tell me the otp", "language": "en-IN", "confidence": 0.9, "stt_ms": sink.turns[0]["stt_ms"]}
    ]
    assert sink.started == 1 and sink.errors == []
    (stream,) = stt.streams
    assert stream.stopped
    pushed_ms = sum(len(c) for c in stream.pushed) * 1000 // (RATE * 2)
    assert pushed_ms >= 600  # the whole spoken part
    assert stream.pushed[0] == SILENT  # ... preceded by pre-roll, so the first syllable is not clipped
    assert stt.calls == [{"locales": ["en-IN", "hi-IN", "kn-IN"], "hint": "en-IN", "rate": RATE}]
    await pipeline.aclose()


async def test_silence_alone_creates_no_utterance_and_buffers_only_a_short_pre_roll():
    pipeline, stt, sink = make()
    for _ in range(500):
        await pipeline.feed(SILENT, RATE)
    await pipeline.drain()
    assert stt.streams == [] and sink.turns == []
    assert pipeline._pre_roll_ms <= 330
    await pipeline.aclose()


async def test_speech_over_the_assistant_is_a_barge_in_and_stops_the_silence_timer():
    pipeline, _, sink = make(sink=FakeSink(speaking=1.4))
    await say(pipeline, voiced_ms=300, silence_ms=0)
    await asyncio.sleep(0)
    assert sink.barge_ins == 1 and sink.started == 1
    await say(pipeline, voiced_ms=200, silence_ms=700)  # more speech in the same utterance: no second barge-in
    await pipeline.drain()
    assert sink.barge_ins == 1
    await pipeline.aclose()


async def test_no_barge_in_when_the_assistant_is_silent():
    pipeline, _, sink = make(sink=FakeSink(speaking=0.0))
    await say(pipeline, voiced_ms=400)
    await pipeline.drain()
    assert sink.barge_ins == 0 and len(sink.turns) == 1
    await pipeline.aclose()


async def test_turns_are_delivered_in_speaking_order_even_when_the_recogniser_answers_out_of_order():
    slow = asyncio.Event()
    stt = FakeStt(Script(text="first", release=slow), Script(text="second"))
    pipeline, _, sink = make(stt)
    await say(pipeline, voiced_ms=400)
    await say(pipeline, voiced_ms=400)
    await asyncio.sleep(0.05)
    assert sink.turns == []  # the second answer is ready but must wait for the first
    slow.set()
    await pipeline.drain()
    assert [t["text"] for t in sink.turns] == ["first", "second"]
    await pipeline.aclose()


async def test_a_recogniser_that_cannot_start_is_reported_and_the_next_utterance_still_works():
    stt = FakeStt(start_error=ProviderUnavailable("fake-stt", "stt", "down"))
    pipeline, _, sink = make(stt)
    await say(pipeline, voiced_ms=400)
    await pipeline.drain()
    assert sink.turns == [] and sink.errors and sink.errors[0][0] == "stt"
    await say(pipeline, voiced_ms=400)
    await pipeline.drain()
    assert [t["text"] for t in sink.turns] == ["tell me the otp"]
    await pipeline.aclose()


async def test_a_failing_flush_is_reported_and_creates_no_turn():
    stt = FakeStt(Script(flush_error=ProviderRejected("fake-stt", "stt", "bad audio")))
    pipeline, _, sink = make(stt)
    await say(pipeline, voiced_ms=400)
    await pipeline.drain()
    assert sink.turns == [] and ("stt", "bad audio") in sink.errors
    assert sink.ended == [False]  # the call service is told to go back to waiting for the caller
    await pipeline.aclose()


async def test_an_empty_transcript_creates_no_turn_and_tells_the_service():
    pipeline, _, sink = make(FakeStt(Script(text="   ")))
    await say(pipeline, voiced_ms=400)
    await pipeline.drain()
    assert sink.turns == [] and sink.ended == [False]
    await pipeline.aclose()


async def test_a_long_monologue_is_recognised_in_pieces():
    pipeline, stt, sink = make(max_utterance_ms=400)
    await say(pipeline, voiced_ms=1500)
    await pipeline.drain()
    assert len(stt.streams) >= 3 and len(sink.turns) >= 3
    await pipeline.aclose()


async def test_partial_results_become_live_captions():
    pipeline, _, sink = make(FakeStt(Script(partial_text="tell me")))
    await say(pipeline, voiced_ms=500)
    await pipeline.drain()
    assert sink.partials == ["tell me"]
    await pipeline.aclose()


async def test_utterances_beyond_the_backlog_limit_are_dropped_and_reported():
    blocked = asyncio.Event()
    stt = FakeStt(Script(text="first", release=blocked), Script(text="second"))
    pipeline, _, sink = make(stt, max_pending_utterances=1)
    await say(pipeline, voiced_ms=400)
    await say(pipeline, voiced_ms=400)
    await asyncio.sleep(0.05)
    assert any("behind" in message for _, message in sink.errors)
    blocked.set()
    await pipeline.drain()
    assert [t["text"] for t in sink.turns] == ["first"]
    await pipeline.aclose()


async def test_the_confidence_is_the_weakest_final_and_the_language_the_first_known():
    class TwoFinals(FakeStream):
        async def flush(self) -> None:
            for text, language, confidence in (("tell me", None, 0.9), ("the code", "hi-IN", 0.6)):
                self._events.put_nowait(
                    TranscriptEvent(kind="final", text=text, language=language, confidence=confidence)
                )

    class TwoFinalsStt(FakeStt):
        async def start_stream(self, **kwargs):
            stream = TwoFinals(Script())
            self.streams.append(stream)
            return stream

    pipeline, _, sink = make(TwoFinalsStt())
    await say(pipeline, voiced_ms=400)
    await pipeline.drain()
    assert sink.turns[0]["text"] == "tell me the code"
    assert sink.turns[0]["language"] == "hi-IN" and sink.turns[0]["confidence"] == 0.6
    await pipeline.aclose()


async def test_closing_stops_the_open_stream_and_ignores_later_audio():
    pipeline, stt, sink = make()
    await say(pipeline, voiced_ms=300, silence_ms=0)  # still speaking
    await pipeline.aclose()
    assert stt.streams and stt.streams[0].stopped
    before = len(stt.streams[0].pushed)
    await pipeline.feed(VOICED, RATE)
    assert len(stt.streams[0].pushed) == before and sink.turns == []
    await pipeline.aclose()  # idempotent
