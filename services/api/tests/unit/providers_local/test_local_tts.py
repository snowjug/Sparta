"""The local Piper provider: voices, formats, framing, streaming, stopping. Piper is faked: no voice file needed."""

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
import types
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
import pytest_asyncio

from sparta.config import Settings
from sparta.observability.metrics import AUDIO_SECONDS, PROVIDER_LATENCY_MS, Metrics
from sparta.providers.base import (
    AudioChunk,
    ProviderError,
    ProviderRejected,
    ProviderUnavailable,
    SynthesisRequest,
    produces_audio,
)
from sparta.providers.fake_tone import tone
from sparta.providers.local_models import ModelFile, ModelSpec
from sparta.providers.tts import local as local_tts
from sparta.providers.tts.local import CHUNK_MS, FRAME_MS, LocalTextToSpeech, load_piper_voice

VOICES = "en-IN=test_en,hi-IN=test_hi,kn-IN=test_kn"


class FakeVoice:
    """A loaded voice: yields one tone per sentence at 22,050 Hz, optionally slowly, and counts what it did."""

    sample_rate = 22050

    def __init__(
        self, sentences_ms: tuple[int, ...] = (300, 200), *, delay: float = 0.0, fail_on: int | None = None
    ) -> None:
        self.sentences_ms = sentences_ms
        self.delay = delay
        self.fail_on = fail_on
        self.started = self.finished = self.active = self.peak = 0
        self.texts: list[str] = []
        self.speeds: list[float] = []
        self._lock = threading.Lock()

    def sentences(self, text: str, speed: float) -> Iterator[bytes]:
        self.texts.append(text)
        self.speeds.append(speed)
        for index, ms in enumerate(self.sentences_ms):
            with self._lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
                self.started += 1
            try:
                time.sleep(self.delay)
                if self.fail_on == index:
                    raise RuntimeError(r"espeak exploded at C:\secret\place")
            finally:
                with self._lock:
                    self.active -= 1
            with self._lock:
                self.finished += 1
            yield tone(220.0, ms, self.sample_rate, 8000)


class FakeLoader:
    """What the provider calls to load a voice: records the files it was given and hands out one shared fake voice."""

    def __init__(self, voice: FakeVoice | None = None, *, error: Exception | None = None) -> None:
        self.voice = voice or FakeVoice()
        self.error = error
        self.loaded: list[tuple[str, Path]] = []

    def __call__(self, onnx: Path, config: Path) -> FakeVoice:
        assert config.name == f"{onnx.name}.json" and onnx.parent.name == onnx.stem
        if self.error is not None:
            raise self.error
        self.loaded.append((onnx.stem, onnx))
        return self.voice


def install(settings: Settings, *voice_ids: str) -> None:
    for voice_id in voice_ids:
        folder = Path(settings.local_model_dir) / "tts" / voice_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{voice_id}.onnx").write_bytes(b"onnx")
        (folder / f"{voice_id}.onnx.json").write_text("{}", encoding="utf-8")


def request(text: str = "Hello there. Goodbye.", locale: str = "en-IN", **overrides: Any) -> SynthesisRequest:
    values: dict[str, Any] = {"text": text, "locale": locale, "voice_id": None, "output_format": "pcm16_8k"}
    values.update(overrides)
    return SynthesisRequest(**values)


async def collect(tts: LocalTextToSpeech, req: SynthesisRequest) -> list[AudioChunk]:
    return [chunk async for chunk in tts.synthesize_stream(req)]


@pytest_asyncio.fixture
async def make_tts(
    make_settings: Callable[..., Settings],
) -> AsyncIterator[Callable[..., tuple[LocalTextToSpeech, FakeLoader]]]:
    created: list[LocalTextToSpeech] = []

    def make(
        loader: FakeLoader | None = None,
        *,
        voices: str = VOICES,
        installed: tuple[str, ...] = ("test_en", "test_hi"),
        **kw: Any,
    ) -> tuple[LocalTextToSpeech, FakeLoader]:
        metrics = kw.pop("metrics", None)
        settings = make_settings(local_tts_voices=voices, **kw)
        install(settings, *installed)
        loader = loader or FakeLoader()
        tts = LocalTextToSpeech(settings, metrics=metrics, loader=loader)
        created.append(tts)
        return tts, loader

    yield make
    for tts in created:
        await tts.aclose()


