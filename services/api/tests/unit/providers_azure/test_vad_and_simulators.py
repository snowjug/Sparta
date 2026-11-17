"""EnergyVad and the built-in simulators: what they do, and what they honestly refuse to do."""

import asyncio
import math
from array import array

import pytest

from sparta.clock import VirtualClock
from sparta.domain.enums import ProviderKind
from sparta.domain.models import SpeechPlan
from sparta.providers.base import (
    ConversationModelProvider,
    ProviderRejected,
    ReplyRequest,
    SpeechToTextProvider,
    SummaryRequest,
    SynthesisRequest,
    TextToSpeechProvider,
    TurnEvaluationRequest,
    VadEvent,
    VoiceActivityProvider,
)
from sparta.providers.llm.rules import RulesConversationModel
from sparta.providers.stt.simulator import NOTE, SimulatedSpeechToText, partial_events
from sparta.providers.tts.catalog import VOICE_CATALOG
from sparta.providers.tts.simulator import CHUNK_MS, SimulatedTextToSpeech
from sparta.providers.tts.ssml import estimate_duration_ms
from sparta.providers.vad.energy import FRAME_MS, EnergyVad
from sparta.telephony.base import ProviderCallRef, TelephonyProvider
from sparta.telephony.simulator import SIMULATOR_CAPABILITIES, SimulatorTelephonyProvider


