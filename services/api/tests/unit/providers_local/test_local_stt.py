"""The local faster-whisper provider: stream behaviour, languages, confidence, uploads. The engine is faked: no model needed."""

import asyncio
import io
import math
import struct
import threading
import time
import wave
from array import array
from collections.abc import AsyncIterator, Callable, Sequence

import pytest
import pytest_asyncio
from tests.audio_fakes import FakeSink

from sparta.config import Settings
from sparta.observability.metrics import PROVIDER_LATENCY_MS, Metrics
from sparta.providers.base import (
    ProviderError,
    ProviderRejected,
    ProviderUnavailable,
    TranscriptEvent,
    TranscriptResult,
    consumes_audio,
)
from sparta.providers.fake_tone import silence, tone
from sparta.providers.stt.local import (
    CONFIDENCE_CEILING,
    MAX_UTTERANCE_SECONDS,
    LocalSpeechToText,
    Recognition,
    canonical_locale,
    confidence_ceiling,
    english_only,
    estimate_confidence,
    locale_support,
    model_tier,
    pick_language,
    plan_languages,
)
from sparta.providers.vad.energy import EnergyVad
from sparta.services.audio_pipeline import AudioPipeline

MODEL_NOT_INSTALLED = "model 'small' is not installed: run `python -m sparta models fetch`"


