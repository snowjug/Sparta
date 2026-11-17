"""Azure text-to-speech adapter against mocked HTTP: request shape, 20 ms framing, errors and barge-in."""

import asyncio
import contextlib
import xml.etree.ElementTree as ET  # parsing our own generated SSML only

import httpx
import pytest

from sparta.observability.metrics import AUDIO_SECONDS, PROVIDER_ERRORS, Metrics
from sparta.providers.base import (
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
    SynthesisRequest,
    TextToSpeechProvider,
)
from sparta.providers.tts.azure import OUTPUT_FORMATS, AzureTextToSpeech
from sparta.providers.tts.catalog import VOICE_CATALOG
from sparta.providers.tts.ssml import build_ssml

from .helpers import MockHttp

URL = "https://centralindia.tts.speech.microsoft.com/cognitiveservices/v1"
KEY = "test-speech-key"
SSML_NS = {"s": "http://www.w3.org/2001/10/synthesis"}


def req(**kw) -> SynthesisRequest:
    values = {"text": "Hello, this is the assistant.", "locale": "en-IN", "voice_id": None, "trace_id": "pb_1"}
    values.update(kw)
    return SynthesisRequest(**values)


def audio(n: int) -> bytes:
    return bytes((i * 7) % 251 + 1 for i in range(n))


def streamed(*pieces, closed: list[bool] | None = None, status: int = 200):
    """A response factory whose body arrives piece by piece. An ``asyncio.Event`` piece is a gate."""

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for piece in pieces:
                if isinstance(piece, asyncio.Event):
                    await piece.wait()
                elif isinstance(piece, BaseException):
                    raise piece
                else:
                    yield piece

        async def aclose(self) -> None:
            if closed is not None:
                closed.append(True)

    return lambda request: httpx.Response(status, stream=Body())


def make(make_settings, fast_clock, *script, metrics=None, **overrides):
    http = MockHttp(*script)
    tts = AzureTextToSpeech(make_settings(**overrides), http=http.client, clock=fast_clock, metrics=metrics)
    return tts, http


async def collect(tts: AzureTextToSpeech, request: SynthesisRequest):
    return [chunk async for chunk in tts.synthesize_stream(request)]


# ------------------------------------------------------------------------------------- request shape
async def test_synthesis_posts_the_documented_ssml_request(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(200, content=audio(6400)))
    chunks = await collect(tts, req(text="Namaste", locale="hi-IN", voice_id="hi-IN-SwaraNeural", rate=1.1))

    request = http.last
    assert request.method == "POST" and str(request.url) == URL
    assert request.headers["ocp-apim-subscription-key"] == KEY
    assert request.headers["content-type"] == "application/ssml+xml"
    assert request.headers["x-microsoft-outputformat"] == "raw-16khz-16bit-mono-pcm"
    assert request.headers["user-agent"] == "sparta"
    assert "authorization" not in request.headers
    assert request.content.decode() == build_ssml("Namaste", "hi-IN", "hi-IN-SwaraNeural", 1.1)
    assert chunks and all(c.sample_rate == 16000 and c.encoding == "pcm16" for c in chunks)


async def test_a_custom_endpoint_uses_the_tts_path_prefix(make_settings, fast_clock):
    tts, http = make(
        make_settings,
        fast_clock,
        httpx.Response(200, content=audio(640)),
        azure_speech_endpoint="https://sparta-speech.cognitiveservices.azure.com/",
    )
    await collect(tts, req())
    assert str(http.last.url) == "https://sparta-speech.cognitiveservices.azure.com/tts/cognitiveservices/v1"


