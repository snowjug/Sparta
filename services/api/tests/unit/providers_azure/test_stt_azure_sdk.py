"""Streaming speech recognition through the Speech SDK (against a scripted fake; the real SDK only for name checks)."""

import asyncio
import sys

import pytest

from sparta.observability.metrics import PROVIDER_LATENCY_MS, Metrics
from sparta.providers.base import ProviderError, ProviderRejected, ProviderUnavailable
from sparta.providers.stt import azure_sdk
from sparta.providers.stt.azure import AzureSpeechToText
from sparta.providers.stt.azure_sdk import SdkSpeechToText, build_stt, sdk_available

from . import fake_speech_sdk as fake
from .fake_speech_sdk import CancellationErrorCode, Scenario, make_sdk

LOCALES = ["en-IN", "hi-IN", "kn-IN"]
PCM = b"\x01\x00" * 320  # 20 ms at 16 kHz


def make(make_settings, scenario: Scenario | None = None, **settings):
    sdk = make_sdk(scenario)
    metrics = Metrics()
    rest = AzureSpeechToText(make_settings(**settings))
    return SdkSpeechToText(make_settings(**settings), rest=rest, sdk_loader=lambda: sdk, metrics=metrics), sdk, metrics


async def open_stream(stt, *, candidates=LOCALES, hint=None, rate=16000):
    return await stt.start_stream(candidate_locales=candidates, locale_hint=hint, trace_id="t", sample_rate=rate)


async def feed(stream, chunks=6):  # 6 x 20 ms = 120 ms: above the minimum utterance length
    for _ in range(chunks):
        await stream.push_audio(PCM)


async def collect(stream):
    return [event async for event in stream.events()]


async def test_partials_arrive_while_audio_is_pushed_and_the_final_carries_language_and_confidence(make_settings):
    scenario = Scenario(
        partials=("hello", "hello sir"),
        final={
            "text": "hello sir",
            "language": "hi-IN",
            "confidence": 0.87,
            "offset_ticks": 5_000_000,
            "duration_ticks": 12_000_000,
            "latency_ms": 180,
        },
    )
    stt, _sdk, metrics = make(make_settings, scenario)
    stream = await open_stream(stt, hint="hi-IN")
    await feed(stream)
    await stream.flush()
    events = await collect(stream)
    assert [(e.kind, e.text) for e in events] == [
        ("partial", "hello"),
        ("partial", "hello sir"),
        ("final", "hello sir"),
    ]
    final = events[-1]
    assert final.language == "hi-IN" and final.confidence == pytest.approx(0.87)
    assert (final.offset_ms, final.duration_ms) == (500, 1200)
    assert metrics.samples(PROVIDER_LATENCY_MS, provider="azure-speech", stage="stt_service") == [180.0]
    recogniser = fake.SpeechRecognizer.created[0]
    assert recogniser.started and recogniser.stopped
    assert recogniser.config.output_format is fake.OutputFormat.Detailed
    # the hint comes first; the call's other languages stay candidates for language identification
    assert recogniser.auto_detect.languages == ["hi-IN", "en-IN", "kn-IN"]
    assert recogniser.config.properties == {fake.PropertyId.SpeechServiceConnection_LanguageIdMode: "Continuous"}
    assert recogniser.audio.stream.format.samples_per_second == 16000 and recogniser.audio.stream.closed
    assert b"".join(recogniser.audio.stream.chunks) == PCM * 6


async def test_a_single_candidate_locale_is_recognised_directly_without_language_identification(make_settings):
    stt, _, _ = make(make_settings, Scenario(final={"text": "namaste"}))
    stream = await open_stream(stt, candidates=["hi-IN"], hint="hi-IN")
    await feed(stream)
    await stream.flush()
    recogniser = fake.SpeechRecognizer.created[0]
    assert recogniser.auto_detect is None and recogniser.config.speech_recognition_language == "hi-IN"
    assert fake.PropertyId.SpeechServiceConnection_LanguageIdMode not in recogniser.config.properties
    assert [e.text for e in await collect(stream)] == ["namaste"]


async def test_callbacks_cross_from_the_sdk_thread_to_the_event_loop(make_settings):
    scenario = Scenario(partials=("a",), final={"text": "a"})
    stt, _, _ = make(make_settings, scenario)
    stream = await open_stream(stt)
    await feed(stream, 1)
    await stream.flush()
    await collect(stream)
    import threading

    assert scenario.callback_threads and threading.get_ident() not in scenario.callback_threads


async def test_speech_that_is_not_recognised_is_an_empty_utterance_not_an_error(make_settings):
    stt, _, _ = make(make_settings, Scenario(no_match=True))
    stream = await open_stream(stt)
    await feed(stream)
    await stream.flush()
    assert await collect(stream) == []