class FakeEngine:
    """Stands in for faster-whisper: records what it was given and answers with a canned recognition."""

    def __init__(
        self,
        *,
        text: str = "hello there",
        language: str = "en",
        mean_logprob: float | None = -0.3,
        suspect: bool = False,
        problem: str | None = None,
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.text, self.language, self.mean_logprob, self.suspect = text, language, mean_logprob, suspect
        self.problem = problem
        self.delay = delay
        self.error = error
        self.calls: list[tuple[int, str | None, tuple[str, ...]]] = []
        self.loaded = self.warmed = 0
        self.closed = False
        self.active = self.peak = 0
        self._lock = threading.Lock()

    def unavailable(self) -> str | None:
        return self.problem

    def load(self) -> None:
        self.loaded += 1

    def warm(self) -> None:
        self.warmed += 1

    def recognise(self, pcm16_16k: bytes, forced: str | None, candidates: Sequence[str]) -> Recognition:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.calls.append((len(pcm16_16k), forced, tuple(candidates)))
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            # a forced language is the one used; otherwise this is the language "detected" among the candidates
            return Recognition(self.text, forced or self.language, self.mean_logprob, self.suspect)
        finally:
            with self._lock:
                self.active -= 1

    def close(self) -> None:
        self.closed = True


def speech(ms: int = 1000, rate: int = 8000) -> bytes:
    return tone(440.0, ms, rate, 8000)


def samples_of(pcm: bytes) -> "array[int]":
    out = array("h")
    out.frombytes(pcm)
    return out


async def recognise(
    stt: LocalSpeechToText,
    audio: bytes,
    *,
    candidates: Sequence[str] = ("en-IN",),
    hint: str | None = None,
    rate: int = 8000,
) -> list[TranscriptEvent]:
    stream = await stt.start_stream(candidate_locales=candidates, locale_hint=hint, trace_id="t", sample_rate=rate)
    step = rate // 50 * 2  # 20 ms frames
    for start in range(0, len(audio), step):
        await stream.push_audio(audio[start : start + step])
    await stream.flush()
    return [event async for event in stream.events()]  # it ends without stop_stream: the utterance is over


async def start(stt: LocalSpeechToText, candidates: Sequence[str], hint: str | None, rate: int = 8000) -> object:
    return await stt.start_stream(candidate_locales=candidates, locale_hint=hint, trace_id="t", sample_rate=rate)


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest_asyncio.fixture
async def make_stt(make_settings: Callable[..., Settings]) -> AsyncIterator[Callable[..., LocalSpeechToText]]:
    created: list[LocalSpeechToText] = []

    def make(engine: FakeEngine, *, metrics: Metrics | None = None, **overrides: object) -> LocalSpeechToText:
        stt = LocalSpeechToText(make_settings(**overrides), engine=engine, metrics=metrics)
        created.append(stt)
        return stt

    yield make
    for stt in created:
        await stt.aclose()


# ------------------------------------------------------------------------------------------------ the stream
async def test_an_utterance_gives_exactly_one_final_event_and_then_ends(make_stt, engine):
    stt = make_stt(engine)
    events = await recognise(stt, speech(1500))
    assert [(e.kind, e.text, e.language) for e in events] == [("final", "hello there", "en-IN")]
    assert events[0].duration_ms == 1500 and events[0].offset_ms == 0
    assert consumes_audio(stt) is True
    assert stt.meta.provider == "local-faster-whisper" and stt.meta.simulated is False and stt.meta.model == "small"


async def test_caller_audio_reaches_the_engine_at_16_khz_without_touching_disk(make_stt, engine, tmp_path, monkeypatch):
    work = tmp_path / "cwd"
    scratch = tmp_path / "tmp"
    work.mkdir()
    scratch.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    stt = make_stt(engine)
    await recognise(stt, speech(1000, 8000), rate=8000)
    await recognise(stt, speech(500, 16000), rate=16000)
    await recognise(stt, speech(500, 24000), rate=24000)
    assert [length for length, _, _ in engine.calls] == [32000, 16000, 16000]  # 1 s, 0.5 s and 0.5 s of 16 kHz PCM16
    assert list(work.iterdir()) == [] and list(scratch.iterdir()) == []


async def test_a_flush_ends_the_utterance_and_a_stopped_stream_says_nothing(make_stt, engine):
    stt = make_stt(engine)
    stream = await stt.start_stream(candidate_locales=["en-IN"], locale_hint=None, trace_id="t", sample_rate=8000)
    await stream.push_audio(speech(500))
    await stream.flush()
    await stream.flush()  # the utterance is over: a second flush must not recognise anything again
    await stream.push_audio(speech(500))
    assert [e.text async for e in stream.events()] == ["hello there"]
    assert len(engine.calls) == 1

    stopped = await stt.start_stream(candidate_locales=["en-IN"], locale_hint=None, trace_id="t", sample_rate=8000)
    await stopped.push_audio(speech(500))
    await stopped.stop_stream()
    await stopped.flush()
    assert [e async for e in stopped.events()] == []
    assert len(engine.calls) == 1


async def test_a_stop_while_the_engine_is_busy_drops_the_result(make_stt):
    stt = make_stt(FakeEngine(delay=0.1))
    stream = await stt.start_stream(candidate_locales=["en-IN"], locale_hint=None, trace_id="t", sample_rate=8000)
    await stream.push_audio(speech(500))
    flushing = asyncio.ensure_future(stream.flush())
    await asyncio.sleep(0.02)
    await stream.stop_stream()
    await flushing
    assert [e async for e in stream.events()] == []


async def test_nothing_said_means_an_empty_final_with_zero_confidence_and_no_recognition(make_stt, engine):
    stt = make_stt(engine)
    for audio in (b"", speech(60), silence(1500, 8000), b"\x01"):  # empty, under 100 ms, digital silence, half a sample
        (event,) = await recognise(stt, audio)
        assert (event.kind, event.text, event.confidence) == ("final", "", 0.0)
    assert engine.calls == []


async def test_text_that_comes_back_blank_is_an_empty_final(make_stt):
    stt = make_stt(FakeEngine(text="  "))
    (event,) = await recognise(stt, speech())
    assert (event.text, event.confidence, event.language) == ("", 0.0, None)


async def test_the_utterance_buffer_is_bounded(make_stt, engine):
    stt = make_stt(engine)
    stream = await stt.start_stream(candidate_locales=["en-IN"], locale_hint=None, trace_id="t", sample_rate=8000)
    second = 8000 * 2
    for _ in range(MAX_UTTERANCE_SECONDS):
        await stream.push_audio(bytes(second))
    with pytest.raises(ProviderRejected, match="maximum buffered audio"):
        await stream.push_audio(bytes(second))
    await stream.flush()  # the buffer was dropped: nothing is left to recognise
    assert [e.text async for e in stream.events()] == [""]
    assert engine.calls == []


@pytest.mark.parametrize("rate", [4000, 7999, 48001, 96000])
async def test_an_unsupported_sample_rate_is_refused_up_front(make_stt, engine, rate):
    with pytest.raises(ProviderRejected, match="sample rate"):
        await start(make_stt(engine), ["en-IN"], None, rate)


async def test_an_engine_failure_surfaces_from_flush_and_the_stream_still_ends(make_stt):
    stt = make_stt(FakeEngine(error=ProviderUnavailable("local-faster-whisper", "stt", "model blew up")))
    stream = await stt.start_stream(candidate_locales=["en-IN"], locale_hint=None, trace_id="t", sample_rate=8000)
    await stream.push_audio(speech())
    with pytest.raises(ProviderError, match="model blew up"):
        await stream.flush()
    assert [e async for e in stream.events()] == []


async def test_recognition_runs_in_a_bounded_pool(make_stt):
    for workers in (1, 2):
        engine = FakeEngine(delay=0.05)
        stt = make_stt(engine, local_max_concurrent_inference=workers)
        await asyncio.gather(*(recognise(stt, speech(300)) for _ in range(6)))
        assert len(engine.calls) == 6
        assert engine.peak == workers


async def test_the_event_loop_keeps_running_while_a_recognition_is_in_progress(make_stt):
    stt = make_stt(FakeEngine(delay=0.3))
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.ensure_future(ticker())
    await recognise(stt, speech(500))
    task.cancel()
    assert ticks >= 15  # about 30 ticks fit into the 300 ms the engine takes


async def test_the_recognition_latency_is_recorded(make_stt, engine):
    metrics = Metrics()
    await recognise(make_stt(engine, metrics=metrics), speech())
    assert len(metrics.samples(PROVIDER_LATENCY_MS, provider="local-faster-whisper", stage="stt_inference")) == 1


# ---------------------------------------------------------------------------------------------- languages
async def test_a_hint_forces_that_language_and_names_the_requested_variant(make_stt, engine):
    stt = make_stt(engine)
    (event,) = await recognise(stt, speech(), candidates=["en-IN", "hi-IN", "kn-IN"], hint="HI-in")
    assert engine.calls[-1][1:] == ("hi", ("hi",))
    assert event.language == "hi-IN"


async def test_without_a_hint_the_language_is_chosen_among_the_candidates_only(make_stt):
    engine = FakeEngine(language="hi")
    stt = make_stt(engine)
    (event,) = await recognise(stt, speech(), candidates=["en-IN", "hi-IN", "ta-IN", "en-GB"])
    assert engine.calls[-1][1:] == (None, ("en", "hi"))  # Tamil is not offered; the first English variant is kept
    assert event.language == "hi-IN"
    engine.language = "en"
    (event,) = await recognise(stt, speech(), candidates=["en-GB", "hi-IN"])
    assert event.language == "en-GB"  # reported as the variant the caller named, not as a default


async def test_one_candidate_language_needs_no_detection_and_none_means_all_three(make_stt, engine):
    stt = make_stt(engine)
    await recognise(stt, speech(), candidates=["kn-IN"])
    assert engine.calls[-1][1:] == ("kn", ("kn",))
    await recognise(stt, speech(), candidates=[])
    assert engine.calls[-1][1:] == (None, ("en", "hi", "kn"))
    await recognise(stt, speech(), candidates=["auto", "en-IN"], hint="und")
    assert engine.calls[-1][1:] == ("en", ("en",))


@pytest.mark.parametrize(
    ("candidates", "hint"),
    [
        (["en-IN"], "ta-IN"),
        (["ta-IN", "te-IN"], None),
        (["en-IN"], "not a locale"),
        (["e"], None),
        (["en-IN"], "hi_IN"),
    ],
)
async def test_what_cannot_be_recognised_is_refused_when_the_stream_starts(make_stt, engine, candidates, hint):
    with pytest.raises(ProviderRejected):
        await start(make_stt(engine), candidates, hint)


async def test_an_english_only_model_cannot_be_asked_for_hindi_or_kannada(make_stt, engine):
    stt = make_stt(engine, local_stt_model="small.en")
    assert await start(stt, ["en-IN", "hi-IN"], None) is not None  # English is the only candidate left
    assert engine.calls == []
    with pytest.raises(ProviderRejected, match="cannot recognise hi-IN"):
        await start(stt, ["en-IN"], "hi-IN")
    with pytest.raises(ProviderRejected, match="none of the candidate languages"):
        await start(stt, ["hi-IN", "kn-IN"], None)
    assert stt.locale_support("hi-IN") == "unsupported" and stt.locale_support("en-IN") == "supported"


def test_plan_languages_reports_locales_in_canonical_form():
    plan = plan_languages(["en-in", "HI-IN", "kn"], None, "small")
    assert dict(plan.locales) == {"en": "en-IN", "hi": "hi-IN", "kn": "kn"} and plan.forced is None
    assert canonical_locale("zh-hant-tw") == "zh-Hant-TW" and canonical_locale("EN") == "en"


def test_the_language_picked_is_the_best_candidate_whatever_whisper_prefers_overall():
    probs = [("ur", 0.50), ("hi", 0.30), ("en", 0.15), ("kn", 0.05)]  # Urdu is Whisper's top guess for Hindi speech
    language, probability = pick_language(probs, ("en", "hi", "kn"))
    assert language == "hi" and probability == pytest.approx(0.30 / 0.50)
    assert pick_language([("ur", 0.9)], ("en", "kn")) == (
        "en",
        0.0,
    )  # nothing known about the candidates: the first one
    assert pick_language([("en", 0.2), ("hi", 0.2)], ("hi", "en"))[0] == "hi"  # a tie goes to the earlier candidate


# ------------------------------------------------------------------------------------------- confidence
@pytest.mark.parametrize(
    ("language", "model", "ceiling"),
    [
        ("en-IN", "small", 0.95),
        ("en-US", "large-v3", 0.95),
        ("hi-IN", "small", 0.80),
        ("hi-IN", "large-v3-turbo", 0.80),
        ("kn-IN", "small", 0.50),
        ("kn-IN", "tiny", 0.50),
        ("kn-IN", "medium", 0.50),
        ("kn-IN", "large-v3", 0.70),
        ("kn-IN", "large-v3-turbo", 0.70),
        ("kn-IN", "something-unlisted", 0.50),  # a model that is not in the table counts as small
        ("kn-IN", "/opt/models/large-v3-turbo", 0.70),  # a directory is looked up by its folder name
        ("kn-IN", "faster-whisper-large-v3", 0.70),
        ("kn-IN", "distil-large-v3", 0.50),
    ],
)
def test_the_confidence_ceiling_per_language_and_model(language, model, ceiling):
    assert confidence_ceiling(language, model) == ceiling
    assert estimate_confidence(-0.001, locale=language, model=model) == pytest.approx(ceiling, abs=0.002)


def test_kannada_from_a_small_model_is_always_below_the_poor_audio_threshold():
    for model in ("tiny", "base", "small", "medium", "unknown"):
        assert estimate_confidence(0.0, locale="kn-IN", model=model) < 0.55  # even a perfect log-probability
    assert estimate_confidence(0.0, locale="kn-IN", model="large-v3") > 0.55


def test_the_ceiling_table_is_the_documented_one():
    assert {lang: dict(row) for lang, row in CONFIDENCE_CEILING.items()} == {
        "en": {"small": 0.95, "medium": 0.95, "large": 0.95},
        "hi": {"small": 0.80, "medium": 0.80, "large": 0.80},
        "kn": {"small": 0.50, "medium": 0.50, "large": 0.70},
    }
    names = ("tiny.en", "small", "medium.en", "large-v1", "turbo", "x")
    assert [model_tier(m) for m in names] == ["small", "small", "medium", "large", "large", "small"]
    assert english_only("small.en") and english_only("distil-large-v3") and not english_only("small")


def test_the_heuristic_is_exp_of_the_mean_logprob_and_can_only_lower_trust():
    assert estimate_confidence(-0.5, locale="en-IN", model="small") == pytest.approx(math.exp(-0.5))
    assert estimate_confidence(-3.0, locale="en-IN", model="small") == pytest.approx(math.exp(-3.0))
    assert estimate_confidence(-0.1, locale="hi-IN", model="small") == 0.80  # exp(-0.1) = 0.905 is capped
    assert (
        estimate_confidence(0.7, locale="en-IN", model="small") == 0.95
    )  # a positive log-probability clips to 1 first
    for bad in (None, math.nan, math.inf, -math.inf):
        assert estimate_confidence(bad, locale="en-IN", model="small") == 0.0


def test_whispers_own_failure_indicators_cap_the_confidence():
    # a confident repetition loop, or a segment Whisper thinks is not speech, must not read as a trustworthy transcript
    assert estimate_confidence(-0.05, locale="en-IN", model="small", suspect=True) == 0.30
    assert estimate_confidence(-3.0, locale="en-IN", model="small", suspect=True) == pytest.approx(math.exp(-3.0))


@pytest.mark.parametrize(
    ("locale", "model", "support"),
    [
        ("en-IN", "small", "supported"),
        ("hi-IN", "small", "experimental"),
        ("kn-IN", "small", "unsupported"),
        ("kn-IN", "medium", "unsupported"),
        ("kn-IN", "large-v3-turbo", "experimental"),
        ("hi-IN", "large-v3", "experimental"),
        ("ta-IN", "large-v3", "unsupported"),
        ("en-IN", "small.en", "supported"),
        ("hi-IN", "small.en", "unsupported"),
    ],
)
def test_locale_support(locale, model, support):
    assert locale_support(locale, model) == support


@pytest.mark.parametrize(
    ("model", "hint", "logprob", "expected"),
    [
        ("small", None, -0.1, 0.50),  # Kannada from small is capped at 0.50 whatever the log-probability
        ("small", "kn-IN", -0.1, 0.50),
        ("large-v3", None, -0.1, 0.70),
        ("large-v3", "kn-IN", -0.1, 0.70),
        ("large-v3", None, -0.9, math.exp(-0.9)),  # a weak log-probability is below the ceiling and wins
    ],
)
async def test_confidence_follows_the_language_and_the_model(make_stt, model, hint, logprob, expected):
    stt = make_stt(FakeEngine(language="kn", mean_logprob=logprob), local_stt_model=model)
    (event,) = await recognise(stt, speech(), candidates=["en-IN", "kn-IN"], hint=hint)
    assert event.language == "kn-IN"
    assert event.confidence == pytest.approx(expected)


# ----------------------------------------------------------------------------------------- availability
async def test_the_local_recogniser_works_through_the_real_audio_pipeline_at_telephone_rate(make_stt):
    engine = FakeEngine(text="tell me the otp", language="hi", mean_logprob=-0.3)
    stt = make_stt(engine)
    sink = FakeSink()
    pipeline = AudioPipeline(
        call_id="call_1",
        sink=sink,
        stt=stt,
        vad=EnergyVad(),
        locales=lambda: (["en-IN", "hi-IN", "kn-IN"], None),
        trace_id="trace",
    )
    voiced, quiet = speech(20), silence(20, 8000)
    for _ in range(15):
        await pipeline.feed(quiet, 8000)  # 300 ms of line noise floor first
    for _ in range(40):
        await pipeline.feed(voiced, 8000)  # 800 ms of talking
    for _ in range(35):
        await pipeline.feed(quiet, 8000)  # then the caller stops: the detector ends the utterance
    await pipeline.drain()
    (turn,) = sink.turns
    assert (turn["text"], turn["language"]) == ("tell me the otp", "hi-IN")
    assert turn["confidence"] == pytest.approx(math.exp(-0.3)) and turn["stt_ms"] >= 0.0
    assert sink.errors == [] and sink.started == 1
    (call,) = engine.calls
    assert (
        call[1:] == (None, ("en", "hi", "kn")) and call[0] >= 32000
    )  # at least 1 s of 16 kHz PCM16 (speech + pre-roll)
    await pipeline.aclose()


async def test_a_missing_model_is_reported_by_the_pipeline_as_a_provider_error_not_a_crash(make_stt):
    stt = make_stt(FakeEngine(problem=MODEL_NOT_INSTALLED))
    sink = FakeSink()
    pipeline = AudioPipeline(
        call_id="call_1", sink=sink, stt=stt, vad=EnergyVad(), locales=lambda: (["en-IN"], "en-IN"), trace_id="trace"
    )
    for _ in range(40):
        await pipeline.feed(speech(20), 8000)
    for _ in range(35):
        await pipeline.feed(silence(20, 8000), 8000)
    await pipeline.drain()
    assert sink.turns == [] and sink.errors and sink.errors[0] == ("stt", MODEL_NOT_INSTALLED)
    await pipeline.aclose()


# ----------------------------------------------------------------------------------------- availability
async def test_a_missing_model_is_refused_with_the_fix_and_never_downloaded(make_stt, no_network):
    stt = make_stt(FakeEngine(problem=MODEL_NOT_INSTALLED))
    with pytest.raises(ProviderUnavailable, match=MODEL_NOT_INSTALLED):
        await start(stt, ["en-IN"], None)
    assert stt.ready() == MODEL_NOT_INSTALLED and no_network == []


async def test_warmup_loads_the_model_and_runs_once(make_stt, engine):
    seconds = await make_stt(engine).warmup()
    assert seconds >= 0.0 and (engine.loaded, engine.warmed) == (1, 1)


async def test_a_closed_recogniser_refuses_new_work_and_closes_the_engine(make_stt, engine):
    stt = make_stt(engine)
    await stt.aclose()
    assert engine.closed
    with pytest.raises(ProviderUnavailable, match="closed"):
        await start(stt, ["en-IN"], None)
    with pytest.raises(ProviderUnavailable, match="closed"):
        await stt.warmup()


# ------------------------------------------------------------------------------------------------ uploads
def wav(frames: bytes, *, rate: int = 8000, channels: int = 1, width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(frames)
    return buffer.getvalue()


async def upload(
    stt: LocalSpeechToText,
    audio: bytes,
    content_type: str = "audio/wav",
    *,
    locale_hint: str | None = None,
    transcript_hint: str | None = None,
) -> TranscriptResult:
    return await stt.transcribe(
        audio,
        content_type=content_type,
        candidate_locales=["en-IN", "hi-IN"],
        locale_hint=locale_hint,
        trace_id="t",
        transcript_hint=transcript_hint,
    )


async def test_a_wav_upload_is_recognised_in_memory_through_the_same_path(make_stt, engine):
    stt = make_stt(engine)
    result = await upload(stt, wav(speech(2000, 8000)), "audio/x-wav; charset=binary", transcript_hint="ignored")
    assert (result.text, result.language, result.simulated) == ("hello there", "en-IN", False)
    assert result.confidence == pytest.approx(math.exp(-0.3))
    assert result.audio_seconds == pytest.approx(2.0) and result.usage.audio_seconds == pytest.approx(2.0)
    assert [(s.kind, s.text) for s in result.segments] == [("final", "hello there")]
    assert engine.calls[-1][0] == 64000  # 2 s at 16 kHz: the 8 kHz clip was resampled


async def test_a_stereo_wav_is_mixed_down_and_other_widths_are_refused(make_stt, engine):
    stt = make_stt(engine)
    both = array("h")
    for value in samples_of(speech(1000, 16000)):
        both.extend((value, value))
    await upload(stt, wav(both.tobytes(), rate=16000, channels=2))
    assert engine.calls[-1][0] == 32000  # one channel remains: 1 s at 16 kHz
    with pytest.raises(ProviderRejected, match="16-bit PCM"):
        await upload(stt, wav(bytes(3 * 8000), rate=8000, width=3))
    with pytest.raises(ProviderRejected, match="sample rate"):
        await upload(stt, wav(bytes(2 * 4000), rate=4000))


async def test_raw_l16_is_big_endian_and_needs_a_rate(make_stt, engine):
    stt = make_stt(engine)
    big = samples_of(speech(1000, 16000))
    big.byteswap()
    result = await upload(stt, big.tobytes(), "audio/L16; rate=16000; channels=1")
    assert result.text == "hello there" and engine.calls[-1][0] == 32000
    with pytest.raises(ProviderRejected, match="rate parameter"):
        await upload(stt, big.tobytes(), "audio/L16")
    with pytest.raises(ProviderRejected, match="mono"):
        await upload(stt, big.tobytes(), "audio/L16; rate=16000; channels=2")


async def test_unreadable_or_unsupported_uploads_are_rejected_not_guessed_at(make_stt, engine):
    stt = make_stt(engine, max_audio_bytes=100_000, max_audio_seconds=2)
    for audio, content_type in [
        (b"OggS" + bytes(500), "audio/ogg"),
        (b"\x1a\x45\xdf\xa3" + bytes(500), "audio/webm"),
        (b"not a wav file at all", "audio/wav"),
        (b"RIFF\x00\x00\x00\x00WAVEjunk", "audio/wav"),
        (b"", "audio/wav"),
        (wav(speech(500)), "text/plain"),
        (wav(bytes(200_000), rate=8000), "audio/wav"),  # larger than max_audio_bytes
        (wav(bytes(2 * 8000 * 3), rate=8000), "audio/wav"),  # 3 s is longer than 2 s
    ]:
        with pytest.raises(ProviderRejected):
            await upload(stt, audio, content_type)
    assert engine.calls == []


async def test_a_clip_with_no_speech_gives_empty_text_and_a_missing_model_is_unavailable(make_stt, engine):
    result = await upload(make_stt(engine), wav(silence(1000, 8000)))
    assert (result.text, result.confidence, result.segments) == ("", 0.0, [])
    with pytest.raises(ProviderUnavailable):
        await upload(make_stt(FakeEngine(problem=MODEL_NOT_INSTALLED)), wav(speech()))


async def test_a_header_that_lies_about_its_length_cannot_make_the_decoder_over_read(make_stt, engine):
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 0xFFFFFFFF, b"WAVE", b"fmt ", 16, 1, 1, 8000, 16000, 2, 16, b"data", 0xFFFFFFFF
    )
    result = await upload(make_stt(engine), header + speech(500, 8000))
    assert result.text == "hello there" and result.audio_seconds == pytest.approx(0.5)