@pytest.mark.parametrize(
    ("fmt", "header", "rate", "encoding"),
    [
        ("pcm16_8k", "raw-8khz-16bit-mono-pcm", 8000, "pcm16"),
        ("pcm16_16k", "raw-16khz-16bit-mono-pcm", 16000, "pcm16"),
        ("pcm16_24k", "raw-24khz-16bit-mono-pcm", 24000, "pcm16"),
        ("mulaw_8k", "raw-8khz-8bit-mono-mulaw", 8000, "mulaw"),
        ("alaw_8k", "raw-8khz-8bit-mono-alaw", 8000, "alaw"),
    ],
)
async def test_output_formats_map_to_the_verified_headers(make_settings, fast_clock, fmt, header, rate, encoding):
    tts, http = make(make_settings, fast_clock, httpx.Response(200, content=audio(1000)))
    chunks = await collect(tts, req(output_format=fmt))
    assert http.last.headers["x-microsoft-outputformat"] == header
    assert {(c.sample_rate, c.encoding) for c in chunks} == {(rate, encoding)}
    assert set(OUTPUT_FORMATS) == {"pcm16_8k", "pcm16_16k", "pcm16_24k", "mulaw_8k", "alaw_8k"}


async def test_the_style_element_is_present_only_when_a_style_is_requested(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(200, content=audio(640)))
    await collect(tts, req())
    assert "express-as" not in http.last.content.decode()
    await collect(tts, req(style="empathetic"))
    body = http.last.content.decode()
    assert '<mstts:express-as style="empathetic">' in body
    assert body == build_ssml("Hello, this is the assistant.", "en-IN", "en-IN-NeerjaNeural", 1.0, "empathetic")


async def test_text_is_xml_escaped_and_illegal_control_characters_are_removed(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(200, content=audio(640)))
    await collect(tts, req(text="Tom & Jerry <break time='5s'/> \x00\x0bsay \x1f\"hi\""))
    body = http.last.content.decode()
    assert "<break" not in body and "&lt;break" in body and "&amp;" in body
    assert "\x00" not in body and "\x0b" not in body and "\x1f" not in body
    root = ET.fromstring(body)
    assert root.tag.endswith("speak") and root.find(".//s:voice", SSML_NS) is not None


async def test_default_voices_follow_the_locale(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(200, content=audio(640)))
    for locale, voice in [
        ("en-IN", "en-IN-NeerjaNeural"),
        ("hi-IN", "hi-IN-SwaraNeural"),
        ("kn-IN", "kn-IN-SapnaNeural"),
    ]:
        await collect(tts, req(locale=locale))
        assert f'<voice name="{voice}">' in http.last.content.decode()


@pytest.mark.parametrize(
    "overrides",
    [
        {"voice_id": "en-IN-NoSuchNeural"},
        {"voice_id": "hi-IN-SwaraNeural"},  # a real voice, but not for en-IN
        {"voice_id": 'en-IN-NeerjaNeural"><evil/>'},
        {"locale": "fr-FR"},
        {"text": "   "},
        {"text": "x" * 2001},
        {"rate": float("nan")},
        {"rate": float("inf")},
        {"output_format": "mp3_48k"},
        {"style": 'cheerful"><x/>'},
        {"style": "Bad Style"},
    ],
)
async def test_invalid_requests_are_rejected_before_any_network_call(make_settings, fast_clock, overrides):
    tts, http = make(make_settings, fast_clock, httpx.Response(200, content=audio(640)))
    with pytest.raises(ProviderRejected) as err:
        await collect(tts, req(**overrides))
    assert http.requests == [] and not err.value.retryable


# --------------------------------------------------------------------------------------- framing
def frame_cases():
    # (output format, frame bytes, silence byte)
    return [
        ("pcm16_16k", 640, 0x00),
        ("pcm16_8k", 320, 0x00),
        ("pcm16_24k", 960, 0x00),
        ("mulaw_8k", 160, 0xFF),
        ("alaw_8k", 160, 0xD5),
    ]


