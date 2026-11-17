"""Azure Speech-to-text adapter against mocked HTTP: exact request shape, mapping, limits, errors and the stream."""

import asyncio
import json
import struct

import httpx
import pytest

from sparta.observability.metrics import PROVIDER_ERRORS, Metrics
from sparta.providers.azure_common import MAX_RETRY_AFTER_S
from sparta.providers.base import (
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
    SpeechToTextProvider,
    SttStream,
)
from sparta.providers.resilience import MAX_BACKOFF_S
from sparta.providers.stt.azure import (
    API_VERSION,
    MAX_AUDIO_BYTES,
    AzureSpeechToText,
    pcm16_to_wav,
    wav_duration_s,
)

from .helpers import MockHttp, multipart_parts

URL = "https://centralindia.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
KEY = "test-speech-key"
LOCALES = ["en-IN", "hi-IN", "kn-IN"]

FAST_JSON = {
    "durationMilliseconds": 4200,
    "combinedPhrases": [{"channel": 0, "text": "Namaste I am calling from your bank sir"}],
    "phrases": [
        {
            "channel": 0,
            "offsetMilliseconds": 40,
            "durationMilliseconds": 1500,
            "text": "Namaste",
            "locale": "hi-IN",
            "confidence": 0.9,
            "words": [],
        },
        {
            "channel": 0,
            "offsetMilliseconds": 1600,
            "durationMilliseconds": 1500,
            "text": "I am calling from your bank",
            "locale": "en-IN",
            "confidence": 0.7,
        },
        {
            "channel": 0,
            "offsetMilliseconds": 3200,
            "durationMilliseconds": 1000,
            "text": "sir",
            "locale": "en-IN",
            "confidence": 0.8,
        },
    ],
}


def ok(payload: object = FAST_JSON) -> httpx.Response:
    return httpx.Response(200, json=payload)