async def test_a_blip_shorter_than_the_minimum_is_an_empty_final_without_waiting_for_the_service(make_settings):
    stt, _, _ = make(make_settings, Scenario(never_stops=True))
    stream = await open_stream(stt)
    await stream.push_audio(b"\x00\x00" * 40)  # 2.5 ms
    await asyncio.wait_for(stream.flush(), 1.0)
    events = await collect(stream)
    assert [(e.kind, e.text) for e in events] == [("final", "")]


@pytest.mark.parametrize(
    ("code", "exc_type", "message"),
    [
        (CancellationErrorCode.AuthenticationFailure, ProviderRejected, "authentication failed"),
        (CancellationErrorCode.BadRequestParameters, ProviderRejected, "unsupported locale"),
        (CancellationErrorCode.TooManyRequests, ProviderError, "rate limited"),
        (CancellationErrorCode.ConnectionFailure, ProviderError, "unavailable"),
        (CancellationErrorCode.RuntimeError, ProviderError, "unavailable"),
    ],
)
async def test_a_cancellation_becomes_a_static_error_and_never_forwards_the_sdk_text(
    make_settings, code, exc_type, message
):
    stt, _, _ = make(make_settings, Scenario(error=code))
    stream = await open_stream(stt)
    await feed(stream)
    with pytest.raises(exc_type) as caught:
        await stream.flush()
    assert message in caught.value.message
    assert "secret.example.com" not in str(caught.value) and "SECRET" not in str(caught.value)
    assert (await collect(stream)) == []  # the stream is over


async def test_a_service_that_never_answers_times_out_and_is_cleaned_up(make_settings, monkeypatch):
    monkeypatch.setattr(azure_sdk, "FINAL_TIMEOUT_S", 0.05)
    stt, _, _ = make(make_settings, Scenario(never_stops=True))
    stream = await open_stream(stt)
    await feed(stream)
    with pytest.raises(ProviderError, match="did not answer in time") as caught:
        await stream.flush()
    assert caught.value.retryable
    assert fake.SpeechRecognizer.created[0].stopped


async def test_a_recogniser_that_cannot_start_is_a_retryable_error_without_the_sdk_message(make_settings):
    stt, _, _ = make(make_settings, Scenario(start_error=True))
    with pytest.raises(ProviderError, match="could not be reached") as caught:
        await open_stream(stt)
    assert "secret.example.com" not in str(caught.value) and caught.value.retryable


async def test_stopping_is_idempotent_and_ends_the_event_stream(make_settings):
    stt, _, _ = make(make_settings, Scenario(partials=("x",), never_stops=True))
    stream = await open_stream(stt)
    await feed(stream, 1)
    await stream.stop_stream()
    await stream.stop_stream()
    await stream.push_audio(PCM)  # ignored after stop, no error
    await stream.flush()  # ignored after stop, no error
    assert all(e.kind == "partial" for e in await collect(stream))
    assert fake.SpeechRecognizer.created[0].stopped


async def test_a_failing_stop_does_not_leak_an_exception(make_settings):
    stt, _, _ = make(make_settings, Scenario(final={"text": "ok"}, stop_error=True))
    stream = await open_stream(stt)
    await feed(stream)
    await stream.flush()
    assert [e.text for e in await collect(stream)] == ["ok"]


async def test_audio_written_after_the_input_is_closed_is_dropped(make_settings):
    stt, _, _ = make(make_settings, Scenario(final={"text": "ok"}))
    stream = await open_stream(stt)
    await feed(stream)
    await stream.flush()
    await stream.push_audio(PCM)
    assert len(fake.SpeechRecognizer.created[0].audio.stream.chunks) == 6


@pytest.mark.parametrize("rate", [8000, 16000, 24000])
async def test_the_push_stream_uses_the_callers_sample_rate(make_settings, rate):
    stt, _, _ = make(make_settings, Scenario(final={"text": "ok"}))
    stream = await open_stream(stt, rate=rate)
    await stream.stop_stream()
    assert fake.SpeechRecognizer.created[0].audio.stream.format.samples_per_second == rate
    with pytest.raises(ProviderRejected, match="sample rate"):
        await open_stream(stt, rate=1000)


async def test_a_missing_sdk_or_configuration_is_unavailable_not_a_crash(make_settings):
    def missing():
        raise ImportError("no module")

    rest = AzureSpeechToText(make_settings())
    stt = SdkSpeechToText(make_settings(), rest=rest, sdk_loader=missing)
    with pytest.raises(ProviderUnavailable, match="not installed"):
        await open_stream(stt)
    keyless, _, _ = make(make_settings, azure_speech_key=None)
    with pytest.raises(ProviderUnavailable, match="key"):
        await open_stream(keyless)
    regionless, _, _ = make(make_settings, azure_speech_region=None)
    with pytest.raises(ProviderUnavailable, match="region"):
        await open_stream(regionless)