# --------------------------------------------------------------------------------------- formats and framing
@pytest.mark.parametrize(("name", "rate"), [("pcm16_8k", 8000), ("pcm16_16k", 16000), ("pcm16_24k", 24000)])
async def test_audio_comes_in_the_requested_rate_in_whole_40_ms_chunks(make_tts, name, rate):
    tts, _ = make_tts()
    chunks = await collect(tts, request(output_format=name))
    chunk_bytes = rate * CHUNK_MS // 1000 * 2
    frame_bytes = rate * FRAME_MS // 1000 * 2
    assert all(c.sample_rate == rate and c.encoding == "pcm16" for c in chunks)
    assert [c.seq for c in chunks] == list(range(len(chunks)))
    assert [c.final for c in chunks] == [False] * (len(chunks) - 1) + [True]
    assert all(len(c.data) == chunk_bytes for c in chunks[:-1])
    assert 0 < len(chunks[-1].data) <= chunk_bytes and len(chunks[-1].data) % frame_bytes == 0  # padded to whole frames
    seconds = sum(len(c.data) for c in chunks) / (2 * rate)
    assert seconds == pytest.approx(0.5, abs=0.03)  # 300 ms + 200 ms of speech, plus at most one frame of padding
    assert produces_audio(tts) is True and tts.meta.provider == "local-piper" and tts.meta.simulated is False


async def test_the_audio_is_the_voice_resampled_not_just_relabelled(make_tts):
    tts, _ = make_tts()
    audio = b"".join(c.data for c in await collect(tts, request(output_format="pcm16_8k")))
    peak = max(abs(int.from_bytes(audio[i : i + 2], "little", signed=True)) for i in range(0, len(audio), 2))
    assert 7000 < peak < 9000  # the 8,000-amplitude 220 Hz tone survives the 22,050 -> 8,000 Hz conversion


@pytest.mark.parametrize("name", ["mulaw_8k", "alaw_8k"])
async def test_companded_formats_are_refused(make_tts, name):
    tts, loader = make_tts()
    with pytest.raises(ProviderRejected, match="16-bit PCM"):
        await collect(tts, request(output_format=name))
    assert loader.loaded == []


async def test_unusable_requests_are_refused_before_anything_is_loaded(make_tts):
    tts, loader = make_tts()
    for bad in (
        request(text=""),
        request(text="   \n"),
        request(text="x" * 2001),
        request(rate=float("nan")),
        request(rate=float("inf")),
    ):
        with pytest.raises(ProviderRejected):
            await collect(tts, bad)
    assert loader.loaded == []


async def test_control_characters_are_stripped_and_the_speaking_rate_is_clamped(make_tts):
    tts, loader = make_tts()
    for rate in (0.1, 1.2, 9.0):
        await collect(tts, request(text="Hel\x00lo\x07 world", rate=rate))
    voice = loader.voice
    assert set(voice.texts) == {"Hello world"} and voice.speeds == [0.5, 1.2, 2.0]