def pcm(ms: int, rate: int = 16000) -> bytes:
    return b"\x01\x02" * (rate * ms // 1000)


async def transcribe(stt: AzureSpeechToText, audio: bytes = b"RIFFdata", **kw):
    kw.setdefault("content_type", "audio/wav")
    kw.setdefault("candidate_locales", LOCALES)
    kw.setdefault("locale_hint", None)
    kw.setdefault("trace_id", "trace-1")
    return await stt.transcribe(audio, **kw)


def make(make_settings, fast_clock, *script, **overrides):
    http = MockHttp(*script)
    return AzureSpeechToText(make_settings(**overrides), http=http.client, clock=fast_clock), http


# ------------------------------------------------------------------------------------- request shape
async def test_transcribe_sends_the_documented_fast_transcription_request(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    audio = b"RIFF" + bytes(range(200))
    await transcribe(stt, audio, content_type="audio/wav")

    request = http.last
    assert request.method == "POST" and str(request.url) == URL
    assert API_VERSION == "2025-10-15"
    assert request.headers["ocp-apim-subscription-key"] == KEY
    assert "authorization" not in request.headers
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")

    parts = multipart_parts(request)
    assert set(parts) == {"audio", "definition"}
    audio_headers, audio_body = parts["audio"]
    assert audio_body == audio
    assert audio_headers["content-type"] == "audio/wav"
    assert 'filename="audio.wav"' in audio_headers["content-disposition"]
    assert json.loads(parts["definition"][1]) == {"locales": LOCALES, "profanityFilterMode": "None"}
    assert parts["definition"][1] == b'{"locales":["en-IN","hi-IN","kn-IN"],"profanityFilterMode":"None"}'


async def test_a_configured_custom_endpoint_replaces_the_regional_host(make_settings, fast_clock):
    stt, http = make(
        make_settings, fast_clock, ok(), azure_speech_endpoint="https://sparta-speech.cognitiveservices.azure.com/"
    )
    await transcribe(stt)
    assert str(http.last.url) == (
        "https://sparta-speech.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe"
        "?api-version=2025-10-15"
    )


@pytest.mark.parametrize(
    ("candidates", "hint"),
    [([], None), ([], "auto"), (["auto"], None), ([""], "und"), ([], "")],
)
async def test_automatic_language_identification_omits_locales(make_settings, fast_clock, candidates, hint):
    stt, http = make(make_settings, fast_clock, ok())
    await transcribe(stt, candidate_locales=candidates, locale_hint=hint)
    assert json.loads(multipart_parts(http.last)["definition"][1]) == {"profanityFilterMode": "None"}


async def test_a_lone_hint_is_sent_as_the_single_locale(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    await transcribe(stt, candidate_locales=[], locale_hint="hi-IN")
    assert json.loads(multipart_parts(http.last)["definition"][1])["locales"] == ["hi-IN"]


async def test_hint_goes_first_duplicates_are_dropped_and_candidates_are_capped(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    many = [f"x{chr(97 + i)}-IN" for i in range(14)]
    await transcribe(stt, candidate_locales=["en-IN", "HI-in", *many], locale_hint="hi-IN")
    sent = json.loads(multipart_parts(http.last)["definition"][1])["locales"]
    assert sent[:2] == ["hi-IN", "en-IN"] and len(sent) == 10 and len(set(map(str.lower, sent))) == 10


async def test_content_type_parameters_are_stripped_and_extensions_follow_the_type(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    await transcribe(stt, content_type="audio/wav; codecs=audio/pcm; samplerate=16000")
    headers, _ = multipart_parts(http.last)["audio"]
    assert headers["content-type"] == "audio/wav"

    await transcribe(stt, content_type="Audio/MPEG")
    headers, _ = multipart_parts(http.last)["audio"]
    assert headers["content-type"] == "audio/mpeg" and 'filename="audio.mp3"' in headers["content-disposition"]


# ---------------------------------------------------------------------------------------- mapping
async def test_the_response_is_mapped_to_a_transcript_result(make_settings, fast_clock):
    stt, _ = make(make_settings, fast_clock, ok())
    result = await transcribe(stt)
    assert result.text == "Namaste I am calling from your bank sir"
    assert result.language == "en-IN"  # the most common phrase locale
    assert result.confidence == pytest.approx(0.8)
    assert result.audio_seconds == pytest.approx(4.2) and result.usage.audio_seconds == pytest.approx(4.2)
    assert result.usage.requests == 1 and result.simulated is False
    assert [(s.kind, s.text, s.language, s.offset_ms, s.duration_ms) for s in result.segments] == [
        ("final", "Namaste", "hi-IN", 40, 1500),
        ("final", "I am calling from your bank", "en-IN", 1600, 1500),
        ("final", "sir", "en-IN", 3200, 1000),
    ]


async def test_combined_phrases_are_joined_in_channel_order_and_fall_back_to_phrases(make_settings, fast_clock):
    two_channels = {
        "combinedPhrases": [{"channel": 1, "text": "second"}, {"channel": 0, "text": "first"}],
        "phrases": [{"text": "ignored here", "locale": "en-IN"}],
    }
    stt, _ = make(make_settings, fast_clock, ok(two_channels))
    result = await transcribe(stt)
    assert result.text == "first second"
    # no durationMilliseconds at the top level: the duration comes from the last phrase
    assert result.audio_seconds == 0.0

    only_phrases = {
        "phrases": [{"text": "hello", "locale": "en-IN", "offsetMilliseconds": 10, "durationMilliseconds": 990}]
    }
    stt, _ = make(make_settings, fast_clock, ok(only_phrases))
    result = await transcribe(stt)
    assert result.text == "hello" and result.audio_seconds == pytest.approx(1.0)


async def test_silence_yields_an_empty_result_without_language_or_confidence(make_settings, fast_clock):
    stt, _ = make(
        make_settings, fast_clock, ok({"durationMilliseconds": 900, "combinedPhrases": [{"text": ""}], "phrases": []})
    )
    result = await transcribe(stt)
    assert (result.text, result.language, result.confidence, result.segments) == ("", None, None, [])


async def test_out_of_range_confidence_and_odd_locales_are_normalised(make_settings, fast_clock):
    payload = {"phrases": [{"text": "a", "locale": "not a locale!", "confidence": 7}, {"text": "b", "confidence": -3}]}
    stt, _ = make(make_settings, fast_clock, ok(payload))
    result = await transcribe(stt)
    assert result.language is None and result.confidence == pytest.approx(0.5)


async def test_the_transcript_hint_is_ignored_by_a_real_provider(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok({"combinedPhrases": [{"text": "what the audio said"}]}))
    result = await transcribe(stt, transcript_hint="what the caller wants us to believe")
    assert result.text == "what the audio said"
    assert b"believe" not in http.last.content


# ---------------------------------------------------------------------------------------- limits
@pytest.mark.parametrize(
    "kwargs",
    [
        {"audio": b""},
        {"audio": b"x" * (MAX_AUDIO_BYTES + 1)},
        {"content_type": "text/plain"},
        {"content_type": "audio/wav\r\nX-Injected: 1"},
        {"content_type": "application/octet-stream"},
        {"candidate_locales": ["en-IN\r\nX: y"]},
        {"locale_hint": "english please"},
    ],
)
async def test_sanity_limits_and_bad_input_are_rejected_before_anything_is_sent(make_settings, fast_clock, kwargs):
    stt, http = make(make_settings, fast_clock, ok())
    with pytest.raises(ProviderRejected) as err:
        await transcribe(stt, **kwargs)
    assert http.requests == [] and not err.value.retryable


async def test_a_lower_configured_size_limit_wins(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok(), max_audio_bytes=1000)
    with pytest.raises(ProviderRejected, match="too large"):
        await transcribe(stt, b"x" * 1001)
    assert http.requests == []


async def test_a_wav_longer_than_the_duration_limit_is_rejected_even_if_its_header_lies(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok(), max_audio_seconds=10)
    too_long = pcm16_to_wav(pcm(11_000), 16000)
    lying = too_long[:40] + struct.pack("<I", 100) + too_long[44:]  # claims a 100-byte data chunk
    for audio in (too_long, lying):
        with pytest.raises(ProviderRejected, match="too long"):
            await transcribe(stt, audio)
    assert http.requests == []
    await transcribe(stt, pcm16_to_wav(pcm(9_000), 16000))
    assert len(http.requests) == 1


def test_wav_helpers_build_and_read_canonical_headers():
    wav = pcm16_to_wav(pcm(1000), 16000)
    assert wav[:4] == b"RIFF" and wav[8:16] == b"WAVEfmt " and wav[36:40] == b"data"
    channels, rate, byte_rate, align, bits = struct.unpack("<HIIHH", wav[22:36])
    assert (channels, rate, byte_rate, align, bits) == (1, 16000, 32000, 2, 16)
    assert struct.unpack("<I", wav[40:44])[0] == 32000 and len(wav) == 44 + 32000
    assert wav_duration_s(wav) == pytest.approx(1.0)
    assert wav_duration_s(b"not a wav file at all, just some bytes that are long enough to look plausible....") is None
    assert wav_duration_s(wav[:30]) is None


# -------------------------------------------------------------------------------- error mapping
@pytest.mark.parametrize("status", [400, 415, 422, 413])
async def test_rejections_are_not_retried(make_settings, fast_clock, status):
    stt, http = make(make_settings, fast_clock, httpx.Response(status, text="detail: audio is corrupt SECRET-BODY"))
    with pytest.raises(ProviderRejected) as err:
        await transcribe(stt)
    assert len(http.requests) == 1 and not err.value.retryable and err.value.status == status
    assert "SECRET-BODY" not in str(err.value) and fast_clock.sleeps == []


@pytest.mark.parametrize("status", [401, 403])
async def test_authentication_failures_are_not_retryable_and_say_nothing_else(make_settings, fast_clock, status):
    stt, http = make(make_settings, fast_clock, httpx.Response(status, json={"error": {"message": f"bad key {KEY}"}}))
    with pytest.raises(ProviderRejected) as err:
        await transcribe(stt)
    assert err.value.message == "authentication failed" and not err.value.retryable and len(http.requests) == 1
    assert KEY not in str(err.value) and KEY not in repr(err.value)


async def test_a_missing_resource_is_a_non_retryable_configuration_error(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, httpx.Response(404, text="nope"))
    with pytest.raises(ProviderError) as err:
        await transcribe(stt)
    assert not err.value.retryable and err.value.status == 404 and len(http.requests) == 1


async def test_redirects_are_never_followed_because_the_request_carries_a_key(make_settings, fast_clock):
    redirect = httpx.Response(302, headers={"location": "https://evil.example/steal"})
    stt, http = make(make_settings, fast_clock, redirect)
    with pytest.raises(ProviderError) as err:
        await transcribe(stt)
    assert len(http.requests) == 1 and not err.value.retryable and "evil" not in str(err.value)


async def test_rate_limits_and_server_errors_are_retried_honouring_retry_after(make_settings, fast_clock):
    script = [
        httpx.Response(429, headers={"retry-after": "1"}),
        httpx.Response(503, headers={"retry-after-ms": "250"}),
        ok(),
    ]
    stt, http = make(make_settings, fast_clock, *script)
    assert (await transcribe(stt)).text
    assert len(http.requests) == 3 and fast_clock.sleeps == [1.0, 0.25]


async def test_a_hostile_retry_after_is_bounded(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, httpx.Response(429, headers={"retry-after": "86400"}), ok())
    await transcribe(stt)
    assert fast_clock.sleeps == [MAX_BACKOFF_S] and MAX_RETRY_AFTER_S >= MAX_BACKOFF_S
    assert len(http.requests) == 2


async def test_persistent_server_errors_raise_a_sanitised_retryable_error_after_the_retry_budget(
    make_settings, fast_clock
):
    metrics = Metrics()
    http = MockHttp(httpx.Response(503, text=f"internal detail {KEY} https://x?key=1"))
    stt = AzureSpeechToText(make_settings(), http=http.client, clock=fast_clock, metrics=metrics)
    with pytest.raises(ProviderError) as err:
        await transcribe(stt)
    assert len(http.requests) == 3 and err.value.retryable and err.value.status == 503
    assert KEY not in str(err.value) and "internal detail" not in str(err.value)
    assert metrics.counter(PROVIDER_ERRORS, provider="azure-speech", stage="stt", kind="ProviderError") == 3


async def test_a_slow_service_times_out_through_the_resilient_caller(make_settings, fast_clock):
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return ok()

    http = MockHttp(slow)  # type: ignore[arg-type]
    stt = AzureSpeechToText(
        make_settings(provider_timeout_s=0.02, provider_max_retries=1), http=http.client, clock=fast_clock
    )
    with pytest.raises(ProviderTimeout):
        await transcribe(stt)
    assert len(http.requests) == 2


async def test_transport_errors_are_retryable_and_never_leak_the_url(make_settings, fast_clock):
    boom = httpx.ConnectError(f"cannot reach https://centralindia.api.cognitive.microsoft.com/?key={KEY}")
    stt, http = make(make_settings, fast_clock, boom, ok())
    assert (await transcribe(stt)).text and len(http.requests) == 2

    stt, _ = make(make_settings, fast_clock, boom)
    with pytest.raises(ProviderError) as err:
        await transcribe(stt)
    assert err.value.message == "network error" and KEY not in str(err.value) and "centralindia" not in str(err.value)

    timeout = httpx.ReadTimeout("read timed out")
    stt, _ = make(make_settings, fast_clock, timeout)
    with pytest.raises(ProviderTimeout):
        await transcribe(stt)


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b"[1, 2]", b'{"phrases": "nope"}', b""])
async def test_an_unexpected_success_body_is_a_sanitised_non_retryable_error(make_settings, fast_clock, body):
    stt, http = make(make_settings, fast_clock, httpx.Response(200, content=body))
    with pytest.raises(ProviderError) as err:
        await transcribe(stt)
    assert err.value.message == "unexpected response format" and not err.value.retryable and len(http.requests) == 1
    assert "gateway" not in str(err.value)


async def test_an_oversized_response_is_refused(make_settings, fast_clock):
    stt, _ = make(make_settings, fast_clock, httpx.Response(200, content=b" " * 4_100_000))
    with pytest.raises(ProviderError, match="response too large"):
        await transcribe(stt)


async def test_repeated_failures_open_the_circuit_so_the_service_is_not_hammered(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, httpx.Response(500), provider_max_retries=0)
    for _ in range(5):
        with pytest.raises(ProviderError):
            await transcribe(stt)
    with pytest.raises(ProviderUnavailable, match="circuit open"):
        await transcribe(stt)
    assert len(http.requests) == 5


# ---------------------------------------------------------------------------------- configuration
@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"azure_speech_key": None}, "key"),
        ({"azure_speech_region": None}, "region or endpoint"),
        ({"azure_speech_region": "evil.example/x?"}, "region or endpoint"),
        ({"azure_speech_endpoint": "http://plain.example"}, "https"),
        ({"azure_speech_endpoint": "https://user:pw@example.com"}, "https"),
    ],
)
async def test_misconfiguration_fails_fast_without_sending_anything(make_settings, fast_clock, overrides, needle):
    stt, http = make(make_settings, fast_clock, ok(), **overrides)
    with pytest.raises(ProviderUnavailable, match=needle):
        await transcribe(stt)
    with pytest.raises(ProviderUnavailable):
        await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    assert http.requests == []


