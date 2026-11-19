"""Real faster-whisper and Piper models. Skipped unless the ``local-speech`` extra is installed and the models are fetched.

Run them with the models in place::

    $env:SPARTA_LOCAL_MODEL_DIR = 'C:\\path\\to\\models'      # python -m sparta models fetch --dir ... puts them there
    python -m pytest tests/unit/providers_local/test_real_models.py -m local_speech

They check that the plumbing works with the real engines (formats, rates, languages, stopping), not that the speech is good:
no recognition quality is asserted beyond an English sentence that Piper itself spoke.
"""

import asyncio
import os
import time
from array import array
from collections.abc import Sequence
from pathlib import Path

import pytest
from tests.audio_fakes import FakeSink

from sparta.config import Settings
from sparta.orchestrator.planner import PlannerConfig, ReplyPlanner
from sparta.providers.base import SynthesisRequest, TranscriptEvent
from sparta.providers.fake_tone import silence
from sparta.providers.local_models import STT_MODELS, VOICES, model_status, spec_dir, verify_spec
from sparta.providers.stt.local import LocalSpeechToText
from sparta.providers.tts.local import LocalTextToSpeech
from sparta.providers.vad.energy import EnergyVad
from sparta.services.audio_pipeline import AudioPipeline

pytestmark = [pytest.mark.local_speech, pytest.mark.timeout(900)]

MODEL_DIR = os.environ.get("SPARTA_LOCAL_MODEL_DIR", "")
OTP = "I'm calling from your bank. Tell me your OTP."


@pytest.fixture(scope="module", autouse=True)
def real_engines() -> None:
    """Skip (not fail) unless the engines import and a model directory was named."""
    if not MODEL_DIR:
        pytest.skip("SPARTA_LOCAL_MODEL_DIR is not set")
    for module in ("numpy", "faster_whisper", "piper"):
        pytest.importorskip(module)


def settings() -> Settings:
    return Settings(_env_file=None, local_model_dir=MODEL_DIR, stt_provider="local", tts_provider="local")


def installed(kind: str, name: str) -> bool:
    return any(s.kind == kind and s.name == name and s.installed for s in model_status(settings()))


def close(provider: LocalSpeechToText | LocalTextToSpeech) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(provider.aclose())
    finally:
        loop.close()


@pytest.fixture(scope="module")
def stt():
    if not installed("stt", "small"):
        pytest.skip("the 'small' model is not installed: python -m sparta models fetch --stt small")
    provider = LocalSpeechToText(settings())
    yield provider
    close(provider)


@pytest.fixture(scope="module")
def tts():
    provider = LocalTextToSpeech(settings())
    yield provider
    close(provider)


def need_voice(key: str) -> None:
    if not installed("tts", key):
        pytest.skip(f"voice {key} is not installed: python -m sparta models fetch --voices all")


async def speak(tts: LocalTextToSpeech, text: str, locale: str, output_format: str = "pcm16_8k") -> bytes:
    request = SynthesisRequest(text=text, locale=locale, voice_id=None, output_format=output_format)  # type: ignore[arg-type]
    return b"".join([chunk.data async for chunk in tts.synthesize_stream(request)])