# --------------------------------------------------------------------------------------------- voice choice
@pytest.mark.parametrize(
    ("locale", "voice_id", "expected"),
    [
        ("en-IN", None, "test_en"),
        ("hi-IN", None, "test_hi"),
        ("hi-in", None, "test_hi"),
        ("en-US", None, "test_en"),  # the same language, another region
        ("en-IN", "en-IN-NeerjaNeural", "test_en"),  # an Azure voice name is not a local voice: the locale decides
        ("hi-IN", "hi-IN-SwaraNeural", "test_hi"),
        ("en-IN", "test_en", "test_en"),
        ("en-IN", "test_hi", "test_en"),  # a voice for another language is never used to read this one
        ("en-IN", "../../etc/passwd", "test_en"),  # a request can never name a path
    ],
)
async def test_the_voice_comes_from_the_locale_unless_the_request_names_a_local_voice_for_that_language(
    make_tts, locale, voice_id, expected
):
    tts, loader = make_tts()
    await collect(tts, request(locale=locale, voice_id=voice_id))
    assert [name for name, _ in loader.loaded] == [expected]


async def test_a_known_local_voice_for_the_language_is_honoured(make_tts):
    tts, loader = make_tts(voices="en-IN=test_en,en-GB=test_en2", installed=("test_en", "test_en2"))
    await collect(tts, request(locale="en-GB", voice_id="test_en"))  # either voice reads English
    assert [name for name, _ in loader.loaded] == ["test_en"]


@pytest.mark.parametrize(
    ("locale", "installed"),
    [("kn-IN", ("test_en", "test_hi")), ("hi-IN", ("test_en",)), ("ta-IN", ("test_en", "test_hi")), ("", ("test_en",))],
)
async def test_a_locale_without_an_installed_voice_is_refused_never_spoken_in_another_language(
    make_tts, locale, installed
):
    tts, loader = make_tts(installed=installed, local_tts_fallback_locale="en-IN")
    with pytest.raises(ProviderRejected) as raised:
        await collect(tts, request(text="\u0928\u092e\u0938\u094d\u0924\u0947", locale=locale))
    assert raised.value.message == f"no local voice installed for {locale}"
    assert loader.loaded == [] and loader.voice.texts == []


async def test_a_voice_named_for_another_locale_is_not_the_fallback_either(make_tts):
    tts, loader = make_tts(voices="en-IN=test_en,kn-IN=test_kn", installed=("test_en",))
    with pytest.raises(ProviderRejected, match="no local voice installed for kn-IN"):
        await collect(tts, request(locale="kn-IN", voice_id="test_en"))
    assert loader.loaded == []


# ------------------------------------------------------------------------------------------------- streaming
async def test_the_first_chunk_does_not_wait_for_the_later_sentences(make_tts):
    voice = FakeVoice((400, 400, 400), delay=0.2)
    tts, _ = make_tts(FakeLoader(voice))
    started = time.perf_counter()
    stream = tts.synthesize_stream(request())
    first = await anext(stream)
    elapsed = time.perf_counter() - started
    assert first.seq == 0 and elapsed < 0.5  # one sentence took 0.2 s: not all three (0.6 s)
    await asyncio.sleep(0.5)
    assert voice.started == 2  # one sentence ahead of the one being played, no more
    await stream.aclose()