async def test_meta_is_honest_and_protocol_conformant(make_settings, fast_clock):
    stt, _ = make(make_settings, fast_clock, ok())
    assert isinstance(stt, SpeechToTextProvider)
    assert (stt.meta.provider, stt.meta.simulated, stt.meta.model, stt.meta.version) == (
        "azure-speech",
        False,
        "fast-transcription",
        "2025-10-15",
    )


async def test_aclose_closes_only_a_client_it_created(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    await stt.aclose()
    assert not http.client.is_closed
    await http.client.aclose()

    owning = AzureSpeechToText(make_settings())
    await owning.aclose()
    assert owning._http.is_closed


# ------------------------------------------------------------------------------------------ stream
async def drain(stream: SttStream) -> list:
    return [event async for event in stream.events()]


async def test_the_stream_is_utterance_based_and_emits_one_final_per_flush_and_no_partials(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint="hi-IN", trace_id="t1", sample_rate=16000)
    assert isinstance(stream, SttStream)
    for _ in range(5):
        await stream.push_audio(pcm(200))
    assert http.requests == []  # nothing is sent until the utterance ends
    await stream.flush()
    await stream.stop_stream()

    events = await drain(stream)
    assert [e.kind for e in events] == ["final"]
    final = events[0]
    assert final.text == "Namaste I am calling from your bank sir" and final.language == "en-IN"
    assert final.confidence == pytest.approx(0.8) and final.offset_ms == 0 and final.duration_ms == 1000

    audio_headers, wav = multipart_parts(http.last)["audio"]
    assert audio_headers["content-type"] == "audio/wav" and len(http.requests) == 1
    assert wav[:4] == b"RIFF" and wav[8:16] == b"WAVEfmt " and len(wav) == 44 + 32000
    assert wav_duration_s(wav) == pytest.approx(1.0)
    assert json.loads(multipart_parts(http.last)["definition"][1])["locales"] == [
        "hi-IN",
        *[loc for loc in LOCALES if loc != "hi-IN"],
    ]


async def test_successive_utterances_get_ordered_finals_with_running_offsets(make_settings, fast_clock):
    stt, _ = make(
        make_settings,
        fast_clock,
        ok({"combinedPhrases": [{"text": "one"}]}),
        ok({"combinedPhrases": [{"text": "two"}]}),
    )
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    await stream.push_audio(pcm(600))
    await stream.flush()
    await stream.push_audio(pcm(400))
    await stream.flush()
    await stream.stop_stream()
    events = await drain(stream)
    assert [(e.text, e.offset_ms, e.duration_ms) for e in events] == [("one", 0, 600), ("two", 600, 400)]


async def test_an_empty_flush_sends_nothing_and_a_blip_yields_an_empty_final_without_a_request(
    make_settings, fast_clock
):
    stt, http = make(make_settings, fast_clock, ok())
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    await stream.flush()
    await stream.push_audio(pcm(40))
    await stream.flush()
    await stream.stop_stream()
    events = await drain(stream)
    assert [(e.kind, e.text, e.duration_ms) for e in events] == [("final", "", 40)] and http.requests == []


async def test_an_utterance_without_speech_is_a_final_event_with_empty_text(make_settings, fast_clock):
    stt, _ = make(make_settings, fast_clock, ok({"durationMilliseconds": 800, "combinedPhrases": [], "phrases": []}))
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    await stream.push_audio(pcm(800))
    await stream.flush()
    await stream.stop_stream()
    assert [(e.kind, e.text, e.language, e.confidence) for e in await drain(stream)] == [("final", "", None, None)]


async def test_events_can_be_consumed_while_the_stream_is_live_and_end_on_stop(make_settings, fast_clock):
    stt, _ = make(make_settings, fast_clock, ok({"combinedPhrases": [{"text": "hello"}]}))
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    consumer = asyncio.create_task(drain(stream))
    await asyncio.sleep(0)
    assert not consumer.done()
    await stream.push_audio(pcm(500))
    await stream.flush()
    await stream.stop_stream()
    assert [e.text for e in await asyncio.wait_for(consumer, 1)] == ["hello"]
    assert await drain(stream) == []  # a second iterator also terminates once stopped


async def test_a_failed_flush_raises_but_the_stream_stays_usable(make_settings, fast_clock):
    stt, _ = make(
        make_settings, fast_clock, httpx.Response(400, text="bad"), ok({"combinedPhrases": [{"text": "recovered"}]})
    )
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    await stream.push_audio(pcm(500))
    with pytest.raises(ProviderRejected):
        await stream.flush()
    await stream.push_audio(pcm(500))
    await stream.flush()
    await stream.stop_stream()
    assert [e.text for e in await drain(stream)] == ["recovered"]


async def test_stop_stream_releases_buffers_and_later_calls_are_harmless(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    await stream.push_audio(pcm(500))
    await stream.stop_stream()
    assert len(stream._pcm) == 0  # type: ignore[attr-defined]
    await stream.push_audio(pcm(500))
    await stream.flush()
    await stream.stop_stream()
    assert http.requests == [] and await drain(stream) == []


async def test_a_stop_during_an_in_flight_flush_drops_its_result(make_settings, fast_clock):
    gate = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return ok()

    http = MockHttp(slow)  # type: ignore[arg-type]
    stt = AzureSpeechToText(make_settings(), http=http.client, clock=fast_clock)
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    await stream.push_audio(pcm(500))
    flushing = asyncio.create_task(stream.flush())
    await asyncio.sleep(0.01)
    await stream.stop_stream()
    gate.set()
    await flushing
    assert await drain(stream) == []


async def test_an_unbounded_utterance_is_rejected_and_the_buffer_is_released(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok(), max_audio_seconds=1)
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t")
    await stream.push_audio(pcm(900))
    with pytest.raises(ProviderRejected, match="maximum buffered audio"):
        await stream.push_audio(pcm(200))
    await stream.flush()  # nothing left to send
    await stream.stop_stream()
    assert http.requests == [] and await drain(stream) == []


@pytest.mark.parametrize("rate", [0, 4000, 96000])
async def test_unsupported_stream_sample_rates_are_rejected(make_settings, fast_clock, rate):
    stt, _ = make(make_settings, fast_clock, ok())
    with pytest.raises(ProviderRejected, match="sample rate"):
        await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t", sample_rate=rate)


async def test_an_odd_trailing_byte_is_dropped_not_sent_as_half_a_sample(make_settings, fast_clock):
    stt, http = make(make_settings, fast_clock, ok())
    stream = await stt.start_stream(candidate_locales=LOCALES, locale_hint=None, trace_id="t", sample_rate=8000)
    await stream.push_audio(pcm(500, 8000) + b"\x07")
    await stream.flush()
    await stream.stop_stream()
    _, wav = multipart_parts(http.last)["audio"]
    assert len(wav) == 44 + 8000 and struct.unpack("<I", wav[24:28])[0] == 8000