@pytest.mark.parametrize(("fmt", "frame", "silence"), frame_cases())
@pytest.mark.parametrize("length_in_frames", [0.5, 1, 5, 5.25, 12.4, 22])
async def test_chunks_are_whole_20ms_frames_padded_with_silence_and_only_the_last_is_final(
    make_settings, fast_clock, fmt, frame, silence, length_in_frames
):
    body = audio(int(frame * length_in_frames))
    tts, _ = make(make_settings, fast_clock, httpx.Response(200, content=body))
    chunks = await collect(tts, req(output_format=fmt))

    assert [c.seq for c in chunks] == list(range(len(chunks)))
    assert [c.final for c in chunks] == [False] * (len(chunks) - 1) + [True]
    assert all(len(c.data) % frame == 0 and 0 < len(c.data) <= frame * 5 for c in chunks)
    joined = b"".join(c.data for c in chunks)
    assert joined[: len(body)] == body
    padding = joined[len(body) :]
    assert len(padding) < frame and set(padding) <= {silence}


async def test_audio_is_identical_whether_the_body_arrives_at_once_or_in_odd_pieces(make_settings, fast_clock):
    body = audio(10_001)
    whole, _ = make(make_settings, fast_clock, httpx.Response(200, content=body))
    pieces = [body[i : i + 777] for i in range(0, len(body), 777)]
    split, _ = make(make_settings, fast_clock, streamed(*pieces))
    one = await collect(whole, req())
    two = await collect(split, req())
    assert [(c.seq, c.data, c.final) for c in one] == [(c.seq, c.data, c.final) for c in two]
    assert len(one) == 4 and [len(c.data) for c in one] == [3200, 3200, 3200, 640]


async def test_chunks_are_yielded_while_the_body_is_still_arriving(make_settings, fast_clock):
    gate, closed = asyncio.Event(), []
    first = audio(3200 * 2 + 10)
    tts, _ = make(make_settings, fast_clock, streamed(first, gate, audio(640), closed=closed))
    stream = tts.synthesize_stream(req())
    got = [await stream.__anext__(), await stream.__anext__()]
    assert [c.final for c in got] == [False, False] and not closed  # the rest of the body has not arrived yet
    gate.set()
    rest = [c async for c in stream]
    assert rest[-1].final and closed


async def test_an_empty_body_is_an_error_not_silence(make_settings, fast_clock):
    tts, _ = make(make_settings, fast_clock, httpx.Response(200, content=b""))
    with pytest.raises(ProviderError, match="no audio returned") as err:
        await collect(tts, req())
    assert not err.value.retryable


async def test_synthesized_seconds_are_recorded_in_the_metrics(make_settings, fast_clock):
    metrics = Metrics()
    tts, _ = make(make_settings, fast_clock, httpx.Response(200, content=audio(32_000)), metrics=metrics)
    await collect(tts, req())
    assert metrics.counter(AUDIO_SECONDS, provider="azure-speech", direction="tts") == pytest.approx(1.0)


# ------------------------------------------------------------------------------------ error mapping
@pytest.mark.parametrize("status", [400, 415, 422])
async def test_rejections_are_not_retried_and_never_echo_the_body(make_settings, fast_clock, status):
    tts, http = make(make_settings, fast_clock, httpx.Response(status, text="SSML invalid near SECRET-BODY"))
    with pytest.raises(ProviderRejected) as err:
        await collect(tts, req())
    assert len(http.requests) == 1 and err.value.status == status and "SECRET-BODY" not in str(err.value)


@pytest.mark.parametrize("status", [401, 403])
async def test_authentication_failures_are_not_retryable(make_settings, fast_clock, status):
    tts, http = make(make_settings, fast_clock, httpx.Response(status, text=f"key {KEY} rejected"))
    with pytest.raises(ProviderRejected) as err:
        await collect(tts, req())
    assert err.value.message == "authentication failed" and len(http.requests) == 1 and KEY not in str(err.value)


async def test_redirects_are_not_followed(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(307, headers={"location": "https://evil.example/"}))
    with pytest.raises(ProviderError) as err:
        await collect(tts, req())
    assert len(http.requests) == 1 and not err.value.retryable


async def test_rate_limits_and_outages_are_retried_before_any_audio_is_yielded(make_settings, fast_clock):
    script = [
        httpx.Response(429, headers={"retry-after": "1"}),
        httpx.Response(503),
        httpx.Response(200, content=audio(640)),
    ]
    tts, http = make(make_settings, fast_clock, *script)
    chunks = await collect(tts, req())
    assert len(http.requests) == 3 and fast_clock.sleeps == [1.0, 0.4] and chunks[-1].final


async def test_a_persistent_outage_raises_a_sanitised_retryable_error(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(503, text=f"boom {KEY}"))
    with pytest.raises(ProviderError) as err:
        await collect(tts, req())
    assert err.value.retryable and err.value.status == 503 and len(http.requests) == 3 and KEY not in str(err.value)


async def test_a_slow_first_byte_times_out_through_the_resilient_caller(make_settings, fast_clock):
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, content=audio(640))

    tts, http = make(make_settings, fast_clock, slow, provider_timeout_s=0.02, provider_max_retries=1)
    with pytest.raises(ProviderTimeout):
        await collect(tts, req())
    assert len(http.requests) == 2


async def test_transport_errors_are_sanitised(make_settings, fast_clock):
    boom = httpx.ConnectError(f"cannot connect to https://centralindia.tts.speech.microsoft.com/?key={KEY}")
    tts, _ = make(make_settings, fast_clock, boom)
    with pytest.raises(ProviderError) as err:
        await collect(tts, req())
    assert err.value.message == "network error" and KEY not in str(err.value)


async def test_a_failure_in_the_middle_of_the_body_is_reported_and_is_not_retried(make_settings, fast_clock):
    metrics, closed = Metrics(), []
    tts, http = make(
        make_settings,
        fast_clock,
        streamed(audio(4000), httpx.ReadError(f"connection reset {KEY}"), closed=closed),
        metrics=metrics,
    )
    stream = tts.synthesize_stream(req())
    first = await stream.__anext__()
    assert not first.final
    with pytest.raises(ProviderError) as err:
        await stream.__anext__()
    assert err.value.message == "audio stream interrupted" and not err.value.retryable and KEY not in str(err.value)
    assert len(http.requests) == 1 and closed
    assert metrics.counter(PROVIDER_ERRORS, provider="azure-speech", stage="tts", kind="stream_interrupted") == 1


async def test_a_stalled_body_times_out(make_settings, fast_clock):
    tts, _ = make(make_settings, fast_clock, streamed(audio(4000), asyncio.Event()), provider_timeout_s=0.05)
    stream = tts.synthesize_stream(req())
    await stream.__anext__()
    with pytest.raises(ProviderTimeout):
        await stream.__anext__()


async def test_repeated_failures_open_the_circuit(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(500), provider_max_retries=0)
    for _ in range(5):
        with pytest.raises(ProviderError):
            await collect(tts, req())
    with pytest.raises(ProviderUnavailable, match="circuit open"):
        await collect(tts, req())
    assert len(http.requests) == 5


# ----------------------------------------------------------------------------------- barge-in / stop
async def test_stop_playback_cancels_the_in_flight_synthesis_promptly(make_settings, fast_clock):
    gate, closed = asyncio.Event(), []
    tts, _ = make(make_settings, fast_clock, streamed(audio(7000), gate, audio(7000), closed=closed))
    stream = tts.synthesize_stream(req(trace_id="pb_7"))
    await stream.__anext__()
    assert "pb_7" in tts._active

    await tts.stop_playback("pb_7")
    rest = await asyncio.wait_for(_drain(stream), timeout=1)
    assert rest == [] and closed and tts._active == {}  # no final chunk, response closed, registry cleaned


async def _drain(stream):
    return [chunk async for chunk in stream]


async def test_stop_playback_during_the_http_round_trip_cancels_the_request(make_settings, fast_clock):
    started = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(30)
        return httpx.Response(200, content=audio(640))

    tts, http = make(make_settings, fast_clock, slow, provider_timeout_s=60)
    task = asyncio.create_task(collect(tts, req(trace_id="pb_8")))
    await started.wait()
    await tts.stop_playback("pb_8")
    assert await asyncio.wait_for(task, timeout=1) == [] and tts._active == {} and len(http.requests) == 1