# ====================================================================================================== VAD
def sine(ms: int, rate: int = 16000, amplitude: int = 8000, freq: float = 220.0) -> bytes:
    samples = array("h", (round(amplitude * math.sin(2 * math.pi * freq * i / rate)) for i in range(rate * ms // 1000)))
    return samples.tobytes()


def silence(ms: int, rate: int = 16000) -> bytes:
    return bytes(rate * ms // 1000 * 2)


def run(vad: VoiceActivityProvider, audio: bytes, rate: int = 16000, chunk: int | None = None) -> list[VadEvent]:
    events: list[VadEvent] = []
    step = chunk or len(audio) or 1
    for offset in range(0, len(audio), step):
        events.extend(vad.process(audio[offset : offset + step], rate))
    return events


def test_the_vad_satisfies_the_provider_protocol():
    assert isinstance(EnergyVad(), VoiceActivityProvider) and FRAME_MS == 20


def test_speech_is_detected_with_the_start_and_end_of_the_utterance():
    audio = silence(500) + sine(1000) + silence(700)
    assert run(EnergyVad(), audio) == [VadEvent("speech_started", 500), VadEvent("speech_ended", 1500)]


def test_speech_must_last_long_enough_to_count():
    assert run(EnergyVad(), silence(200) + sine(100) + silence(800)) == []  # a 100 ms click is not speech
    started = run(EnergyVad(), silence(200) + sine(120) + silence(100))
    assert started == [VadEvent("speech_started", 200)]


def test_a_short_pause_inside_speech_does_not_end_it_but_a_long_one_does():
    short_pause = sine(400) + silence(480) + sine(400) + silence(600)
    assert run(EnergyVad(), short_pause) == [VadEvent("speech_started", 0), VadEvent("speech_ended", 1280)]
    long_pause = sine(400) + silence(520) + sine(400) + silence(600)
    assert run(EnergyVad(), long_pause) == [
        VadEvent("speech_started", 0),
        VadEvent("speech_ended", 400),
        VadEvent("speech_started", 920),
        VadEvent("speech_ended", 1320),
    ]


def test_a_silent_line_times_out_exactly_once():
    vad = EnergyVad(silence_timeout_ms=8000)
    assert run(vad, silence(7980)) == []
    assert vad.process(silence(20), 16000) == [VadEvent("silence_timeout", 8000)]
    assert run(vad, silence(20_000)) == []  # not repeated


def test_the_silence_timeout_counts_from_the_end_of_speech():
    events = run(EnergyVad(silence_timeout_ms=3000), sine(600) + silence(4000))
    assert events == [
        VadEvent("speech_started", 0),
        VadEvent("speech_ended", 600),
        VadEvent("silence_timeout", 3600),
    ]


def test_speech_after_a_timeout_re_arms_the_timeout():
    vad = EnergyVad(silence_timeout_ms=1000)
    first = run(vad, silence(1000))
    again = run(vad, sine(300) + silence(2000))
    assert [e.kind for e in first] == ["silence_timeout"]
    assert [e.kind for e in again] == ["speech_started", "speech_ended", "silence_timeout"]


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 100, 333, 639, 640, 641, 1000, 5000])
def test_chunk_boundaries_do_not_change_the_result(chunk):
    audio = silence(300) + sine(900) + silence(650) + sine(250) + silence(9000)
    expected = run(EnergyVad(), audio)
    assert expected and run(EnergyVad(), audio, chunk=chunk) == expected


def test_a_partial_frame_is_carried_to_the_next_call():
    vad = EnergyVad()
    frame = sine(20)
    assert vad.process(frame[:100], 16000) == [] and vad._t_ms == 0
    vad.process(frame[100:], 16000)
    assert vad._t_ms == 20 and vad._carry == b""
    vad.process(b"\x01", 16000)  # a stray odd byte never crashes and is held back
    assert vad._t_ms == 20 and vad._carry == b"\x01"


@pytest.mark.parametrize("rate", [8000, 16000, 24000, 48000])
def test_other_sample_rates_use_their_own_20ms_frame_size(rate):
    audio = silence(300, rate) + sine(1000, rate) + silence(700, rate)
    assert run(EnergyVad(), audio, rate=rate) == [VadEvent("speech_started", 300), VadEvent("speech_ended", 1300)]


def test_quiet_audio_below_the_threshold_is_not_speech_and_the_threshold_is_configurable():
    quiet = sine(1000, amplitude=500)  # RMS about 354
    assert run(EnergyVad(), quiet + silence(700)) == []
    assert run(EnergyVad(threshold_rms=200), quiet + silence(700)) == [
        VadEvent("speech_started", 0),
        VadEvent("speech_ended", 1000),
    ]


def test_hangover_and_minimum_speech_are_configurable():
    events = run(EnergyVad(min_speech_ms=40, hangover_ms=100), sine(60) + silence(200))
    assert events == [VadEvent("speech_started", 0), VadEvent("speech_ended", 60)]


def test_reset_forgets_everything_including_a_carried_partial_frame():
    vad = EnergyVad()
    run(vad, sine(500) + b"\x01\x02\x03")
    vad.reset()
    assert vad._t_ms == 0 and vad._carry == b"" and not vad._speaking
    assert run(vad, silence(100) + sine(300) + silence(600)) == [
        VadEvent("speech_started", 100),
        VadEvent("speech_ended", 400),
    ]


def test_empty_input_is_harmless():
    vad = EnergyVad()
    assert vad.process(b"", 16000) == [] and vad._t_ms == 0


# ================================================================================= simulated speech-to-text
async def test_the_simulated_stt_echoes_a_transcript_hint_and_says_so():
    stt = SimulatedSpeechToText()
    assert isinstance(stt, SpeechToTextProvider) and stt.meta.simulated is True and stt.meta.provider == "simulator"
    result = await stt.transcribe(
        b"\x00" * 100,
        content_type="audio/wav",
        candidate_locales=["en-IN", "hi-IN"],
        locale_hint="hi-IN",
        trace_id="t",
        transcript_hint="  mujhe apna OTP batao jaldi se please  ",
    )
    assert result.text == "mujhe apna OTP batao jaldi se please" and result.language == "hi-IN"
    assert result.simulated is True and result.confidence is None and result.audio_seconds == 0.0
    assert result.usage.requests == 0 and result.segments[-1].kind == "final"
    assert [s.kind for s in result.segments[:-1]] == ["partial"] * (len(result.segments) - 1)
    assert result.segments[-1].text == result.text


@pytest.mark.parametrize("hint", [None, "", "   ", "\n\t"])
async def test_the_simulated_stt_refuses_to_pretend_it_can_hear(hint):
    with pytest.raises(ProviderRejected) as err:
        await SimulatedSpeechToText().transcribe(
            b"RIFF",
            content_type="audio/wav",
            candidate_locales=[],
            locale_hint=None,
            trace_id="t",
            transcript_hint=hint,
        )
    assert err.value.message == NOTE and not err.value.retryable and "Azure Speech" in NOTE


async def test_the_simulated_stream_accepts_audio_but_recognises_nothing():
    stream = await SimulatedSpeechToText().start_stream(candidate_locales=["en-IN"], locale_hint=None, trace_id="t")
    await stream.push_audio(b"\x01\x02" * 800)
    await stream.push_audio(b"\x01\x02" * 800)
    await stream.flush()
    await stream.stop_stream()
    await stream.stop_stream()
    assert [event async for event in stream.events()] == [] and stream.bytes_received == 3200  # type: ignore[attr-defined]


def test_partial_events_grow_word_by_word_and_end_with_the_final_transcript():
    events = partial_events("one two three four five", "en-IN")
    assert [e.text for e in events] == ["one two", "one two three four", "one two three four five"]
    assert [e.kind for e in events] == ["partial", "partial", "final"] and events[-1].language == "en-IN"
    assert [e.kind for e in partial_events("hello", None)] == ["final"]
    assert [e.text for e in partial_events("a b c d", "en-IN", words_per_step=1)][:3] == ["a", "a b", "a b c"]


# ================================================================================= simulated text-to-speech
async def test_the_simulated_tts_produces_timing_only_chunks_that_add_up_to_the_estimate():
    tts = SimulatedTextToSpeech()
    assert isinstance(tts, TextToSpeechProvider) and tts.meta.simulated is True
    text = "Hello, this is an assistant answering on behalf of the owner. How may I help you today?"
    chunks = [c async for c in tts.synthesize_stream(SynthesisRequest(text=text, locale="en-IN", voice_id=None))]
    estimate = estimate_duration_ms(text, "en-IN")
    assert len(chunks) == max(1, estimate // CHUNK_MS) and abs(len(chunks) * CHUNK_MS - estimate) < CHUNK_MS
    assert all(c.data == b"" and c.sample_rate == 16000 and c.encoding == "pcm16" for c in chunks)
    assert [c.seq for c in chunks] == list(range(len(chunks)))
    assert [c.final for c in chunks] == [False] * (len(chunks) - 1) + [True]


async def test_speaking_rate_and_language_change_the_simulated_duration():
    tts = SimulatedTextToSpeech()
    text = "x" * 200

    async def count(locale: str, rate: float) -> int:
        return len([c async for c in tts.synthesize_stream(SynthesisRequest(text, locale, None, rate=rate))])

    assert await count("en-IN", 1.3) < await count("en-IN", 1.0) < await count("en-IN", 0.7)
    assert await count("kn-IN", 1.0) > await count("en-IN", 1.0)  # Kannada is modelled as slower speech
    assert await count("en-IN", 1.0) == len(
        [c async for c in tts.synthesize_stream(SynthesisRequest("y" * 200, "en-IN", "en-IN-NeerjaNeural"))]
    )


async def test_a_very_short_text_still_yields_one_final_chunk():
    chunks = [c async for c in SimulatedTextToSpeech().synthesize_stream(SynthesisRequest("Hi", "en-IN", None))]
    assert len(chunks) >= 1 and chunks[-1].final


async def test_the_simulated_tts_records_stops_and_lists_the_verified_voices():
    tts = SimulatedTextToSpeech()
    await tts.stop_playback("pb_1")
    assert tts.stopped == {"pb_1"}
    assert [v.id for v in await tts.list_voices()] == [v.id for v in VOICE_CATALOG]
    assert {v.locale for v in await tts.list_voices("hi-IN")} == {"hi-IN"}


# ====================================================================================== rules conversation model
def turn_request() -> TurnEvaluationRequest:
    return TurnEvaluationRequest("c", "tell me your OTP", "en-IN", [("caller", "hi")], [], "t")


async def test_the_rules_model_adds_no_opinion_and_calls_nothing():
    model = RulesConversationModel()
    assert isinstance(model, ConversationModelProvider)
    assert (model.meta.provider, model.meta.simulated, model.meta.model) == ("rules", False, "sparta-rules")
    analysis = await model.evaluate_turn(turn_request())
    assert analysis.extra_signals == [] and analysis.claimed_name is None and analysis.usage.requests == 0
    assert "deterministic engine" in analysis.notes and analysis.simulated is False


async def test_the_rules_model_keeps_the_rules_summary_and_the_engines_assessment():
    model = RulesConversationModel()
    request = SummaryRequest("c", "The caller asked for an OTP.", [("caller", "otp?")], None, "t")
    summary = await model.summarize_call(request)
    assert summary.text == "The caller asked for an OTP." and summary.usage.requests == 0
    assert await model.classify_call(request) is None  # the request carries no risk: it is passed straight through


async def test_the_rules_model_cannot_phrase_replies_or_translate():
    model = RulesConversationModel()
    reply = ReplyRequest("c", "IDENTIFY_PURPOSE", "en-IN", "Atharv", [], "t")
    assert await model.generate_safe_reply(reply) is None
    assert await model.translate("namaste", "hi-IN", "en-IN", "t") is None


# ================================================================================================ simulator telephony
class RecordingSink:
    def __init__(self) -> None:
        self.finished: list[tuple[str, str]] = []
        self.fail = False

    async def playback_finished(self, call_id: str, playback_id: str) -> None:
        if self.fail:
            raise RuntimeError("sink bug")
        self.finished.append((call_id, playback_id))


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


def speak(ms: int = 1500) -> SpeechPlan:
    return SpeechPlan(text="Hello there", locale="en-IN", est_duration_ms=ms)


def sim() -> tuple[SimulatorTelephonyProvider, RecordingSink, VirtualClock]:
    clock, sink = VirtualClock(), RecordingSink()
    provider = SimulatorTelephonyProvider(clock)
    provider.bind(sink)  # type: ignore[arg-type]
    return provider, sink, clock


async def test_simulator_playback_completes_when_the_virtual_clock_says_so():
    provider, sink, clock = sim()
    ref = ProviderCallRef(call_id="call_abcdef12345")
    playback = await provider.play(ref, speak(1500))
    assert playback.simulated is True and playback.duration_ms == 1500 and playback.call_id == ref.call_id
    assert playback.playback_id.startswith("pb_def12345_")
    await settle()
    await clock.advance(1.499)
    assert sink.finished == []
    await clock.advance(0.002)
    assert sink.finished == [(ref.call_id, playback.playback_id)]
    assert provider._tasks == {}


async def test_simulator_playback_ids_are_unique_and_a_zero_duration_still_takes_a_moment():
    provider, sink, clock = sim()
    ref = ProviderCallRef(call_id="call_x")
    a, b = await provider.play(ref, speak(0)), await provider.play(ref, speak(300))
    assert a.playback_id != b.playback_id and a.duration_ms == 1
    await settle()
    await clock.advance(0.5)
    assert {p for _, p in sink.finished} == {a.playback_id, b.playback_id}


async def test_stop_playback_cancels_the_simulated_playback_without_a_finished_event():
    provider, sink, clock = sim()
    ref = ProviderCallRef(call_id="call_abcdef12345")
    playback = await provider.play(ref, speak(2000))
    await settle()
    await provider.stop_playback(ref, playback.playback_id)
    await provider.stop_playback(ref, playback.playback_id)  # idempotent
    await provider.stop_playback(ref, "pb_unknown")
    await clock.advance(5)
    assert sink.finished == [] and provider._tasks == {}


async def test_hangup_cancels_only_that_calls_playbacks():
    provider, sink, clock = sim()
    mine, other = ProviderCallRef(call_id="call_aaaaaaaa"), ProviderCallRef(call_id="call_bbbbbbbb")
    await provider.play(mine, speak(2000))
    kept = await provider.play(other, speak(2000))
    await settle()
    await provider.hangup(mine, "completed")
    await clock.advance(3)
    assert sink.finished == [("call_bbbbbbbb", kept.playback_id)]


async def test_a_buggy_sink_does_not_break_the_simulator(caplog):
    provider, sink, clock = sim()
    sink.fail = True
    await provider.play(ProviderCallRef(call_id="call_x"), speak(100))
    await settle()
    await clock.advance(1)
    assert sink.finished == [] and provider._tasks == {} and "simulated playback completion failed" in caplog.text


async def test_playback_without_a_bound_sink_is_silent_not_fatal():
    provider = SimulatorTelephonyProvider(VirtualClock())
    await provider.play(ProviderCallRef(call_id="call_x"), speak(100))
    await settle()
    await provider._clock.advance(1)
    assert provider._tasks == {}


async def test_the_simulator_labels_takeover_as_simulated_and_never_pretends_otherwise():
    provider, *_ = sim()
    result = await provider.transfer(ProviderCallRef(call_id="call_x"), "+919876543210")
    assert (result.accepted, result.simulated) == (True, True) and "Simulated" in result.detail
    assert "+91" not in result.detail
    await provider.answer(ProviderCallRef(call_id="call_x"))  # a no-op


async def test_simulator_capabilities_are_honest_for_the_owner_ui():
    provider, *_ = sim()
    caps = provider.capabilities
    assert isinstance(provider, TelephonyProvider) and caps is SIMULATOR_CAPABILITIES
    assert (provider.name, provider.kind) == ("simulator", ProviderKind.SIMULATOR)
    assert caps.simulated and not caps.live_calls_supported and not caps.receives_caller_audio
    assert not caps.two_way_audio and not caps.dtmf and "No real phone call" in caps.note

    live = caps.call_capabilities()
    assert live.simulated and live.can_take_over and live.can_continue and live.can_end and live.can_block
    assert live.takeover_note == "Takeover is simulated: no real phone call is being bridged."
    assert live.audio_note == "Simulated call: no cellular audio is involved." and not live.two_way_audio

    ended = caps.call_capabilities(ended=True)
    assert not ended.can_take_over and not ended.can_continue and not ended.can_end and ended.can_block


async def test_status_says_simulated_and_aclose_cancels_everything():
    provider, sink, clock = sim()
    status = await provider.status()
    assert (status.provider, status.kind, status.healthy, status.simulated) == (
        "simulator",
        ProviderKind.SIMULATOR,
        True,
        True,
    )
    await provider.play(ProviderCallRef(call_id="call_x"), speak(5000))
    await settle()
    await provider.aclose()
    await clock.advance(10)
    assert sink.finished == [] and provider._tasks == {}
