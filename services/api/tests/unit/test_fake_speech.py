"""The tone-coded fake speech providers: they prove audio plumbing, recognise and speak nothing real."""

import random
from array import array

import pytest

from sparta.config import ConfigurationError, Settings
from sparta.providers.base import ProviderRejected, SynthesisRequest, consumes_audio, produces_audio
from sparta.providers.fake_tone import (
    BURST_MS,
    FILLER_HZ,
    decode_line_id,
    encode_line_id,
    line_id_for,
    silence,
    tone,
    tone_duration_ms,
)
from sparta.providers.stt.fake import FakeToneSpeechToText
from sparta.providers.stt.fake_phrases import FAKE_PHRASES, id_of, phrase_for
from sparta.providers.stt.simulator import SimulatedSpeechToText
from sparta.providers.tts.fake import MIN_LINE_MS, FakeToneTextToSpeech
from sparta.providers.tts.simulator import SimulatedTextToSpeech
from sparta.providers.tts.ssml import estimate_duration_ms
from sparta.telephony.g711 import pcm16_to_ulaw, ulaw_to_pcm16

RATES = (8000, 16000, 24000)


def scaled(pcm: bytes, factor: float) -> bytes:
    samples = array("h")
    samples.frombytes(pcm)
    return array("h", [int(s * factor) for s in samples]).tobytes()


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("line_id", [0, 1, 17, 90, 255])
def test_a_line_id_round_trips_at_every_rate(rate, line_id):
    assert decode_line_id(encode_line_id(line_id, rate), rate) == line_id


def test_the_burst_is_found_after_silence_and_before_filler():
    rate = 8000
    audio = silence(300, rate) + encode_line_id(42, rate) + tone(FILLER_HZ, 800, rate)
    assert decode_line_id(audio, rate) == 42


def test_the_burst_survives_mu_law_companding_and_a_quiet_line():
    rate = 8000
    burst = encode_line_id(200, rate) + tone(FILLER_HZ, 400, rate)
    companded = ulaw_to_pcm16(pcm16_to_ulaw(burst))
    assert decode_line_id(companded, rate) == 200
    assert decode_line_id(scaled(burst, 0.45), rate) == 200


def test_a_wrong_sample_rate_or_byte_order_does_not_decode():
    burst = encode_line_id(77, 8000) + tone(FILLER_HZ, 400, 8000)
    assert decode_line_id(burst, 16000) is None  # the samples are read at twice their rate
    swapped = array("h")
    swapped.frombytes(burst)
    swapped.byteswap()  # what a big-endian bridge would deliver
    assert decode_line_id(swapped.tobytes(), 8000) is None


def test_noise_silence_and_a_steady_tone_carry_no_line_id():
    rate = 8000
    rng = random.Random(7)
    noise = array("h", [rng.randint(-6000, 6000) for _ in range(rate * 2)]).tobytes()
    for audio in (noise, silence(1500, rate), tone(FILLER_HZ, 1500, rate), b"", b"\x01"):
        assert decode_line_id(audio, rate) is None


def test_a_damaged_check_symbol_is_refused():
    rate = 8000
    burst = encode_line_id(0x5C, rate)
    window = rate * 40 // 1000 * 2
    damaged = burst[: 4 * window] + encode_line_id(0x00, rate)[4 * window :]  # a different last symbol
    assert decode_line_id(damaged, rate) is None


def test_an_id_must_fit_one_byte():
    with pytest.raises(ValueError):
        encode_line_id(256, 8000)


def test_the_phrase_table_has_unique_ids_and_known_locales():
    assert len({p.text for p in FAKE_PHRASES.values()}) == len(FAKE_PHRASES)
    assert all(
        0 <= i <= 255 and p.text.strip() and p.locale in {"en-IN", "hi-IN", "kn-IN"} for i, p in FAKE_PHRASES.items()
    )
    assert phrase_for(1) is not None and phrase_for(1).text == "I'm calling from your bank. Tell me your OTP."
    assert id_of("Reveal his calendar.") == 24 and phrase_for(250) is None
    with pytest.raises(KeyError):
        id_of("not a registered phrase")


async def test_the_fake_recogniser_answers_with_the_phrase_a_caller_burst_names():
    stt = FakeToneSpeechToText()
    stream = await stt.start_stream(
        candidate_locales=["en-IN", "hi-IN"], locale_hint=None, trace_id="t", sample_rate=8000
    )
    audio = silence(200, 8000) + encode_line_id(id_of("Sir KYC update karna hai, OTP bata dijiye."), 8000)
    audio += tone(FILLER_HZ, 500, 8000)
    for start in range(0, len(audio), 320):
        await stream.push_audio(audio[start : start + 320])
    await stream.flush()
    await stream.stop_stream()
    events = [event async for event in stream.events()]
    assert [(e.kind, e.text, e.language) for e in events] == [
        ("final", "Sir KYC update karna hai, OTP bata dijiye.", "hi-IN")
    ]
    assert events[0].confidence == pytest.approx(0.99)


async def test_audio_without_a_burst_yields_an_empty_transcript_like_noise_would():
    stream = await FakeToneSpeechToText().start_stream(
        candidate_locales=["en-IN"], locale_hint=None, trace_id="t", sample_rate=8000
    )
    await stream.push_audio(tone(FILLER_HZ, 600, 8000))
    await stream.flush()
    await stream.stop_stream()
    events = [event async for event in stream.events()]
    assert [(e.text, e.confidence) for e in events] == [("", 0.0)]


async def test_uploaded_clips_still_need_a_transcript_hint():
    stt = FakeToneSpeechToText()
    with pytest.raises(ProviderRejected):
        await stt.transcribe(
            b"RIFF", content_type="audio/wav", candidate_locales=["en-IN"], locale_hint=None, trace_id="t"
        )
    result = await stt.transcribe(
        b"RIFF",
        content_type="audio/wav",
        candidate_locales=["en-IN"],
        locale_hint="en-IN",
        trace_id="t",
        transcript_hint="hello",
    )
    assert result.text == "hello"


@pytest.mark.parametrize(("rate_name", "rate"), [("pcm16_8k", 8000), ("pcm16_16k", 16000)])
async def test_every_assistant_line_is_marked_with_its_id_and_lasts_as_long_as_estimated(rate_name, rate):
    text = "Hi, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding?"
    chunks = [
        c
        async for c in FakeToneTextToSpeech().synthesize_stream(
            SynthesisRequest(text=text, locale="en-IN", voice_id=None, output_format=rate_name)
        )
    ]
    audio = b"".join(c.data for c in chunks)
    assert all(c.sample_rate == rate and c.encoding == "pcm16" for c in chunks)
    assert [c.final for c in chunks] == [False] * (len(chunks) - 1) + [True]
    assert decode_line_id(audio, rate) == line_id_for(text)
    expected = max(MIN_LINE_MS, estimate_duration_ms(text, "en-IN", 1.0))
    assert abs(tone_duration_ms(audio, rate) - expected) <= 60
    assert expected > BURST_MS


async def test_the_fake_synthesiser_makes_only_pcm16():
    with pytest.raises(ProviderRejected):
        async for _ in FakeToneTextToSpeech().synthesize_stream(
            SynthesisRequest(text="hello", locale="en-IN", voice_id=None, output_format="mulaw_8k")
        ):
            pass


def test_audio_capabilities_tell_the_simulator_from_a_fake_that_reads_or_makes_samples():
    assert consumes_audio(SimulatedSpeechToText()) is False and consumes_audio(FakeToneSpeechToText()) is True
    assert produces_audio(SimulatedTextToSpeech()) is False and produces_audio(FakeToneTextToSpeech()) is True


def test_the_fake_providers_are_forbidden_in_production_and_fine_elsewhere():
    outside = Settings(stt_provider="fake", tts_provider="fake", _env_file=None).problems()
    assert not any("test-only" in problem for problem in outside)
    for field in ("stt_provider", "tts_provider"):
        with pytest.raises(ConfigurationError, match="test-only"):
            Settings(env="production", _env_file=None, **{field: "fake"})