async def hear(
    stt: LocalSpeechToText, audio: bytes, *, hint: str | None, candidates: Sequence[str], rate: int = 8000
) -> TranscriptEvent:
    stream = await stt.start_stream(candidate_locales=candidates, locale_hint=hint, trace_id="real", sample_rate=rate)
    for start in range(0, len(audio), rate // 50 * 2):
        await stream.push_audio(audio[start : start + rate // 50 * 2])
    await stream.flush()
    (event,) = [event async for event in stream.events()]
    return event


def rms(pcm: bytes) -> float:
    samples = array("h")
    samples.frombytes(pcm)
    return (sum(s * s for s in samples) / max(len(samples), 1)) ** 0.5


def test_the_installed_files_match_their_pinned_hashes():
    checked = 0
    for spec in (*STT_MODELS.values(), *VOICES.values()):
        if installed(spec.kind, spec.key):
            assert verify_spec(spec, spec_dir(Path(MODEL_DIR), spec)) == [], spec.key
            checked += 1
    assert checked > 0, "no manifest model is installed in SPARTA_LOCAL_MODEL_DIR"


async def test_an_english_sentence_survives_piper_then_8_khz_then_whisper(stt, tts):
    need_voice("en_US-ljspeech-medium")
    audio = await speak(tts, OTP, "en-IN")
    assert 1.5 < len(audio) / 16000 < 6.0  # seconds of 8 kHz PCM16
    for hint, candidates in (("en-IN", ["en-IN"]), (None, ["en-IN", "hi-IN", "kn-IN"])):
        event = await hear(stt, audio, hint=hint, candidates=candidates)
        text = event.text.lower().replace(" ", "")
        assert "bank" in text and "otp" in text, event.text
        assert event.language == "en-IN" and 0.3 < (event.confidence or 0) <= 0.95


@pytest.mark.parametrize(
    ("locale", "key"), [("hi-IN", "hi_IN-priyamvada-medium"), ("kn-IN", "kn_IN-syspin_male-medium")]
)
async def test_the_hindi_and_kannada_voices_speak_sparta_s_own_greeting_at_every_rate(tts, locale, key):
    need_voice(key)
    plan = ReplyPlanner().render("disclosure", locale, PlannerConfig(owner_name="Atharv"))
    assert plan.locale == locale
    for name, rate in (("pcm16_8k", 8000), ("pcm16_16k", 16000), ("pcm16_24k", 24000)):
        audio = await speak(tts, plan.text, locale, name)
        assert 2.0 < len(audio) / (2 * rate) < 20.0 and rms(audio) > 300, (locale, name)


async def test_kannada_recognised_by_whisper_small_is_always_treated_as_poor_audio(stt, tts):
    need_voice("kn_IN-syspin_male-medium")
    plan = ReplyPlanner().render("ask_name", "kn-IN", PlannerConfig())
    audio = await speak(tts, plan.text, "kn-IN")
    event = await hear(stt, audio, hint="kn-IN", candidates=["kn-IN"])
    assert event.language == "kn-IN" and event.confidence is not None and event.confidence <= 0.5 < 0.55


async def test_the_real_models_work_through_the_audio_pipeline_at_telephone_rate(stt, tts):
    need_voice("en_US-ljspeech-medium")
    speech = await speak(tts, OTP, "en-IN")
    sink = FakeSink()
    pipeline = AudioPipeline(
        call_id="call_1",
        sink=sink,
        stt=stt,
        vad=EnergyVad(),
        locales=lambda: (["en-IN", "hi-IN", "kn-IN"], None),
        trace_id="real",
    )
    audio = silence(300, 8000) + speech + silence(1000, 8000)
    for start in range(0, len(audio), 320):  # 20 ms frames, the way Asterisk delivers them
        await pipeline.feed(audio[start : start + 320], 8000)
    await pipeline.drain(within_s=180)
    heard = " ".join(turn["text"] for turn in sink.turns).lower().replace(" ", "")
    assert sink.errors == [] and "bank" in heard and "otp" in heard, (sink.turns, sink.errors)
    assert all(turn["language"] == "en-IN" and 0.3 < turn["confidence"] <= 0.95 for turn in sink.turns)
    await pipeline.aclose()


async def test_silence_and_hiss_are_not_recognised_as_speech(stt):
    for audio in (silence(2000, 8000), array("h", [(i * 7919) % 41 - 20 for i in range(16000)]).tobytes()):
        event = await hear(stt, audio, hint="en-IN", candidates=["en-IN"])
        assert event.text == "" and event.confidence == 0.0


async def test_stopping_a_real_synthesis_ends_the_audio_promptly(tts):
    need_voice("en_US-ljspeech-medium")
    request = SynthesisRequest(
        text="Hi, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding? " * 3,
        locale="en-IN",
        voice_id=None,
        output_format="pcm16_8k",
        trace_id="pb_real",
    )
    stream = tts.synthesize_stream(request)
    first = await anext(stream)
    assert first.sample_rate == 8000 and len(first.data) == 640
    await tts.stop_playback("pb_real")
    started = time.perf_counter()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert time.perf_counter() - started < 0.5