async def test_the_next_sentence_is_made_while_the_current_one_plays_so_there_is_no_gap(make_tts):
    voice = FakeVoice((300, 300, 300), delay=0.1)
    tts, _ = make_tts(FakeLoader(voice))
    stream = tts.synthesize_stream(request())
    await anext(stream)
    await asyncio.sleep(0.4)  # the caller is listening to the first sentence
    assert voice.finished == 2  # the second sentence is ready before the first has been heard
    chunks = [await anext(stream) for _ in range(5)]
    assert all(len(c.data) == 8000 * CHUNK_MS // 1000 * 2 for c in chunks)
    await stream.aclose()


async def test_the_event_loop_keeps_running_while_sentences_are_made(make_tts):
    tts, _ = make_tts(FakeLoader(FakeVoice((300, 300), delay=0.2)))
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.ensure_future(ticker())
    await collect(tts, request())
    task.cancel()
    assert ticks >= 20  # about 40 ticks fit into the 0.4 s of synthesis


async def test_syntheses_share_a_bounded_pool(make_tts):
    for workers in (1, 2):
        voice = FakeVoice((200, 200), delay=0.05)
        tts, _ = make_tts(FakeLoader(voice), local_max_concurrent_inference=workers)
        await asyncio.gather(*(collect(tts, request()) for _ in range(4)))
        assert voice.peak == workers


async def test_a_voice_that_fails_mid_text_delivers_what_it_made_then_a_sanitised_error(make_tts):
    tts, _ = make_tts(FakeLoader(FakeVoice((300, 300), fail_on=1)))
    chunks: list[AudioChunk] = []

    async def drain() -> None:
        async for chunk in tts.synthesize_stream(request()):
            chunks.append(chunk)

    with pytest.raises(ProviderError) as raised:
        await drain()
    assert raised.value.message == "speech synthesis failed" and "secret" not in str(raised.value)
    assert len(chunks) > 0 and not any(c.final for c in chunks)


async def test_a_voice_that_cannot_be_loaded_is_unavailable_without_details(make_tts, caplog):
    tts, _ = make_tts(FakeLoader(error=ValueError(r"bad file C:\secret\voice.onnx")))
    with caplog.at_level(logging.ERROR, logger="sparta.local_tts"), pytest.raises(ProviderUnavailable) as raised:
        await collect(tts, request())
    assert "could not be loaded (ValueError)" in raised.value.message and "secret" not in raised.value.message
    assert any(r.exc_info for r in caplog.records)


async def test_a_voice_that_makes_no_audio_is_an_error_not_silence(make_tts):
    tts, _ = make_tts(FakeLoader(FakeVoice(())))
    with pytest.raises(ProviderError, match="no audio returned"):
        await collect(tts, request())


# --------------------------------------------------------------------------------------------- stopping
async def test_stop_playback_ends_the_audio_at_once_even_while_a_sentence_is_being_made(make_tts):
    voice = FakeVoice((600, 600, 600), delay=0.5)
    tts, _ = make_tts(FakeLoader(voice))
    stream = tts.synthesize_stream(request(trace_id="pb_1"))
    await anext(stream)
    await asyncio.sleep(0.1)  # the second sentence is now being made in its worker
    assert voice.started == 2 and voice.finished == 1
    await tts.stop_playback("pb_1")
    started = time.perf_counter()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert time.perf_counter() - started < 0.2  # not the 0.5 s the second sentence still needs
    await asyncio.sleep(0.8)
    assert (voice.started, voice.finished) == (2, 2)  # that sentence ran to its end, and no third one was started


async def test_a_stop_right_after_the_first_chunk_never_starts_the_next_sentence(make_tts):
    voice = FakeVoice((600, 600, 600), delay=0.2)
    tts, _ = make_tts(FakeLoader(voice))
    stream = tts.synthesize_stream(request(trace_id="pb_1"))
    await anext(stream)
    await tts.stop_playback("pb_1")
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    await asyncio.sleep(0.5)
    assert voice.started <= 2 and voice.finished <= 2


async def test_stop_playback_only_stops_the_named_playback(make_tts):
    tts, _ = make_tts()
    first = tts.synthesize_stream(request(trace_id="pb_1"))
    other = tts.synthesize_stream(request(trace_id="pb_2"))
    await anext(first)
    await anext(other)
    await tts.stop_playback("pb_1")
    await tts.stop_playback("unknown")
    with pytest.raises(StopAsyncIteration):
        await anext(first)
    assert (await anext(other)).seq == 1
    await other.aclose()


async def test_a_consumer_that_walks_away_leaves_nothing_running(make_tts):
    tts, _ = make_tts(FakeLoader(FakeVoice((400, 400, 400), delay=0.05)))
    before = set(asyncio.all_tasks())
    stream = tts.synthesize_stream(request(trace_id="pb_3"))
    await anext(stream)
    await stream.aclose()  # what cancelling the playback task does
    await asyncio.sleep(0.1)
    assert set(asyncio.all_tasks()) - before == set()
    await tts.stop_playback("pb_3")  # nothing is registered any more: harmless


async def test_closing_the_provider_stops_everything_and_refuses_new_requests(make_tts):
    tts, _ = make_tts(FakeLoader(FakeVoice((400, 400), delay=0.05)))
    stream = tts.synthesize_stream(request(trace_id="pb_4"))
    await anext(stream)
    await tts.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    with pytest.raises(ProviderUnavailable, match="closed"):
        await collect(tts, request())


# ------------------------------------------------------------------------------------- voices and warm-up
async def test_list_voices_shows_only_installed_local_voices_and_never_claims_verification(make_tts):
    tts, _ = make_tts(voices=VOICES, installed=("test_en", "test_kn"))
    voices = await tts.list_voices()
    assert [(v.id, v.locale) for v in voices] == [("test_en", "en-IN"), ("test_kn", "kn-IN")]
    assert all(v.verified is False and v.provider == "local-piper" and v.gender == "neutral" for v in voices)
    assert all("not in the manifest" in (v.note or "") for v in voices)
    assert [v.id for v in await tts.list_voices("kn-IN")] == ["test_kn"]
    assert [v.id for v in await tts.list_voices("kn-in")] == ["test_kn"]
    assert await tts.list_voices("hi-IN") == []  # configured but not installed
    assert await tts.list_voices("fr-FR") == []


async def test_manifest_voices_carry_their_licence_caveat_in_the_voice_note(make_tts, make_settings, monkeypatch):
    spec = ModelSpec(
        key="hi_IN-test-medium",
        kind="tts",
        repo="owner/repo",
        revision="b" * 40,
        files=(ModelFile("hi_IN-test-medium.onnx", "0" * 64, 4), ModelFile("hi_IN-test-medium.onnx.json", "1" * 64, 2)),
        summary="",
        licence="Dataset CC-BY-NC-SA-4.0",
        caveat="Non-commercial use only.",
        language="hi",
        gender="female",
    )
    monkeypatch.setattr(local_tts, "VOICES", {spec.key: spec})
    settings = make_settings(local_tts_voices="hi-IN=hi_IN-test-medium")
    folder = Path(settings.local_model_dir) / "tts" / spec.key
    folder.mkdir(parents=True)
    (folder / "hi_IN-test-medium.onnx").write_bytes(b"onnx")
    (folder / "hi_IN-test-medium.onnx.json").write_text("{}", encoding="utf-8")
    tts = LocalTextToSpeech(settings, loader=FakeLoader())
    (voice,) = await tts.list_voices()
    assert (voice.id, voice.display_name, voice.gender, voice.note) == (
        "hi_IN-test-medium",
        "Test",
        "female",
        "Licence: Dataset CC-BY-NC-SA-4.0. Non-commercial use only.",
    )
    await tts.aclose()
    (folder / "hi_IN-test-medium.onnx.json").write_text(
        "{}{}", encoding="utf-8"
    )  # one byte too many: not the pinned file
    assert await LocalTextToSpeech(settings, loader=FakeLoader()).list_voices() == []


async def test_warmup_loads_every_installed_voice_once_and_speaks_a_word_with_each(make_tts):
    tts, loader = make_tts(installed=("test_en", "test_hi"))
    seconds = await tts.warmup()
    assert seconds >= 0.0
    assert sorted(name for name, _ in loader.loaded) == ["test_en", "test_hi"]  # test_kn is not installed: skipped
    assert len(loader.voice.texts) == 2
    await collect(tts, request())
    assert len(loader.loaded) == 2  # already loaded: the first caller pays nothing


async def test_a_voice_is_loaded_once_however_many_calls_start_together(make_tts):
    tts, loader = make_tts()
    await asyncio.gather(*(collect(tts, request()) for _ in range(5)))
    assert [name for name, _ in loader.loaded] == ["test_en"]


async def test_the_startup_warning_names_the_missing_voices(make_settings, caplog):
    settings = make_settings(local_tts_voices=VOICES)
    install(settings, "test_en")
    with caplog.at_level(logging.WARNING, logger="sparta.local_tts"):
        LocalTextToSpeech(settings, loader=FakeLoader())
    messages = [r.getMessage() for r in caplog.records]
    assert sum("is not installed" in m for m in messages) == 2 and any("hi-IN" in m for m in messages)


# ------------------------------------------------------------------------------------------------- metrics
async def test_the_first_sentence_latency_and_the_audio_seconds_are_recorded(make_tts):
    metrics = Metrics()
    tts, _ = make_tts(metrics=metrics)
    await collect(tts, request())
    assert len(metrics.samples(PROVIDER_LATENCY_MS, provider="local-piper", stage="tts_first_sentence")) == 1
    assert metrics.counter(AUDIO_SECONDS, provider="local-piper", direction="tts") == pytest.approx(0.5, abs=0.03)


# ----------------------------------------------------------------------------------- the real Piper adapter
class FakePiperVoice:
    loaded_with: tuple[Any, ...] = ()
    configs: ClassVar[list[Any]] = []

    def __init__(self) -> None:
        self.config = SimpleNamespace(sample_rate=22050, length_scale=1.0)

    @staticmethod
    def load(model_path: Any, config_path: Any = None, **kwargs: Any) -> "FakePiperVoice":
        FakePiperVoice.loaded_with = (model_path, config_path, kwargs)
        return FakePiperVoice()

    def synthesize(self, text: str, syn_config: Any = None) -> Iterator[SimpleNamespace]:
        FakePiperVoice.configs.append(syn_config)
        yield SimpleNamespace(sample_rate=22050, audio_int16_bytes=tone(300.0, 100, 22050))
        yield SimpleNamespace(sample_rate=22050, audio_int16_bytes=b"")  # an empty sentence is skipped
        yield SimpleNamespace(sample_rate=22050, audio_int16_bytes=tone(300.0, 100, 22050))


class FakeSynthesisConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def test_the_piper_adapter_loads_local_files_only_and_maps_the_speaking_rate_to_length_scale(
    monkeypatch, tmp_path, no_network
):
    module = types.ModuleType("piper")
    module.PiperVoice = FakePiperVoice  # type: ignore[attr-defined]
    module.SynthesisConfig = FakeSynthesisConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", module)
    telemetry: list[str] = []
    ort = types.ModuleType("onnxruntime")
    ort.disable_telemetry_events = lambda: telemetry.append(os.environ.get("ORT_DISABLE_TELEMETRY", "unset"))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    FakePiperVoice.configs = []
    onnx, config = tmp_path / "v.onnx", tmp_path / "v.onnx.json"
    handle = load_piper_voice(onnx, config)
    assert FakePiperVoice.loaded_with == (onnx, config, {}) and handle.sample_rate == 22050
    sentences = list(handle.sentences("hello", 2.0))
    assert len(sentences) == 2 and all(len(s) > 0 for s in sentences)
    assert FakePiperVoice.configs[0].kwargs == {
        "length_scale": 0.5,
        "volume": local_tts.VOLUME,
    }  # twice as fast: half as long
    assert no_network == [] and telemetry == ["1"]  # the opt-out was in place when the API call was made


def test_a_missing_piper_package_is_unavailable_with_the_fix(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "piper", None)  # `import piper` now raises ImportError
    with pytest.raises(ProviderUnavailable, match=r"pip install 'sparta-api\[local-speech\]'"):
        load_piper_voice(tmp_path / "v.onnx", tmp_path / "v.onnx.json")


def test_importing_the_providers_does_not_load_any_speech_engine():
    code = (
        "import sys; import sparta.providers.stt.local, sparta.providers.tts.local, sparta.providers.local_models; "
        "heavy = {'piper', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'numpy', 'scipy', 'av'}; "
        "loaded = sorted(heavy & set(sys.modules)); assert not loaded, loaded"
    )
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr
