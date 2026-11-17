"""Azure Communication Services adapter: media frames, pacing, barge-in, provider flows and the SDK client.

Everything runs against fakes (SDK client, WebSocket, TTS, event sink): no live ACS behaviour is verified here.
"""

import asyncio
import base64
import json
import logging
import random
from types import SimpleNamespace

import httpx
import pytest

from sparta.clock import VirtualClock
from sparta.config import ConfigurationError
from sparta.domain.enums import ProviderKind
from sparta.domain.models import SpeechPlan
from sparta.observability.metrics import PROVIDER_ERRORS, Metrics
from sparta.providers.base import ProviderError, ProviderRejected, ProviderUnavailable
from sparta.providers.resilience import BreakerState
from sparta.telephony import azure_acs
from sparta.telephony.azure_acs import (
    ACS_MEDIA_MAX_LIFETIME_S,
    AcsClientPort,
    AcsMediaSession,
    AzureAcsTelephonyProvider,
    SdkAcsClient,
    WebSocketLike,
    build_acs_provider,
)
from sparta.telephony.base import ProviderCallRef, TelephonyProvider
from sparta.telephony.webhooks import EventGridEvent

from .conftest import ACS_RESOURCE
from .helpers import (
    FakeAcsClient,
    FakeSink,
    FakeTts,
    FakeWebSocket,
    FastClock,
    MockHttp,
    claims,
    jwks_response,
)

CALL = "call_test0001"
SERVER_CALL = "server-call-id-1"
CONTEXT = "incoming-call-context-token"
CALLER, CALLED = "+919876543210", "+14255550123"
FRAME_16K = 640


def pcm(value: int = 1, rate: int = 16000, frames: int = 1) -> bytes:
    return bytes([value]) * (rate * 20 // 1000 * 2 * frames)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def audio_msg(data: bytes | str | None, *, silent: bool = False, **extra) -> dict:
    payload = {"timestamp": "2026-11-17T10:00:00Z", "participantRawID": f"4:{CALLER}", "silent": silent}
    if data is not None:
        payload["data"] = b64(data) if isinstance(data, bytes) else data
    payload.update(extra)
    return {"kind": "AudioData", "audioData": payload}


def meta_msg(rate: int = 16000, channels: int = 1, encoding: str = "PCM") -> dict:
    return {
        "kind": "AudioMetadata",
        "audioMetadata": {
            "subscriptionId": "sub-1",
            "encoding": encoding,
            "sampleRate": rate,
            "channels": channels,
            "length": rate * 20 // 1000 * 2,
        },
    }


async def settle(rounds: int = 25) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def drive(clock: VirtualClock, seconds: float, step: float = 0.02) -> None:
    """Advance virtual time in 20 ms steps, letting woken tasks run in between."""
    for _ in range(round(seconds / step)):
        await settle(4)
        await clock.advance(step)
    await settle(4)


def make_session(sink=None, ws=None, clock=None, **kw):
    clock = clock or VirtualClock()
    ws = ws or FakeWebSocket(clock)
    sink = sink or FakeSink()
    return AcsMediaSession(CALL, ws, sink, clock=clock, **kw), ws, sink, clock


# ====================================================================================== media: inbound
async def test_metadata_sets_the_sample_rate_and_audio_is_forwarded_to_the_sink():
    session, _, sink, _ = make_session()
    await session.handle_message(json.dumps(meta_msg(24000)))
    await session.handle_message(json.dumps(audio_msg(pcm(3, 24000))))
    assert session.sample_rate == 24000 and session.frame_bytes == 960
    assert sink.audio == [(CALL, pcm(3, 24000), 24000)]
    assert (session.stats["metadata"], session.stats["audio_frames"]) == (1, 1)


async def test_audio_before_metadata_assumes_the_requested_16khz_format():
    session, _, sink, _ = make_session()
    await session.handle_message(json.dumps(audio_msg(pcm(5))))
    assert sink.audio == [(CALL, pcm(5), 16000)] and session.frame_bytes == FRAME_16K


@pytest.mark.parametrize("rewrite", [str.lower, str.upper, lambda s: s])
async def test_inbound_key_casing_is_not_trusted(rewrite):
    session, _, sink, _ = make_session()
    text = json.dumps(audio_msg(pcm(4)))
    keys_only = json.loads(text, object_pairs_hook=lambda pairs: {rewrite(k): v for k, v in pairs})
    keys_only["kind" if "kind" in keys_only else rewrite("kind")] = "AudioData"
    await session.handle_message(json.dumps(keys_only))
    assert sink.audio == [(CALL, pcm(4), 16000)]


async def test_silent_frames_are_forwarded_so_the_vad_timeline_is_intact():
    session, _, sink, _ = make_session()
    await session.handle_message(json.dumps(audio_msg(bytes(FRAME_16K), silent=True)))
    await session.handle_message(json.dumps(audio_msg(None, silent=True)))  # a silent frame without a payload
    assert sink.audio == [(CALL, bytes(FRAME_16K), 16000)] * 2
    await session.handle_message(json.dumps(audio_msg(None, silent=False)))
    assert len(sink.audio) == 2 and session.stats["bad_audio"] == 1


@pytest.mark.parametrize(("sent", "expected"), [("3", "3"), ("#", "#"), ("*", "*"), ("a", "A"), ("D", "D")])
async def test_dtmf_digits_are_forwarded_upper_cased(sent, expected):
    session, _, sink, _ = make_session()
    await session.handle_message(json.dumps({"kind": "DtmfData", "dtmfData": {"data": sent}}))
    assert sink.dtmf == [(CALL, expected)]


@pytest.mark.parametrize("bad", ["12", "x", "", None, 5, ["1"], "\n", "٣"])
async def test_anything_that_is_not_a_single_dtmf_digit_is_dropped(bad):
    session, _, sink, _ = make_session()
    await session.handle_message(json.dumps({"kind": "DtmfData", "dtmfData": {"data": bad}}))
    assert sink.dtmf == [] and session.stats["bad_dtmf"] == 1


async def test_unknown_frame_kinds_are_ignored_and_are_not_abuse():
    session, _, sink, _ = make_session(max_invalid_frames=2)
    for kind in ("TranscriptionData", "TranscriptionMetadata", "SomethingNew", "audiodata_v2"):
        await session.handle_message(json.dumps({"kind": kind, kind[0].lower() + kind[1:]: {"x": 1}}))
    assert session.stats["ignored_kind"] == 4 and not session.closed and sink.audio == []


BAD_METADATA = [
    meta_msg(channels=2),
    meta_msg(encoding="MULAW"),
    meta_msg(rate=44100),
    meta_msg(rate=0),
    {"kind": "AudioMetadata", "audioMetadata": {"sampleRate": "16000", "channels": 1, "encoding": "PCM"}},
    {"kind": "AudioMetadata", "audioMetadata": {"sampleRate": True, "channels": True, "encoding": "PCM"}},
    {"kind": "AudioMetadata", "audioMetadata": None},
]


@pytest.mark.parametrize("metadata", BAD_METADATA)
async def test_unsupported_audio_formats_are_never_fed_to_the_pipeline_until_a_good_format_arrives(metadata):
    session, _, sink, _ = make_session()
    await session.handle_message(json.dumps(metadata))
    await session.handle_message(json.dumps(audio_msg(pcm(9))))
    assert sink.audio == [] and session.stats["bad_format"] >= 2
    await session.handle_message(json.dumps(meta_msg(16000)))
    await session.handle_message(json.dumps(audio_msg(pcm(9))))
    assert sink.audio == [(CALL, pcm(9), 16000)]


MALFORMED = [
    "",
    "not json",
    "{",
    "[]",
    "null",
    "42",
    '"just a string"',
    "{}",
    '{"kind": 5}',
    '{"kind": null}',
    '{"kind": "AudioData"}',
    '{"kind": "AudioData", "audioData": "x"}',
    '{"kind": "AudioData", "audioData": null}',
    '{"kind": "AudioData", "audioData": []}',
    '{"kind": "AudioData", "audioData": {"data": 123}}',
    '{"kind": "AudioData", "audioData": {"data": "***not base64***"}}',
    '{"kind": "AudioData", "audioData": {"data": "AAA"}}',  # bad padding
    '{"kind": "AudioData", "audioData": {"data": "AAAA"}}',  # 3 bytes: not whole PCM16 samples
    '{"kind": "AudioData", "audioData": {"data": ""}}',
    '{"kind": "AudioData", "audioData": {"data": "\u00e9\u00e9\u00e9\u00e9"}}',
    '{"kind": "AudioData", "audioData": {"data": "' + "A" * 60_000 + '"}}',
    '{"kind": "DtmfData"}',
    '{"kind": "DtmfData", "dtmfData": 3}',
    "[" * 100_000 + "]" * 100_000,
    '{"a":' * 5000 + "1" + "}" * 5000,
    "x" * 70_000,
]


@pytest.mark.parametrize("text", MALFORMED)
async def test_malformed_input_is_counted_and_dropped_never_raised(text):
    metrics = Metrics()
    session, _, sink, _ = make_session(metrics=metrics)
    await session.handle_message(text)
    assert sink.audio == [] and sink.dtmf == [] and not session.closed
    dropped = sum(
        v for k, v in session.stats.items() if k in {"malformed", "bad_audio", "bad_dtmf", "too_large", "bad_format"}
    )
    ignored = session.stats["ignored_kind"]
    assert dropped + ignored >= 1
    if dropped:
        total = sum(metrics.counter(PROVIDER_ERRORS, provider="azure", stage="media", kind=k) for k in session.stats)
        assert total >= 1


async def test_a_non_string_message_and_oversized_frames_are_dropped():
    session, _, sink, _ = make_session(max_frame_bytes=1000)
    await session.handle_message(None)  # type: ignore[arg-type]
    await session.handle_message(json.dumps(audio_msg(bytes(1002))))
    await session.handle_message(json.dumps(audio_msg(bytes(1000))))
    assert [len(p) for _, p, _ in sink.audio] == [1000] and session.stats["too_large"] + session.stats["bad_audio"] == 2


async def test_garbage_fuzz_never_raises_and_never_forwards_anything_unexpected():
    rng = random.Random(1234)
    session, _, sink, _ = make_session(max_invalid_frames=10**9)
    alphabet = '{}[]",:\\ntrueflsAudioDataKindaPCM0123456789=+/\u00e9\u0000'
    for _ in range(400):
        await session.handle_message("".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 80))))
        await session.handle_message(
            json.dumps(
                {
                    "kind": rng.choice(["AudioData", "DtmfData", "AudioMetadata", "x"]),
                    "audioData": rng.choice([None, 1, "s", {}, {"data": rng.choice(["AAAA", "AA==", 5, "QUJD"])}]),
                }
            )
        )
    assert all(len(p) % 2 == 0 for _, p, _ in sink.audio)


async def test_a_failing_sink_is_logged_but_does_not_kill_the_session_or_count_as_abuse(caplog):
    caplog.set_level(logging.WARNING)
    session, _, sink, _ = make_session(max_invalid_frames=1)
    sink.audio_error = RuntimeError(f"db exploded for {CALLER}")
    await session.handle_message(json.dumps(audio_msg(pcm())))
    assert session.stats["handler_error"] == 1 and not session.closed
    assert CALLER not in caplog.text and "RuntimeError" in str(caplog.records[0].__dict__)
    sink.audio_error = None
    await session.handle_message(json.dumps(audio_msg(pcm())))
    assert len(sink.audio) == 1


async def test_too_many_invalid_frames_end_the_session():
    session, ws, _, _ = make_session(max_invalid_frames=3)
    ws.feed("garbage", "garbage", "garbage", meta_msg())
    await asyncio.wait_for(session.run(), 1)
    assert session.closed and session.stats["malformed"] == 3 and session.stats["metadata"] == 0


async def test_run_forwards_frames_until_the_socket_closes():
    session, ws, sink, _ = make_session()
    ws.feed(meta_msg(), audio_msg(pcm(1)), {"kind": "DtmfData", "dtmfData": {"data": "5"}}, audio_msg(pcm(2)))
    ws.disconnect()
    await asyncio.wait_for(session.run(), 1)
    assert [p for _, p, _ in sink.audio] == [pcm(1), pcm(2)] and sink.dtmf == [(CALL, "5")] and session.closed


async def test_any_receive_failure_ends_the_loop_quietly_but_cancellation_propagates():
    session, ws, _, _ = make_session()
    ws.incoming.put_nowait(RuntimeError("starlette disconnect"))
    await asyncio.wait_for(session.run(), 1)
    assert session.closed

    session, ws, _, _ = make_session()
    task = asyncio.create_task(session.run())
    await settle()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.closed


# ===================================================================================== media: outbound
def b64_of_frame(text: str, casing: str) -> bytes:
    frame = json.loads(text)
    key = "AudioData" if casing == "pascal" else "audioData"
    data = "Data" if casing == "pascal" else "data"
    return base64.b64decode(frame[key][data])


async def test_audio_frames_use_the_documented_pascal_case_wire_format():
    session, ws, _, _clock = make_session()
    await session.send_audio(pcm(7, frames=2))
    assert (
        ws.sent
        == [
            '{"Kind":"AudioData","AudioData":{"Data":"' + b64(pcm(7)) + '"},"StopAudio":null}',
        ]
        * 2
    )
    assert all(len(b64_of_frame(t, "pascal")) == FRAME_16K for t in ws.sent)


async def test_camel_case_is_available_because_the_docs_conflict():
    session, ws, _, _ = make_session(casing="camel")
    await session.send_audio(pcm(7))
    assert ws.sent == ['{"kind":"AudioData","audioData":{"data":"' + b64(pcm(7)) + '"},"stopAudio":null}']
    await session.stop_audio()
    assert ws.sent[-1] == '{"kind":"StopAudio","audioData":null,"stopAudio":{}}'


async def test_barge_in_sends_the_documented_stop_audio_frame():
    session, ws, _, _ = make_session()
    await session.stop_audio()
    assert ws.sent == ['{"Kind":"StopAudio","AudioData":null,"StopAudio":{}}']


def test_an_unknown_casing_is_refused():
    with pytest.raises(ValueError, match="casing"):
        AcsMediaSession(CALL, FakeWebSocket(), FakeSink(), casing="snake")  # type: ignore[arg-type]


@pytest.mark.parametrize(("rate", "frame"), [(8000, 320), (16000, 640), (24000, 960)])
async def test_frames_are_whole_20ms_pcm16_frames_and_the_tail_is_padded_with_silence(rate, frame):
    session, ws, _, _ = make_session()
    await session.handle_message(json.dumps(meta_msg(rate)))
    payload = bytes([9]) * (frame * 2 + 37)
    await session.send_audio(payload)
    chunks = [b64_of_frame(t, "pascal") for t in ws.sent]
    assert [len(c) for c in chunks] == [frame, frame, frame]
    assert b"".join(chunks) == payload + bytes(frame - 37)


async def test_frames_are_paced_in_real_time_with_a_small_head_start():
    session, ws, _, clock = make_session()
    sender = asyncio.create_task(session.send_audio(pcm(1, frames=25)))
    await drive(clock, 0.6)
    await sender
    assert len(ws.sent) == 25
    expected = [0.0] * 5 + [0.02 * k for k in range(1, 21)]
    assert ws.sent_at == pytest.approx(expected, abs=1e-9)
    assert ws.sent_at[-1] < 25 * 0.02  # never later than the audio itself would play


async def test_after_a_gap_in_the_source_pacing_restarts_instead_of_bursting_to_catch_up():
    session, ws, _, clock = make_session()
    gate = asyncio.Event()

    async def source():
        yield pcm(1, frames=10)
        await gate.wait()
        yield pcm(2, frames=10)

    sender = asyncio.create_task(session.send_audio_stream(source()))
    await drive(clock, 0.3)
    assert len(ws.sent) == 10
    await clock.advance(1.0)  # a long stall in the TTS stream
    gate.set()
    await settle()
    resumed_at = clock.monotonic()
    await drive(clock, 0.4)
    await sender
    second = ws.sent_at[10:]
    assert len(second) == 10 and second[:5] == pytest.approx([resumed_at] * 5, abs=0.021)
    assert second[5] > second[4]  # the rest is paced again, not dumped at once


async def test_a_stop_during_playback_aborts_the_send_and_clears_the_acs_queue():
    session, ws, _, clock = make_session()
    sender = asyncio.create_task(session.send_audio(pcm(1, frames=50)))
    await drive(clock, 0.2)
    sent_before = len(ws.sent)
    assert 5 < sent_before < 50
    await session.stop_audio()
    await drive(clock, 1.5)
    await asyncio.wait_for(sender, 1)
    assert ws.frames[-1]["Kind"] == "StopAudio"
    assert len(ws.sent) == sent_before + 1  # the stop frame, and no audio after it


async def test_the_audio_source_is_closed_when_sending_is_interrupted():
    session, _ws, _, clock = make_session()
    closed = []

    async def source():
        try:
            for _ in range(100):
                yield pcm(1)
        finally:
            closed.append(True)

    sender = asyncio.create_task(session.send_audio_stream(source()))
    await drive(clock, 0.1)
    await session.stop_audio()
    await drive(clock, 0.1)
    await asyncio.wait_for(sender, 1)
    assert closed == [True]


async def test_a_dead_socket_raises_a_sanitised_error_and_closes_the_session():
    session, ws, _, _ = make_session()
    ws.fail_send = True
    with pytest.raises(ProviderError, match="media stream closed") as err:
        await session.send_audio(pcm())
    assert session.closed and "websocket" not in str(err.value).lower() and not err.value.retryable
    await session.stop_audio()  # closed: nothing is attempted, nothing raises
    assert ws.sent == []


async def test_sending_serialises_playbacks_so_frames_never_interleave():
    session, ws, _, clock = make_session()
    first = asyncio.create_task(session.send_audio(pcm(1, frames=8)))
    second = asyncio.create_task(session.send_audio(pcm(2, frames=8)))
    await drive(clock, 0.6)
    await asyncio.gather(first, second)
    values = [b64_of_frame(t, "pascal")[0] for t in ws.sent]
    assert values == [1] * 8 + [2] * 8


async def test_a_closed_session_sends_nothing():
    session, ws, _, _ = make_session()
    await session.close()
    await session.send_audio(pcm(1, frames=3))
    assert ws.sent == []


def test_the_fake_socket_satisfies_the_socket_protocol():
    assert isinstance(FakeWebSocket(), WebSocketLike)


# ====================================================================================== provider setup
def event(server_call_id: str = SERVER_CALL, event_id: str = "evt-1", **data) -> EventGridEvent:
    payload = {
        "to": {"kind": "phoneNumber", "rawId": f"4:{CALLED}", "phoneNumber": {"value": CALLED}},
        "from": {"kind": "phoneNumber", "rawId": f"4:{CALLER}", "phoneNumber": {"value": CALLER}},
        "serverCallId": server_call_id,
        "callerDisplayName": "Rahul",
        "incomingCallContext": CONTEXT,
        "correlationId": "corr-1",
    }
    payload.update(data)
    return EventGridEvent.model_validate(
        {
            "id": event_id,
            "topic": "/subscriptions/s",
            "subject": "/caller/x",
            "eventType": "Microsoft.Communication.IncomingCall",
            "eventTime": "2026-11-17T10:00:00Z",
            "dataVersion": "1.0",
            "data": payload,
        }
    )


def ref(call_id: str = CALL) -> ProviderCallRef:
    return ProviderCallRef(call_id=call_id, provider_call_id=SERVER_CALL)


def plan(text: str = "Hello, you have reached the assistant.", **kw) -> SpeechPlan:
    values = {"text": text, "locale": "en-IN", "voice_id": "en-IN-NeerjaNeural", "est_duration_ms": 400}
    values.update(kw)
    return SpeechPlan(**values)


def make(make_settings, *, tts=None, client=None, clock=None, sink=None, http=None, **kw):
    ctor = {k: kw.pop(k) for k in ("media_attach_timeout_s", "media_casing") if k in kw}
    clock = clock or VirtualClock()
    tts = tts or FakeTts()
    client = client or FakeAcsClient()
    sink = sink or FakeSink()
    provider = AzureAcsTelephonyProvider(make_settings(**kw), tts=tts, client=client, clock=clock, http=http, **ctor)
    provider.bind(sink)
    return provider, client, sink, tts, clock


async def answered_call(make_settings, **kw):
    """A provider with one answered call (like the service does it) and nothing attached yet."""
    provider, client, sink, tts, clock = make(make_settings, **kw)
    await provider.handle_incoming(event())
    return provider, client, sink, tts, clock


async def attach(provider, clock=None):
    ws = FakeWebSocket(clock)
    task = asyncio.create_task(provider.attach_media(CALL, ws))
    await settle()
    return ws, task


# ============================================================================================ capabilities
async def test_capabilities_are_honest_and_say_what_is_not_verified(make_settings):
    provider, *_ = make(make_settings)
    caps = provider.capabilities
    assert isinstance(provider, TelephonyProvider)
    assert (provider.name, provider.kind) == ("azure", ProviderKind.AZURE)
    assert caps.can_answer and caps.can_play_audio and caps.can_stop_playback and caps.can_transfer and caps.can_hangup
    assert caps.receives_caller_audio and caps.dtmf and caps.simulated is False and caps.live_calls_supported is True
    assert caps.two_way_audio is False  # a per-call fact: see capabilities_for_call
    assert "UNVERIFIED" in caps.note and "+91" in caps.note and "docs/research/acs-android-verification.md" in caps.note
    per_call = caps.call_capabilities()
    assert per_call.simulated is False and per_call.two_way_audio is False and per_call.audio_note is not None
    assert per_call.can_take_over and per_call.takeover_note is None


@pytest.mark.parametrize("missing", ["acs_connection_string", "acs_callback_base_url", "acs_resource_id"])
def test_live_calls_need_the_connection_string_the_callback_url_and_the_resource_id(make_settings, missing):
    assert make(make_settings)[0].capabilities.live_calls_supported is True
    provider, *_ = make(make_settings, **{missing: None})
    assert provider.capabilities.live_calls_supported is False and provider.live_configured is False


def test_a_simulated_tts_means_no_audio_can_be_played(make_settings):
    provider, *_ = make(make_settings, tts=FakeTts(simulated=True))
    assert provider.capabilities.can_play_audio is False


async def test_two_way_audio_is_per_call_and_follows_the_media_socket(make_settings):
    provider, _client, _sink, _tts, clock = await answered_call(make_settings)
    assert provider.capabilities_for_call(CALL).two_way_audio is False
    assert provider.capabilities_for_call("unknown-call").two_way_audio is False
    ws, task = await attach(provider, clock)
    per_call = provider.capabilities_for_call(CALL)
    assert per_call.two_way_audio is True and per_call.call_capabilities().audio_note is None
    assert provider.capabilities.two_way_audio is False  # the shared object is never mutated
    ws.disconnect()
    await asyncio.wait_for(task, 1)
    assert provider.capabilities_for_call(CALL).two_way_audio is False


async def test_status_reports_health_without_any_network_call(make_settings):
    provider, client, *_ = make(make_settings)
    status = await provider.status()
    assert (status.provider, status.kind, status.healthy, status.simulated) == (
        "azure",
        ProviderKind.AZURE,
        True,
        False,
    )
    assert status.extra["live_calls_supported"] == "true" and status.extra["circuit"] == "closed"
    assert (status.extra["active_calls"], status.extra["media_sessions"]) == ("0", "0")
    assert client.answers == []

    unconfigured, *_ = make(make_settings, acs_resource_id=None)
    assert (await unconfigured.status()).healthy is False
    silent, *_ = make(make_settings, tts=FakeTts(simulated=True))
    degraded = await silent.status()
    assert degraded.healthy is False and "silent" in degraded.detail


async def test_status_goes_unhealthy_while_the_circuit_is_open(make_settings):
    provider, client, sink, *_ = make(make_settings, clock=FastClock(), provider_max_retries=0)
    for _ in range(5):
        client.answer_errors.append(ProviderError("azure", "answer", "service unavailable (HTTP 503)", retryable=True))
    for i in range(5):
        sink.call_id = f"call_fail{i:04d}"
        await provider.handle_incoming(event(server_call_id=f"s{i}"))
    assert provider._breaker.state is BreakerState.OPEN
    assert (await provider.status()).healthy is False


def test_build_acs_provider_matches_the_factorys_call_and_creates_no_client_yet(make_settings):
    http = httpx.AsyncClient()
    provider = build_acs_provider(make_settings(), tts=FakeTts(), http=http, clock=VirtualClock(), metrics=Metrics())
    assert isinstance(provider, AzureAcsTelephonyProvider) and provider._client is None
    assert build_acs_provider(make_settings(), tts=FakeTts()).capabilities.live_calls_supported is True


# ====================================================================================== incoming calls
async def test_the_incoming_flow_matches_how_the_call_service_drives_the_provider(make_settings):
    provider, client, sink, _tts, clock = make(make_settings)

    async def service(call):  # the CallService answers and speaks from INSIDE incoming_call(), before returning
        assert call.provider == "azure" and (call.caller_number, call.called_number) == (CALLER, CALLED)
        await provider.answer(ref())
        await provider.play(ref(), plan())

    sink.on_incoming = service
    assert await provider.handle_incoming(event()) == CALL
    assert client.answers == [
        (
            CONTEXT,
            "https://sparta.example.com/api/v1/webhooks/acs/callbacks/call_test0001",
            "wss://sparta.example.com/api/v1/media/acs/call_test0001",
        )
    ]
    ws, task = await attach(provider, clock)
    await drive(clock, 0.5)
    assert sink.finished and sink.finished[0][0] == CALL and len(ws.sent) == 10
    assert sink.errors == [] and sink.hangups == []
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_without_a_service_answer_handle_incoming_answers_the_call_itself(make_settings):
    provider, client, _sink, *_ = make(make_settings)
    assert await provider.handle_incoming(event()) == CALL
    assert len(client.answers) == 1 and client.answers[0][0] == CONTEXT


async def test_the_answer_context_is_single_use_and_is_not_kept(make_settings):
    provider, _client, *_ = await answered_call(make_settings)
    state = provider._calls[CALL]
    assert state.context is None and state.connection_id == "conn-1" and provider._pending == {}


async def test_duplicate_and_concurrent_deliveries_create_one_call_and_one_answer(make_settings):
    provider, client, sink, *_ = make(make_settings)
    client.answer_gate = asyncio.Event()
    deliveries = [asyncio.create_task(provider.handle_incoming(event(event_id=f"evt-{i}"))) for i in range(3)]
    await settle()
    client.answer_gate.set()
    assert await asyncio.gather(*deliveries) == [CALL] * 3
    assert await provider.handle_incoming(event(event_id="evt-late")) == CALL  # an Event Grid redelivery
    assert len(sink.incoming) == 1 and len(client.answers) == 1


async def test_a_different_call_is_a_different_acceptance(make_settings):
    provider, client, sink, *_ = make(make_settings)
    await provider.handle_incoming(event())
    sink.call_id = "call_test0002"
    assert (
        await provider.handle_incoming(event(server_call_id="other-server-call", event_id="evt-2")) == "call_test0002"
    )
    assert len(sink.incoming) == 2 and len(client.answers) == 2


async def test_a_failed_acceptance_can_be_retried_by_a_redelivery(make_settings):
    provider, client, sink, *_ = make(make_settings)
    sink.incoming_error = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await provider.handle_incoming(event())
    sink.incoming_error = None
    assert await provider.handle_incoming(event()) == CALL and len(client.answers) == 1


async def test_a_call_the_service_already_ended_is_never_answered(make_settings):
    provider, client, sink, *_ = make(make_settings)

    async def block(call):  # e.g. a blocked caller: the service finishes the call inside incoming_call()
        await provider.hangup(ref(), "blocked")

    sink.on_incoming = block
    assert await provider.handle_incoming(event()) == CALL
    assert client.answers == [] and client.hangups == []
    with pytest.raises(ProviderRejected, match="already ended"):
        await provider.answer(ref())


async def test_an_answer_that_fails_is_retried_then_reported_and_the_call_is_closed(make_settings):
    clock = FastClock()
    provider, client, sink, *_ = make(make_settings, clock=clock)
    client.answer_errors = [ProviderError("azure", "answer", "service unavailable (HTTP 503)", retryable=True)] * 2
    assert await provider.handle_incoming(event()) == CALL  # nothing raised: Event Grid must not redeliver
    assert len(client.answers) == 2 and clock.sleeps == [0.2]
    assert sink.errors == [(CALL, "answer", "service unavailable (HTTP 503)")]
    assert sink.hangups == [(CALL, "answer_failed")] and CALL not in provider._calls


async def test_a_rejected_answer_is_not_retried(make_settings):
    provider, client, sink, *_ = make(make_settings, clock=FastClock())
    client.answer_errors = [ProviderRejected("azure", "answer", "request rejected (HTTP 400)", status=400)]
    await provider.handle_incoming(event())
    assert len(client.answers) == 1 and sink.errors[0][1:] == ("answer", "request rejected (HTTP 400)")


async def test_answer_needs_a_context_and_is_idempotent(make_settings):
    provider, client, _sink, *_ = make(make_settings)
    with pytest.raises(ProviderRejected, match="no incoming call context"):
        await provider.answer(ProviderCallRef(call_id=CALL, provider_call_id="never-seen"))
    explicit = ProviderCallRef(call_id=CALL, provider_call_id=SERVER_CALL, provider_context="explicit-context")
    await provider.answer(explicit)
    await provider.answer(explicit)
    assert [a[0] for a in client.answers] == ["explicit-context"]


async def test_concurrent_answers_make_one_acs_call(make_settings):
    provider, client, *_ = make(make_settings)
    client.answer_gate = asyncio.Event()
    explicit = ProviderCallRef(call_id=CALL, provider_call_id=SERVER_CALL, provider_context=CONTEXT)
    tasks = [asyncio.create_task(provider.answer(explicit)) for _ in range(4)]
    await settle()
    client.answer_gate.set()
    await asyncio.gather(*tasks)
    assert len(client.answers) == 1


@pytest.mark.parametrize(
    ("base", "callback", "ws"),
    [
        (
            "https://example.com/",
            "https://example.com/api/v1/webhooks/acs/callbacks/call_test0001",
            "wss://example.com/api/v1/media/acs/call_test0001",
        ),
        (
            "https://example.com:8443/edge",
            "https://example.com:8443/edge/api/v1/webhooks/acs/callbacks/call_test0001",
            "wss://example.com:8443/edge/api/v1/media/acs/call_test0001",
        ),
    ],
)
async def test_callback_and_media_urls_are_derived_from_the_configured_base(make_settings, base, callback, ws):
    provider, client, *_ = make(make_settings, acs_callback_base_url=base)
    await provider.handle_incoming(event())
    assert client.answers[0][1:] == (callback, ws)


@pytest.mark.parametrize(
    "base", ["http://plain.example", "ftp://x", "https://u:p@x.example", "not a url", "https://x.example/?q=1"]
)
async def test_a_bad_callback_base_url_is_an_answer_failure_never_a_plain_http_callback(make_settings, base):
    provider, client, sink, *_ = make(make_settings, acs_callback_base_url=base)
    await provider.handle_incoming(event())
    assert client.answers == [] and sink.errors and "https" in sink.errors[0][2]


async def test_a_call_id_that_could_alter_the_urls_is_refused(make_settings):
    provider, client, sink, *_ = make(make_settings)
    sink.call_id = "call/../../evil?x=1"
    await provider.handle_incoming(event())
    assert client.answers == [] and sink.errors


async def test_a_malformed_event_is_rejected_before_anything_happens(make_settings):
    provider, client, sink, *_ = make(make_settings)
    with pytest.raises(Exception, match="incomplete"):
        await provider.handle_incoming(event(incomingCallContext=None))
    assert sink.incoming == [] and client.answers == []


async def test_events_need_a_bound_sink(make_settings):
    provider = AzureAcsTelephonyProvider(make_settings(), tts=FakeTts(), client=FakeAcsClient(), clock=VirtualClock())
    with pytest.raises(ProviderUnavailable, match="not bound"):
        await provider.handle_incoming(event())
    with pytest.raises(ProviderUnavailable, match="not bound"):
        await provider.attach_media(CALL, FakeWebSocket())


async def test_nothing_in_the_incoming_flow_logs_numbers_contexts_or_connection_strings(make_settings, caplog):
    caplog.set_level(logging.DEBUG)
    provider, client, sink, *_ = make(make_settings, clock=FastClock())
    client.answer_errors = [RuntimeError(f"boom {CALLER} {CONTEXT}")] * 2
    await provider.handle_incoming(event())
    text = caplog.text + " ".join(m for _, _, m in sink.errors)
    assert CALLER not in text and CALLED not in text and CONTEXT not in text and "accesskey" not in text


# ================================================================================================ playback
async def test_speech_is_synthesised_as_pcm16_and_sent_as_paced_frames_then_reported_finished(make_settings):
    tts = FakeTts(frames=25)
    provider, _client, sink, _, clock = await answered_call(make_settings, tts=tts)
    ws, task = await attach(provider, clock)
    playback = await provider.play(ref(), plan(rate=1.1, style="cheerful"))
    assert playback.simulated is False and playback.call_id == CALL and playback.duration_ms == 400
    assert playback.playback_id.startswith("pb_") and playback.playback_id.endswith("_1")
    await drive(clock, 0.7)
    request = tts.requests[0]
    assert (request.output_format, request.trace_id) == ("pcm16_16k", playback.playback_id)
    assert (request.text, request.locale, request.voice_id, request.rate, request.style) == (
        "Hello, you have reached the assistant.",
        "en-IN",
        "en-IN-NeerjaNeural",
        1.1,
        "cheerful",
    )
    assert len(ws.sent) == 25 and all(len(b64_of_frame(t, "pascal")) == FRAME_16K for t in ws.sent)
    assert ws.sent_at[0] == 0.0 and ws.sent_at[-1] == pytest.approx(0.4)
    assert sink.finished == [(CALL, playback.playback_id)] and tts.closed_streams == 1
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_the_duration_falls_back_to_an_estimate_and_ids_are_unique(make_settings):
    provider, *_ = await answered_call(make_settings)
    first = await provider.play(ref(), plan(est_duration_ms=0))
    second = await provider.play(ref(), plan())
    assert first.duration_ms > 1 and first.playback_id != second.playback_id


async def test_the_negotiated_sample_rate_selects_the_tts_output_format(make_settings):
    tts = FakeTts(frames=3)
    provider, _client, _sink, _, clock = await answered_call(make_settings, tts=tts)
    ws, task = await attach(provider, clock)
    ws.feed(meta_msg(24000))
    await settle()
    await provider.play(ref(), plan())
    await drive(clock, 0.2)
    assert tts.requests[0].output_format == "pcm16_24k" and all(len(b64_of_frame(t, "pascal")) == 960 for t in ws.sent)
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_the_configured_wire_casing_is_used_for_the_session(make_settings):
    provider, _client, _sink, _tts, clock = await answered_call(make_settings, media_casing="camel")
    ws, task = await attach(provider, clock)
    await provider.play(ref(), plan())
    await drive(clock, 0.4)
    assert ws.frames and all(set(f) == {"kind", "audioData", "stopAudio"} for f in ws.frames)
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_playback_waits_for_the_media_socket_to_attach(make_settings):
    provider, _client, sink, tts, clock = await answered_call(make_settings)
    await provider.play(ref(), plan())
    await drive(clock, 0.2)
    assert tts.requests == [] and sink.finished == []  # nothing happens until ACS connects its media socket
    ws, task = await attach(provider, clock)
    await drive(clock, 0.5)
    assert len(sink.finished) == 1 and len(ws.sent) == 10
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_two_lines_are_spoken_in_order_never_on_top_of_each_other(make_settings):
    tts = FakeTts(frames=6)
    provider, _client, sink, _, clock = await answered_call(make_settings, tts=tts)
    ws, task = await attach(provider, clock)
    tts.frame_value = 1
    first = await provider.play(ref(), plan("first line"))
    second = await provider.play(ref(), plan("second line"))
    await drive(clock, 0.5)
    assert [r.text for r in tts.requests] == ["first line", "second line"]
    assert sink.finished == [(CALL, first.playback_id), (CALL, second.playback_id)] and len(ws.sent) == 12
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_no_media_socket_in_time_is_a_provider_error_not_a_hang(make_settings):
    provider, _client, sink, _tts, _clock = await answered_call(make_settings, media_attach_timeout_s=0.05)
    await provider.play(ref(), plan())
    await asyncio.sleep(0.15)
    assert sink.errors == [(CALL, "play", "the media stream is not connected")] and sink.finished == []
    assert provider._calls[CALL].playbacks == {}


async def test_a_tts_failure_is_reported_sanitised_and_no_finish_is_claimed(make_settings):
    tts = FakeTts()
    tts.error = ProviderError("azure-speech", "tts", "service unavailable (HTTP 503)", retryable=True, status=503)
    provider, _client, sink, _, clock = await answered_call(make_settings, tts=tts)
    ws, task = await attach(provider, clock)
    await provider.play(ref(), plan())
    await drive(clock, 0.2)
    assert sink.errors == [(CALL, "play", "service unavailable (HTTP 503)")] and sink.finished == [] and ws.sent == []
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_an_unexpected_playback_crash_is_reported_without_details(make_settings):
    tts = FakeTts()
    tts.error = RuntimeError(f"secret detail {CALLER}")  # type: ignore[assignment]
    provider, _client, sink, _, clock = await answered_call(make_settings, tts=tts)
    ws, task = await attach(provider, clock)
    await provider.play(ref(), plan())
    await drive(clock, 0.2)
    assert sink.errors == [(CALL, "play", "playback failed")] and CALLER not in str(sink.errors)
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_a_socket_that_dies_during_playback_is_reported(make_settings):
    provider, _client, sink, _tts, clock = await answered_call(make_settings, tts=FakeTts(frames=40))
    ws, task = await attach(provider, clock)
    await provider.play(ref(), plan())
    await drive(clock, 0.1)
    ws.fail_send = True
    await drive(clock, 0.2)
    assert sink.finished == [] and sink.errors and sink.errors[0][1] == "play"
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_a_socket_that_closes_during_playback_is_reported_not_finished(make_settings):
    provider, _client, sink, _tts, clock = await answered_call(make_settings, tts=FakeTts(frames=40))
    ws, task = await attach(provider, clock)
    await provider.play(ref(), plan())
    await drive(clock, 0.1)
    ws.disconnect()
    await drive(clock, 0.2)
    assert sink.finished == [] and sink.errors == [(CALL, "play", "the media stream closed during playback")]
    await asyncio.wait_for(task, 1)


async def test_play_needs_an_active_call_and_a_real_tts(make_settings):
    provider, *_ = make(make_settings)
    with pytest.raises(ProviderRejected, match="not active"):
        await provider.play(ref("never-answered"), plan())
    silent, *_ = make(make_settings, tts=FakeTts(simulated=True))
    await silent.handle_incoming(event())
    with pytest.raises(ProviderRejected, match="real text-to-speech"):
        await silent.play(ref(), plan())


# ================================================================================================ barge-in
async def test_barge_in_stops_audio_cancels_the_synthesis_and_never_reports_finished(make_settings):
    tts = FakeTts(frames=50, chunk_frames=5)
    provider, _client, sink, _, clock = await answered_call(make_settings, tts=tts)
    ws, task = await attach(provider, clock)
    playback = await provider.play(ref(), plan())
    await drive(clock, 0.2)
    sent_before = len(ws.sent)
    assert 5 <= sent_before < 50

    await provider.stop_playback(ref(), playback.playback_id)
    await drive(clock, 1.5)
    assert ws.frames[-1] == {"Kind": "StopAudio", "AudioData": None, "StopAudio": {}}
    assert len(ws.sent) == sent_before + 1  # exactly one StopAudio and no audio after it
    assert tts.stopped == [playback.playback_id] and tts.closed_streams == 1
    assert sink.finished == [] and sink.errors == [] and provider._calls[CALL].playbacks == {}
    await provider.stop_playback(ref(), playback.playback_id)  # idempotent
    assert ws.frames[-1]["Kind"] == "StopAudio"
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_stop_playback_clears_audio_already_queued_at_acs_even_when_nothing_is_running(make_settings):
    provider, _client, _sink, _tts, clock = await answered_call(make_settings)
    ws, task = await attach(provider, clock)
    await provider.stop_playback(ref(), "pb_already_finished")
    assert ws.frames == [{"Kind": "StopAudio", "AudioData": None, "StopAudio": {}}]
    await provider.stop_playback(ref("unknown-call"), "pb_x")  # an unknown call is a quiet no-op
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_a_barge_in_while_still_waiting_for_the_socket_cancels_the_queued_line(make_settings):
    provider, _client, sink, tts, clock = await answered_call(make_settings)
    playback = await provider.play(ref(), plan())
    await provider.stop_playback(ref(), playback.playback_id)
    ws, task = await attach(provider, clock)
    await drive(clock, 0.5)
    assert tts.requests == [] and sink.finished == [] and ws.sent == []
    ws.disconnect()
    await asyncio.wait_for(task, 1)


async def test_a_failed_stop_frame_does_not_raise_out_of_stop_playback(make_settings):
    provider, _client, _sink, _tts, clock = await answered_call(make_settings, tts=FakeTts(frames=50))
    ws, task = await attach(provider, clock)
    playback = await provider.play(ref(), plan())
    await drive(clock, 0.1)
    ws.fail_send = True
    await provider.stop_playback(ref(), playback.playback_id)  # must not raise
    ws.disconnect()
    await asyncio.wait_for(task, 1)


# ================================================================================================ hang up
async def test_hangup_ends_the_acs_call_for_everyone_and_is_idempotent(make_settings):
    provider, client, _sink, *_ = await answered_call(make_settings)
    await provider.hangup(ref(), "completed")
    await provider.hangup(ref(), "completed")
    assert client.hangups == [("conn-1", True)] and CALL not in provider._calls


async def test_hangup_stops_playback_and_closes_the_media_session(make_settings):
    provider, client, sink, tts, clock = await answered_call(make_settings, tts=FakeTts(frames=50))
    _ws, task = await attach(provider, clock)
    await provider.play(ref(), plan())
    await drive(clock, 0.1)
    await provider.hangup(ref(), "completed")
    await drive(clock, 0.5)
    assert sink.finished == [] and tts.closed_streams == 1
    await asyncio.wait_for(task, 1)  # the media loop was ended
    assert provider._calls == {} and client.hangups == [("conn-1", True)]


async def test_hangup_of_a_call_that_was_never_answered_makes_no_acs_call(make_settings):
    provider, client, _sink, *_ = make(make_settings)
    explicit = ProviderCallRef(call_id=CALL, provider_call_id=SERVER_CALL, provider_context=CONTEXT)
    provider._state_for(CALL, SERVER_CALL, CONTEXT)
    await provider.hangup(explicit, "completed")
    assert client.hangups == [] and client.answers == []
    await provider.hangup(ref("never-heard-of"), "completed")  # unknown: no-op


@pytest.mark.parametrize("status", [404, 409])
async def test_a_call_that_is_already_gone_is_not_an_error(make_settings, status):
    provider, client, *_ = await answered_call(make_settings, clock=FastClock())
    client.hangup_errors = [ProviderError("azure", "hangup", "gone", status=status)]
    await provider.hangup(ref(), "completed")
    assert len(client.hangups) == 1


async def test_a_real_hangup_failure_is_raised_after_local_cleanup(make_settings):
    provider, client, *_ = await answered_call(make_settings, clock=FastClock())
    client.hangup_errors = [ProviderRejected("azure", "hangup", "authentication failed", status=401)]
    with pytest.raises(ProviderRejected):
        await provider.hangup(ref(), "completed")
    assert CALL not in provider._calls and len(client.hangups) == 1


# ================================================================================================ transfer
async def test_a_transfer_is_requested_not_claimed_and_never_labelled_simulated(make_settings):
    provider, client, _sink, *_ = await answered_call(make_settings)
    result = await provider.transfer(ref(), CALLED)
    assert result.accepted is True and result.simulated is False
    assert client.transfers == [("conn-1", CALLED)] and "asynchronously" in result.detail
    assert CALLED not in result.detail and provider._calls[CALL].transfer == "requested"


@pytest.mark.parametrize(
    "destination",
    [None, "", "9876543210", "+0123456789", "+12", "+1234567890123456", "abc", "+91 98765 43210", "tel:+14255550123"],
)
async def test_only_e164_destinations_are_accepted_and_nothing_is_sent_otherwise(make_settings, destination):
    provider, client, *_ = await answered_call(make_settings)
    result = await provider.transfer(ref(), destination)
    assert (result.accepted, result.simulated) == (False, False) and "number" in result.detail
    assert client.transfers == []


async def test_a_transfer_needs_a_connected_call(make_settings):
    provider, client, *_ = make(make_settings)
    result = await provider.transfer(ref(), CALLED)
    assert result.accepted is False and "not connected" in result.detail and client.transfers == []


async def test_a_failed_transfer_request_is_a_sanitised_non_acceptance_and_is_not_retried(make_settings):
    provider, client, _sink, *_ = await answered_call(make_settings, clock=FastClock())
    client.transfer_errors = [ProviderError("azure", "transfer", "service unavailable (HTTP 503)", retryable=True)] * 2
    result = await provider.transfer(ref(), CALLED)
    assert result.accepted is False and "503" in result.detail and CALLED not in result.detail
    assert len(client.transfers) == 1  # transfers are not idempotent: never retried


async def test_an_accepted_transfer_ends_with_a_disconnect_reported_as_transferred(make_settings):
    provider, _client, sink, *_ = await answered_call(make_settings)
    await provider.transfer(ref(), CALLED)
    await provider.handle_callback_event(
        CALL, [{"id": "e1", "type": "Microsoft.Communication.CallTransferAccepted", "data": {}}]
    )
    await provider.handle_callback_event(
        CALL, [{"id": "e2", "type": "Microsoft.Communication.CallDisconnected", "data": {}}]
    )
    assert sink.hangups == [(CALL, "transferred")]


# ============================================================================================ media socket
async def test_attach_media_forwards_caller_audio_until_the_socket_closes(make_settings):
    provider, _client, sink, _tts, clock = await answered_call(make_settings)
    ws, task = await attach(provider, clock)
    ws.feed(meta_msg(), audio_msg(pcm(1)), {"kind": "DtmfData", "dtmfData": {"data": "7"}})
    await settle()
    assert sink.audio == [(CALL, pcm(1), 16000)] and sink.dtmf == [(CALL, "7")]
    ws.disconnect()
    await asyncio.wait_for(task, 1)
    assert provider._calls[CALL].session is None and not provider._calls[CALL].media_ready.is_set()


async def test_attach_media_for_an_unknown_or_ended_call_is_refused(make_settings):
    provider, *_ = await answered_call(make_settings)
    with pytest.raises(ProviderRejected, match="unknown or ended"):
        await provider.attach_media("someone-elses-call", FakeWebSocket())
    await provider.hangup(ref(), "completed")
    with pytest.raises(ProviderRejected, match="unknown or ended"):
        await provider.attach_media(CALL, FakeWebSocket())


async def test_a_reconnect_replaces_the_previous_media_socket(make_settings):
    provider, _client, sink, _tts, clock = await answered_call(make_settings)
    old_ws, old_task = await attach(provider, clock)
    new_ws, new_task = await attach(provider, clock)
    await asyncio.wait_for(old_task, 1)  # the old attach_media ended without error
    new_ws.feed(audio_msg(pcm(4)))
    await settle()
    assert sink.audio == [(CALL, pcm(4), 16000)]
    await provider.play(ref(), plan())
    await drive(clock, 0.5)
    assert len(new_ws.sent) == 10 and old_ws.sent == []
    new_ws.disconnect()
    await asyncio.wait_for(new_task, 1)


async def test_cancelling_attach_media_cleans_up(make_settings):
    provider, _client, _sink, _tts, clock = await answered_call(make_settings)
    _ws, task = await attach(provider, clock)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = provider._calls[CALL]
    assert state.session is None and not state.media_ready.is_set()


# ================================================================================================ callbacks
def cb(name: str, event_id: str | None = "e-1", *, connection: str | None = "conn-1", **data) -> dict:
    payload = dict(data)
    if connection is not None:
        payload["callConnectionId"] = connection
    event = {"type": f"Microsoft.Communication.{name}", "data": payload, "specversion": "1.0"}
    if event_id is not None:
        event["id"] = event_id
    return event


async def test_call_disconnected_ends_the_call_once_even_if_delivered_twice(make_settings):
    provider, client, sink, *_ = await answered_call(make_settings)
    await provider.handle_callback_event(CALL, [cb("CallConnected"), cb("CallDisconnected", "e-2")])
    await provider.handle_callback_event(CALL, [cb("CallDisconnected", "e-2")])  # same event id
    await provider.handle_callback_event(CALL, cb("CallDisconnected", "e-3"))  # new id, but the call is gone
    await provider.handle_callback_event(CALL, cb("CallDisconnected", None))  # no id at all
    assert sink.hangups == [(CALL, "disconnected")] and CALL not in provider._calls
    await provider.hangup(ref(), "disconnected")  # the service's own end-of-call hangup is a no-op
    assert client.hangups == []  # ...and does not call ACS for a call ACS already ended


async def test_events_without_ids_are_still_idempotent_where_it_matters(make_settings):
    provider, _client, sink, *_ = await answered_call(make_settings)
    for _ in range(3):
        await provider.handle_callback_event(CALL, cb("PlayFailed", None, code=1))
    assert len(sink.errors) == 3  # nothing to dedupe on: each is reported, but a disconnect only happens once
    for _ in range(3):
        await provider.handle_callback_event(CALL, cb("CallDisconnected", None))
    assert sink.hangups == [(CALL, "disconnected")]


@pytest.mark.parametrize(
    ("name", "stage", "message"),
    [
        ("PlayFailed", "play", "Azure reported a media playback failure"),
        ("MediaStreamingFailed", "media", "Azure reported a media streaming failure"),
        ("CallTransferFailed", "transfer", "Azure reported that the transfer failed"),
    ],
)
async def test_failure_events_become_sanitised_provider_errors_with_only_result_codes(
    make_settings, name, stage, message
):
    provider, _client, sink, *_ = await answered_call(make_settings)
    info = {"resultInformation": {"code": 400, "subCode": 8501, "message": f"leaky {CALLER} {CONTEXT}"}}
    await provider.handle_callback_event(CALL, cb(name, **info))
    assert sink.errors == [(CALL, stage, f"{message} (code 400.8501)")]
    assert CALLER not in str(sink.errors) and CONTEXT not in str(sink.errors)
    assert CALL in provider._calls  # a failure of one operation does not end the call by itself


async def test_an_answer_failed_callback_reports_and_ends_the_call(make_settings):
    provider, _client, sink, *_ = await answered_call(make_settings)
    await provider.handle_callback_event(CALL, cb("AnswerFailed", resultInformation={"code": 500}))
    assert sink.errors == [(CALL, "answer", "Azure could not answer the call (code 500)")]
    assert sink.hangups == [(CALL, "answer_failed")] and CALL not in provider._calls


async def test_connected_and_informational_events_change_nothing_visible(make_settings):
    provider, _client, sink, *_ = await answered_call(make_settings)
    for name in ("CallConnected", "ParticipantsUpdated", "MediaStreamingStarted", "PlayCompleted", "SomethingElse"):
        await provider.handle_callback_event(CALL, cb(name, f"id-{name}"))
    assert provider._calls[CALL].connected is True and sink.errors == [] and sink.hangups == []


async def test_a_transfer_failure_leaves_the_call_open(make_settings):
    provider, _client, sink, *_ = await answered_call(make_settings)
    await provider.transfer(ref(), CALLED)
    await provider.handle_callback_event(CALL, cb("CallTransferFailed", "t-1"))
    assert provider._calls[CALL].transfer == "failed" and sink.hangups == []


async def test_events_for_other_calls_connections_or_garbage_are_ignored(make_settings):
    provider, _client, sink, *_ = await answered_call(make_settings)
    await provider.handle_callback_event("another-call", cb("CallDisconnected"))
    await provider.handle_callback_event(CALL, cb("CallDisconnected", connection="some-other-connection"))
    for junk in (None, 5, "x", [], [1, "a", None], {"type": 5}, {"id": 5, "type": None, "data": []}, {"data": "x"}):
        await provider.handle_callback_event(CALL, junk)
    assert sink.hangups == [] and CALL in provider._calls


async def test_a_callback_can_supply_the_connection_id_when_it_beats_the_answer_response(make_settings):
    provider, _client, sink, *_ = make(make_settings)
    state = provider._state_for(CALL, SERVER_CALL, CONTEXT)
    await provider.handle_callback_event(CALL, cb("CallConnected", connection="early-conn"))
    assert state.connection_id == "early-conn"
    await provider.handle_callback_event(CALL, cb("CallDisconnected", "d-1", connection="other"))
    assert sink.hangups == []  # an event for a different connection id


async def test_a_batch_is_capped(make_settings):
    provider, _client, sink, *_ = await answered_call(make_settings)
    await provider.handle_callback_event(CALL, [cb("PlayFailed", f"id-{i}") for i in range(500)])
    assert len(sink.errors) == 50


# ================================================================================================ lifecycle
async def test_aclose_stops_everything_and_closes_the_client(make_settings):
    provider, client, sink, tts, clock = await answered_call(make_settings, tts=FakeTts(frames=50))
    _ws, task = await attach(provider, clock)
    await provider.play(ref(), plan())
    await drive(clock, 0.1)
    await provider.aclose()
    await asyncio.wait_for(task, 1)
    assert provider._calls == {} and client.closed is True and tts.closed_streams == 1 and sink.finished == []


# ================================================================================================ verifiers
async def test_verifier_helpers_need_the_shared_http_client(make_settings):
    provider, *_ = make(make_settings)
    for build in (provider.callback_verifier, provider.media_verifier, provider.event_grid_verifier):
        with pytest.raises(ConfigurationError, match="HTTP client"):
            build()


async def test_verifier_helpers_are_cached_and_use_the_documented_acs_settings(make_settings, key):
    http = MockHttp(jwks_response(key))
    provider, *_ = make(make_settings, http=http.client)
    assert provider.callback_verifier() is provider.callback_verifier()
    assert provider.callback_verifier() is not provider.media_verifier()
    token = key.token(claims("https://acscallautomation.communication.azure.com", ACS_RESOURCE))
    assert (await provider.callback_verifier().verify(token))["aud"] == ACS_RESOURCE
    day_long = key.token(
        claims(
            "https://acscallautomation.communication.azure.com",
            ACS_RESOURCE,
            exp=int(__import__("time").time()) + 86_400,
        )
    )
    assert (await provider.media_verifier().verify(day_long))["aud"] == ACS_RESOURCE
    assert ACS_MEDIA_MAX_LIFETIME_S > 86_400
    assert provider.event_grid_verifier() is provider.event_grid_verifier()


# ============================================================================================= SDK client
class FakeSdkConnection:
    def __init__(self, sdk) -> None:
        self.sdk = sdk

    def hang_up(self, is_for_everyone):
        self.sdk.calls.append(("hang_up", is_for_everyone))
        if self.sdk.error:
            raise self.sdk.error

    def transfer_call_to_participant(self, target_participant, **kw):
        self.sdk.calls.append(("transfer", target_participant, kw))
        if self.sdk.error:
            raise self.sdk.error


class FakeSdk:
    def __init__(self) -> None:
        self.calls: list = []
        self.error: BaseException | None = None
        self.closed = False
        self.connection_id: object = "conn-9"

    def answer_call(self, incoming_call_context, callback_url, **kw):
        self.calls.append(("answer", incoming_call_context, callback_url, kw))
        if self.error:
            raise self.error
        return SimpleNamespace(call_connection_id=self.connection_id)

    def get_call_connection(self, connection_id):
        self.calls.append(("connection", connection_id))
        return FakeSdkConnection(self)

    def close(self):
        self.closed = True


@pytest.fixture
def sdk(monkeypatch) -> FakeSdk:
    from azure.communication.callautomation import CallAutomationClient

    fake = FakeSdk()
    monkeypatch.setattr(CallAutomationClient, "from_connection_string", staticmethod(lambda conn, **kw: fake))
    return fake


async def test_the_sdk_client_answers_with_bidirectional_pcm16_websocket_streaming(sdk):
    from azure.communication.callautomation import (
        AudioFormat,
        MediaStreamingAudioChannelType,
        MediaStreamingContentType,
        StreamingTransportType,
    )

    client = SdkAcsClient("endpoint=https://x.communication.azure.com/;accesskey=c2VjcmV0")
    assert isinstance(client, AcsClientPort)
    connection_id = await client.answer_call("ctx-token", "https://cb.example/cb", "wss://ws.example/media")
    assert connection_id == "conn-9"
    _, context, callback, kwargs = next(c for c in sdk.calls if c[0] == "answer")
    assert (context, callback) == ("ctx-token", "https://cb.example/cb")
    options = kwargs["media_streaming"]
    assert options.transport_url == "wss://ws.example/media"
    assert options.transport_type == StreamingTransportType.WEBSOCKET
    assert options.content_type == MediaStreamingContentType.AUDIO
    assert options.audio_channel_type == MediaStreamingAudioChannelType.MIXED
    assert options.start_media_streaming is True and options.enable_bidirectional is True
    assert options.enable_dtmf_tones is True and options.audio_format == AudioFormat.PCM16_K_MONO


async def test_the_sdk_client_hangs_up_and_transfers_by_connection_id(sdk):
    client = SdkAcsClient(
        "endpoint=https://x.communication.azure.com/;accesskey=c2VjcmV0", source_caller_id="+14255550999"
    )
    await client.hang_up("conn-9", True)
    await client.transfer_to_phone("conn-9", "+14255550123")
    kinds = [c[0] for c in sdk.calls]
    assert kinds == ["connection", "hang_up", "connection", "transfer"]
    assert sdk.calls[0][1] == "conn-9" and sdk.calls[1][1] is True
    _, target, kwargs = sdk.calls[3]
    assert target.raw_id == "4:+14255550123" and kwargs["source_caller_id_number"].raw_id == "4:+14255550999"
    await client.aclose()
    assert sdk.closed


async def test_the_sdk_client_omits_the_caller_id_unless_configured(sdk):
    client = SdkAcsClient("endpoint=https://x.communication.azure.com/;accesskey=c2VjcmV0")
    await client.transfer_to_phone("conn-9", "+14255550123")
    assert sdk.calls[-1][2] == {"source_caller_id_number": None}


class HttpFailure(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status


@pytest.mark.parametrize(
    ("status", "cls", "message", "retryable"),
    [
        (401, ProviderRejected, "authentication failed", False),
        (403, ProviderRejected, "authentication failed", False),
        (400, ProviderRejected, "request rejected (HTTP 400)", False),
        (422, ProviderRejected, "request rejected (HTTP 422)", False),
        (404, ProviderError, "the call no longer exists or cannot do that now", False),
        (409, ProviderError, "the call no longer exists or cannot do that now", False),
        (429, ProviderError, "rate limited", True),
        (500, ProviderError, "service unavailable (HTTP 500)", True),
        (503, ProviderError, "service unavailable (HTTP 503)", True),
        (418, ProviderError, "unexpected response (HTTP 418)", False),
    ],
)
@pytest.mark.parametrize("operation", ["answer", "hangup", "transfer"])
async def test_sdk_failures_are_mapped_to_sanitised_provider_errors(sdk, status, cls, message, retryable, operation):
    secret = "accesskey=c2VjcmV0 https://x.communication.azure.com/ +919876543210"
    sdk.error = HttpFailure(status, f"Operation failed: {secret}")
    client = SdkAcsClient("endpoint=https://x.communication.azure.com/;accesskey=c2VjcmV0")
    calls = {
        "answer": lambda: client.answer_call("ctx", "https://cb", "wss://ws"),
        "hangup": lambda: client.hang_up("conn-9", True),
        "transfer": lambda: client.transfer_to_phone("conn-9", "+14255550123"),
    }
    with pytest.raises(ProviderError) as err:
        await calls[operation]()
    assert isinstance(err.value, cls) and err.value.message == message and err.value.retryable is retryable
    assert err.value.status == status and "accesskey" not in str(err.value) and "+91" not in str(err.value)
    assert err.value.__cause__ is None


async def test_network_and_unknown_sdk_errors_are_sanitised(sdk):
    from azure.core.exceptions import ServiceRequestError

    client = SdkAcsClient("endpoint=https://x.communication.azure.com/;accesskey=c2VjcmV0")
    sdk.error = ServiceRequestError("cannot reach https://x.communication.azure.com/?accesskey=c2VjcmV0")
    with pytest.raises(ProviderError) as err:
        await client.hang_up("conn-9", True)
    assert err.value.message == "network error" and err.value.retryable and "accesskey" not in str(err.value)
    sdk.error = ValueError("internal detail accesskey=c2VjcmV0")
    with pytest.raises(ProviderError) as err:
        await client.hang_up("conn-9", True)
    assert err.value.message == "request failed" and not err.value.retryable and "internal" not in str(err.value)


async def test_an_answer_without_a_connection_id_is_an_error(sdk):
    client = SdkAcsClient("endpoint=https://x.communication.azure.com/;accesskey=c2VjcmV0")
    for bad in (None, "", 5):
        sdk.connection_id = bad
        with pytest.raises(ProviderError, match="connection id"):
            await client.answer_call("ctx", "https://cb", "wss://ws")


async def test_the_provider_creates_the_sdk_client_lazily_with_the_secret_and_reuses_it(make_settings, monkeypatch):
    created = []

    class Recorded(FakeAcsClient):
        def __init__(self, connection_string: str) -> None:
            super().__init__()
            created.append(connection_string)

    monkeypatch.setattr(azure_acs, "SdkAcsClient", Recorded)
    provider = AzureAcsTelephonyProvider(make_settings(), tts=FakeTts(), clock=VirtualClock())
    provider.bind(FakeSink())
    assert created == []
    await provider.handle_incoming(event())
    await provider.hangup(ref(), "done")
    assert created == ["endpoint=https://acs-test.communication.azure.com/;accesskey=dGVzdA=="]


async def test_a_missing_or_broken_sdk_or_connection_string_is_unavailable_not_a_crash(make_settings, monkeypatch):
    sink = FakeSink()
    provider = AzureAcsTelephonyProvider(make_settings(acs_connection_string=None), tts=FakeTts(), clock=FastClock())
    provider.bind(sink)
    await provider.handle_incoming(event())
    assert sink.errors and "not configured" in sink.errors[0][2]

    def not_installed(*_a, **_k):
        raise ImportError("No module named azure.communication.callautomation")

    monkeypatch.setattr(azure_acs, "SdkAcsClient", not_installed)
    sink2, provider2 = FakeSink(), AzureAcsTelephonyProvider(make_settings(), tts=FakeTts(), clock=FastClock())
    provider2.bind(sink2)
    await provider2.handle_incoming(event())
    assert "not installed" in sink2.errors[0][2]

    def broken(connection_string):
        raise ValueError(f"bad connection string {connection_string}")

    monkeypatch.setattr(azure_acs, "SdkAcsClient", broken)
    sink3, provider3 = FakeSink(), AzureAcsTelephonyProvider(make_settings(), tts=FakeTts(), clock=FastClock())
    provider3.bind(sink3)
    await provider3.handle_incoming(event())
    assert "invalid" in sink3.errors[0][2] and "accesskey" not in str(sink3.errors)


def test_the_real_sdk_rejects_a_malformed_connection_string_without_us_echoing_it(make_settings):
    provider = AzureAcsTelephonyProvider(
        make_settings(acs_connection_string="definitely-not-a-connection-string"), tts=FakeTts(), clock=VirtualClock()
    )
    with pytest.raises(ProviderUnavailable) as err:
        provider._get_client()
    assert "definitely-not" not in str(err.value) and err.value.message.endswith("is invalid")