async def test_a_custom_domain_endpoint_is_passed_to_the_sdk(make_settings):
    endpoint = "https://sparta-speech.cognitiveservices.azure.com"
    stt, _, _ = make(make_settings, Scenario(), azure_speech_endpoint=endpoint, azure_speech_region=None)
    stream = await open_stream(stt)
    await stream.stop_stream()
    config = fake.SpeechRecognizer.created[0].config
    assert config.endpoint == endpoint and config.region is None and config.subscription == "test-speech-key"


async def test_one_shot_transcription_stays_on_the_rest_adapter(make_settings):
    class Rest:
        async def transcribe(self, audio, **kwargs):
            return ("rest", audio, kwargs["trace_id"])

        async def aclose(self):
            self.closed = True

    rest = Rest()
    stt = SdkSpeechToText(make_settings(), rest=rest, sdk_loader=make_sdk)  # type: ignore[arg-type]
    result = await stt.transcribe(
        b"x", content_type="audio/wav", candidate_locales=LOCALES, locale_hint=None, trace_id="t9"
    )
    assert result == ("rest", b"x", "t9")
    await stt.aclose()
    assert rest.closed


@pytest.mark.parametrize(
    ("mode", "installed", "streaming"),
    [("off", True, False), ("auto", True, True), ("auto", False, False), ("on", True, True)],
)
def test_streaming_is_chosen_by_setting_and_availability(make_settings, monkeypatch, mode, installed, streaming):
    monkeypatch.setattr(azure_sdk, "sdk_available", lambda: installed)
    rest = AzureSpeechToText(make_settings())
    chosen = build_stt(make_settings(azure_speech_streaming=mode), rest, clock=None, metrics=Metrics())  # type: ignore[arg-type]
    assert isinstance(chosen, SdkSpeechToText) is streaming


def test_requiring_streaming_without_the_sdk_fails_configuration(make_settings, monkeypatch):
    from sparta import config

    monkeypatch.setattr(config, "_module_available", lambda name: False)
    problems = make_settings(stt_provider="azure", azure_speech_streaming="on").problems()
    assert any("azure-cognitiveservices-speech" in p for p in problems)
    assert not any("azure-cognitiveservices-speech" in p for p in make_settings(stt_provider="azure").problems())


def test_the_names_used_exist_in_the_real_sdk():
    """Guards against SDK drift: every SDK name the adapter touches must exist, and the real classes must construct."""
    pytest.importorskip("azure.cognitiveservices.speech", reason="Speech SDK not installed")
    sdk = azure_sdk.load_sdk()
    for name in (
        "SpeechConfig",
        "SpeechRecognizer",
        "OutputFormat",
        "PropertyId",
        "ResultReason",
        "CancellationReason",
    ):
        assert hasattr(sdk, name), name
    assert hasattr(sdk.OutputFormat, "Detailed")
    for name in (
        "SpeechServiceConnection_LanguageIdMode",
        "SpeechServiceConnection_AutoDetectSourceLanguageResult",
        "SpeechServiceResponse_JsonResult",
        "SpeechServiceResponse_RecognitionLatencyMs",
    ):
        assert hasattr(sdk.PropertyId, name), name
    assert hasattr(sdk.ResultReason, "RecognizedSpeech") and hasattr(sdk.CancellationReason, "Error")
    for name in ("AudioStreamFormat", "PushAudioInputStream", "AudioConfig"):
        assert hasattr(sdk.audio, name), name
    assert hasattr(sdk.languageconfig, "AutoDetectSourceLanguageConfig")
    for name in ("recognizing", "recognized", "canceled", "session_stopped"):
        assert hasattr(sdk.SpeechRecognizer, name), name
    for name in ("start_continuous_recognition_async", "stop_continuous_recognition_async"):
        assert hasattr(sdk.SpeechRecognizer, name), name
    # Construction does not connect: it proves the keyword names and the object graph are right.
    config = sdk.SpeechConfig(subscription="not-a-real-key", region="centralindia")
    config.output_format = sdk.OutputFormat.Detailed
    config.set_property(sdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous")
    push = sdk.audio.PushAudioInputStream(
        stream_format=sdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
    )
    detect = sdk.languageconfig.AutoDetectSourceLanguageConfig(languages=LOCALES)
    recogniser = sdk.SpeechRecognizer(
        speech_config=config, audio_config=sdk.audio.AudioConfig(stream=push), auto_detect_source_language_config=detect
    )
    assert recogniser is not None
    push.close()


def test_sdk_availability_reflects_the_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.cognitiveservices.speech", None)  # an import of it now raises ImportError
    assert sdk_available() is False