async def test_stop_playback_matches_by_handle_and_stops_every_synthesis_under_it(make_settings, fast_clock):
    gate = asyncio.Event()
    tts, _ = make(make_settings, fast_clock, streamed(audio(7000), gate, audio(640)))
    a, b, other = (tts.synthesize_stream(req(trace_id=t)) for t in ("call_1", "call_1", "call_2"))
    for stream in (a, b, other):
        await stream.__anext__()
    await tts.stop_playback("call_1")
    assert await asyncio.wait_for(_drain(a), 1) == [] and await asyncio.wait_for(_drain(b), 1) == []
    assert list(tts._active) == ["call_2"]  # the unrelated synthesis is untouched
    gate.set()
    assert (await _drain(other))[-1].final
    await tts.stop_playback("unknown-handle")  # harmless no-op


async def test_a_request_without_a_trace_id_is_never_registered(make_settings, fast_clock):
    gate = asyncio.Event()
    tts, _ = make(make_settings, fast_clock, streamed(audio(7000), gate, audio(640)))
    stream = tts.synthesize_stream(req(trace_id=""))
    await stream.__anext__()
    assert tts._active == {}
    await tts.stop_playback("")
    gate.set()
    assert (await _drain(stream))[-1].final


async def test_closing_the_stream_early_releases_everything(make_settings, fast_clock):
    gate, closed = asyncio.Event(), []
    tts, _ = make(make_settings, fast_clock, streamed(audio(7000), gate, audio(7000), closed=closed))
    async with contextlib.aclosing(tts.synthesize_stream(req(trace_id="pb_9"))) as stream:
        await stream.__anext__()
    assert closed and tts._active == {}


async def test_aclose_stops_active_synthesis_and_closes_only_an_owned_client(make_settings, fast_clock):
    gate = asyncio.Event()
    tts, http = make(make_settings, fast_clock, streamed(audio(7000), gate, audio(640)))
    stream = tts.synthesize_stream(req())
    await stream.__anext__()
    await tts.aclose()
    assert await asyncio.wait_for(_drain(stream), 1) == [] and not http.client.is_closed
    await http.client.aclose()

    owning = AzureTextToSpeech(make_settings())
    await owning.aclose()
    assert owning._http.is_closed


# ------------------------------------------------------------------------------------- catalogue
async def test_list_voices_is_the_verified_catalogue_and_never_touches_the_network(make_settings, fast_clock):
    tts, http = make(make_settings, fast_clock, httpx.Response(500))
    assert [v.id for v in await tts.list_voices()] == [v.id for v in VOICE_CATALOG]
    kn = await tts.list_voices("kn-IN")
    assert {v.id for v in kn} == {"kn-IN-SapnaNeural", "kn-IN-GaganNeural"} and all(v.verified for v in kn)
    assert await tts.list_voices("fr-FR") == [] and http.requests == []


# -------------------------------------------------------------------------------- configuration
@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"azure_speech_key": None}, "key"),
        ({"azure_speech_region": None}, "region or endpoint"),
        ({"azure_speech_region": "evil.example/x?"}, "region or endpoint"),
        ({"azure_speech_endpoint": "http://plain.example"}, "https"),
    ],
)
async def test_misconfiguration_fails_fast_without_sending_anything(make_settings, fast_clock, overrides, needle):
    tts, http = make(make_settings, fast_clock, httpx.Response(200, content=audio(640)), **overrides)
    with pytest.raises(ProviderUnavailable, match=needle):
        await collect(tts, req())
    assert http.requests == [] and len(await tts.list_voices()) == len(VOICE_CATALOG)


async def test_meta_is_honest_and_protocol_conformant(make_settings, fast_clock):
    tts, _ = make(make_settings, fast_clock, httpx.Response(200, content=audio(640)))
    assert isinstance(tts, TextToSpeechProvider)
    assert (tts.meta.provider, tts.meta.simulated, tts.meta.model) == ("azure-speech", False, "neural")
