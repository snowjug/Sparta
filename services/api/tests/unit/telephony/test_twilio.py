"""The Twilio adapter, against fakes of the REST client and of the media WebSocket (never a live Twilio account)."""

import asyncio
import base64
import json
import xml.etree.ElementTree as ET

import httpx
import pytest
from pydantic import SecretStr

from sparta.clock import VirtualClock
from sparta.domain.enums import ProviderKind
from sparta.domain.models import SpeechPlan
from sparta.providers.base import ProviderError, ProviderRejected
from sparta.telephony import twilio
from sparta.telephony.base import ProviderCallRef, TelephonyProvider
from sparta.telephony.g711 import ulaw_to_pcm16
from sparta.telephony.twilio import (
    HttpTwilioClient,
    TwilioMediaSession,
    TwilioTelephonyProvider,
    dial_twiml,
    reject_twiml,
    stream_token,
    stream_twiml,
    twilio_signature,
    url_variants,
    verify_twilio_signature,
)

from .helpers import FakeSink, FakeTts, FakeWebSocket, MockHttp

SID = "CA" + "0123456789abcdef" * 2
ACCOUNT = "AC" + "fedcba9876543210" * 2
STREAM = "MZ" + "00112233445566778899aabbccddeeff"
TOKEN = "twilio-auth-token-for-tests"
BASE = "https://sparta.example.test"
CALL = "call_tw0001"
CALLER, CALLED, OWNER = "+14155550100", "+14155550199", "+919876543210"
FIELDS = {"CallSid": SID, "From": CALLER, "To": CALLED, "AccountSid": ACCOUNT, "CallStatus": "ringing"}


@pytest.fixture(autouse=True)
def short_mark_grace(monkeypatch):
    monkeypatch.setattr(twilio, "MARK_GRACE_S", 0.03)


async def settle(rounds: int = 25) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class FakeTwilio:
    """Records Call-resource updates; errors can be queued per operation."""

    def __init__(self) -> None:
        self.hangups: list[str] = []
        self.redirects: list[tuple[str, str]] = []
        self.hangup_errors: list[BaseException] = []
        self.redirect_errors: list[BaseException] = []

    async def hang_up(self, call_sid: str) -> None:
        self.hangups.append(call_sid)
        if self.hangup_errors:
            raise self.hangup_errors.pop(0)

    async def redirect(self, call_sid: str, twiml: str) -> None:
        self.redirects.append((call_sid, twiml))
        if self.redirect_errors:
            raise self.redirect_errors.pop(0)


def plan(text: str = "Hello, you have reached the assistant.", **kw) -> SpeechPlan:
    values = {"text": text, "locale": "en-IN", "voice_id": "en-IN-NeerjaNeural", "est_duration_ms": 20}
    values.update(kw)
    return SpeechPlan(**values)


def ref(call_id: str = CALL) -> ProviderCallRef:
    return ProviderCallRef(call_id=call_id, provider_call_id=SID)


def make(make_settings, *, tts=None, client=None, **kw):
    ctor = {k: kw.pop(k) for k in ("media_attach_timeout_s", "media_start_timeout_s") if k in kw}
    values = {
        "telephony_provider": "twilio",
        "twilio_account_sid": ACCOUNT,
        "twilio_auth_token": TOKEN,
        "twilio_callback_base_url": BASE,
    }
    values.update(kw)
    tts, client, sink = tts or FakeTts(), client or FakeTwilio(), FakeSink(CALL)
    provider = TwilioTelephonyProvider(make_settings(**values), tts=tts, client=client, clock=VirtualClock(), **ctor)
    provider.bind(sink)
    return provider, client, sink, tts


async def accept(provider, sink, *, answer: bool = True, fields=None):
    """Deliver a voice webhook the way the service handles it: answer (and speak) from inside ``incoming_call``."""

    async def on_incoming(call):
        if answer:
            await provider.answer(ProviderCallRef(CALL, provider_call_id=call.provider_call_id))

    sink.on_incoming = on_incoming
    return await provider.handle_voice_webhook(fields or FIELDS)


def start_message(token: str, *, call_sid: str = SID, stream: str = STREAM, **fmt) -> dict:
    media_format = {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1, **fmt}
    return {
        "event": "start",
        "sequenceNumber": "1",
        "start": {
            "accountSid": ACCOUNT,
            "streamSid": stream,
            "callSid": call_sid,
            "tracks": ["inbound"],
            "mediaFormat": media_format,
            "customParameters": {"token": token},
        },
        "streamSid": stream,
    }


def media_message(payload: bytes, *, stream: str = STREAM, track: str = "inbound") -> dict:
    body = {"track": track, "chunk": "1", "timestamp": "5", "payload": base64.b64encode(payload).decode()}
    return {"event": "media", "sequenceNumber": "2", "media": body, "streamSid": stream}


def mark_message(name: str, stream: str = STREAM) -> dict:
    return {"event": "mark", "sequenceNumber": "9", "streamSid": stream, "mark": {"name": name}}


async def attach(provider, *, token: str | None = None, ws: FakeWebSocket | None = None):
    ws = ws or FakeWebSocket()
    token = token if token is not None else provider._calls[CALL].token
    ws.feed({"event": "connected", "protocol": "Call", "version": "1.0.0"}, start_message(token))
    task = asyncio.create_task(provider.attach_media(CALL, ws))
    await settle()
    return ws, task


def parse_twiml(text: str) -> ET.Element:
    return ET.fromstring(text.split("?>", maxsplit=1)[-1])


# ============================================================================================== signatures
def test_the_signature_reproduces_twilios_published_known_answer_vector():
    """The vector from twilio-python's test-suite (auth token 12345): HMAC-SHA1 over the URL and the sorted fields."""
    fields = [
        ("CallSid", "CA1234567890ABCDE"),
        ("Caller", "+14158675309"),
        ("Digits", "1234"),
        ("From", "+14158675309"),
        ("To", "+18005551212"),
    ]
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    assert twilio_signature("12345", url, fields) == "RSOYDt4T1cUTdK1PDd93/VVr8B8="
    assert twilio_signature("12345", url, list(reversed(fields))) == "RSOYDt4T1cUTdK1PDd93/VVr8B8="


def test_a_repeated_field_is_part_of_the_signature_in_a_stable_order():
    a = twilio_signature(TOKEN, "https://x.test/a", [("k", "2"), ("k", "1")])
    b = twilio_signature(TOKEN, "https://x.test/a", [("k", "1"), ("k", "2")])
    assert a == b and a != twilio_signature(TOKEN, "https://x.test/a", [("k", "1")])


def test_verification_accepts_only_the_right_token_url_fields_and_header():
    fields = [("CallSid", SID), ("From", CALLER)]
    header = twilio_signature(TOKEN, f"{BASE}/x", fields)
    assert verify_twilio_signature(TOKEN, header, [f"{BASE}/x"], fields)
    assert not verify_twilio_signature("other-token", header, [f"{BASE}/x"], fields)
    assert not verify_twilio_signature(TOKEN, header, [f"{BASE}/y"], fields)
    assert not verify_twilio_signature(TOKEN, header, [f"{BASE}/x"], [("CallSid", SID), ("From", "+1999")])
    assert not verify_twilio_signature(TOKEN, header, [f"{BASE}/x"], [*fields, ("Extra", "1")])
    for bad in (None, "", "x" * 200, header[:-2], header.lower(), "é" * 28, "\ud800" * 28):  # the last two: not ASCII
        assert not verify_twilio_signature(TOKEN, bad, [f"{BASE}/x"], fields)


def test_either_form_of_the_url_with_or_without_the_default_port_verifies():
    fields = [("CallSid", SID)]
    configured = f"{BASE}/api/v1/webhooks/twilio/voice"
    with_port = "https://sparta.example.test:443/api/v1/webhooks/twilio/voice"
    variants = url_variants(configured)
    assert configured in variants and with_port in variants
    for signed_url in (configured, with_port):
        assert verify_twilio_signature(TOKEN, twilio_signature(TOKEN, signed_url, fields), variants, fields)
    assert url_variants(with_port)[:2] == [with_port, configured]
    assert url_variants("https://h.test:8443/p") == ["https://h.test:8443/p"]


def test_the_websocket_url_is_signed_as_wss_or_https_and_keeps_its_path():
    variants = url_variants("wss://sparta.example.test/api/v1/media/twilio/call_x", schemes=("https",))
    assert "wss://sparta.example.test/api/v1/media/twilio/call_x" in variants
    assert "https://sparta.example.test/api/v1/media/twilio/call_x" in variants
    assert "wss://sparta.example.test:443/api/v1/media/twilio/call_x" in variants
    assert all(v.endswith("/api/v1/media/twilio/call_x") for v in variants)


def test_the_stream_token_is_per_call_secret_derived_and_never_the_auth_token():
    token = stream_token(TOKEN, CALL)
    assert len(token) == 32 and token == stream_token(TOKEN, CALL)
    assert token != stream_token(TOKEN, "call_other") and token != stream_token("other-token", CALL)
    assert TOKEN not in token


# ================================================================================================== TwiML
def test_stream_twiml_is_well_formed_connects_a_stream_and_carries_the_token_as_a_parameter():
    root = parse_twiml(stream_twiml("wss://h.test/api/v1/media/twilio/call_1", "tok123"))
    stream = root.find("./Connect/Stream")
    assert root.tag == "Response" and stream is not None
    assert stream.attrib == {"url": "wss://h.test/api/v1/media/twilio/call_1"}
    parameter = stream.find("Parameter")
    assert parameter is not None and parameter.attrib == {"name": "token", "value": "tok123"}
    assert "?" not in stream.attrib["url"]  # a <Stream> URL may not carry a query string


def test_twiml_values_cannot_break_out_of_their_attribute():
    root = parse_twiml(stream_twiml('wss://h.test/"><Hangup/><x a="', 'a"b<c>&d'))
    assert root.find("./Hangup") is None and root.find("./Connect/Stream/Parameter") is not None
    assert parse_twiml(reject_twiml("busy")).find("./Reject").attrib == {"reason": "busy"}  # type: ignore[union-attr]
    dial = parse_twiml(dial_twiml(OWNER, CALLED))
    assert dial.find("./Dial").attrib == {"callerId": CALLED}  # type: ignore[union-attr]
    assert dial.findtext("./Dial/Number") == OWNER and dial.find("./Hangup") is not None
    hostile = parse_twiml(dial_twiml("+1</Number><Hangup/><Number>", 'x"\x00 y'))
    assert hostile.findtext("./Dial/Number") == "+1</Number><Hangup/><Number>"  # text, not markup
    assert len(hostile.findall(".//Hangup")) == 1 and hostile.find("./Dial").attrib == {"callerId": 'x" y'}  # type: ignore[union-attr]


# ================================================================================================== REST
async def test_hang_up_posts_status_completed_with_basic_auth_and_never_leaks_the_token():
    http = MockHttp(httpx.Response(200, json={"status": "completed"}))
    client = HttpTwilioClient(ACCOUNT, SecretStr(TOKEN), http.client)
    await client.hang_up(SID)
    request = http.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Calls/{SID}.json"
    assert request.content.decode() == "Status=completed"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(f"{ACCOUNT}:{TOKEN}".encode()).decode()
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()


async def test_redirect_posts_inline_twiml():
    http = MockHttp(httpx.Response(200, json={}))
    await HttpTwilioClient(ACCOUNT, SecretStr(TOKEN), http.client).redirect(SID, dial_twiml(OWNER, CALLED))
    body = http.requests[0].content.decode()
    assert body.startswith("Twiml=") and "%3CDial" in body


@pytest.mark.parametrize(
    ("status", "exc_type", "message", "retryable"),
    [
        (401, ProviderRejected, "authentication failed", False),
        (400, ProviderRejected, "HTTP 400", False),
        (404, ProviderError, "not found", False),
        (429, ProviderError, "rate limited", True),
        (503, ProviderError, "unavailable", True),
    ],
)
async def test_rest_failures_are_sanitised_and_classified(status, exc_type, message, retryable):
    http = MockHttp(httpx.Response(status, text="SECRET-BODY https://api.twilio.com/leak"))
    with pytest.raises(exc_type) as caught:
        await HttpTwilioClient(ACCOUNT, SecretStr(TOKEN), http.client).hang_up(SID)
    assert message in caught.value.message and caught.value.retryable is retryable
    assert "SECRET-BODY" not in str(caught.value) and TOKEN not in str(caught.value) and caught.value.status == status


async def test_a_network_failure_and_bad_identifiers_are_handled_without_leaking():
    http = MockHttp(httpx.ConnectError("failed to reach https://api.twilio.com with token " + TOKEN))
    with pytest.raises(ProviderError) as caught:
        await HttpTwilioClient(ACCOUNT, SecretStr(TOKEN), http.client).hang_up(SID)
    assert "network error" in caught.value.message and TOKEN not in str(caught.value)
    http = MockHttp(httpx.Response(200))
    with pytest.raises(ProviderRejected, match="invalid"):
        await HttpTwilioClient(ACCOUNT, SecretStr(TOKEN), http.client).hang_up("not-a-sid/../x")
    with pytest.raises(ProviderRejected, match="invalid"):
        await HttpTwilioClient("nope", SecretStr(TOKEN), http.client).hang_up(SID)
    assert http.requests == []  # nothing was sent for an identifier that is not a SID


# ============================================================================================ media session
def session_for(sink=None, ws=None, **kw):
    sink, ws = sink or FakeSink(CALL), ws or FakeWebSocket()
    marks: list[str] = []
    stops: list[bool] = []

    async def on_stop() -> None:
        stops.append(True)

    session = TwilioMediaSession(
        CALL,
        ws,
        sink,
        expected_token="secret-token",
        expected_call_sid=SID,
        on_mark=marks.append,
        on_stop=on_stop,
        **kw,
    )
    return session, sink, ws, marks, stops


async def feed(session: TwilioMediaSession, *messages) -> None:
    for message in messages:
        await session.handle_message(message if isinstance(message, str) else json.dumps(message))


async def test_a_valid_start_authenticates_and_then_audio_dtmf_marks_and_stop_flow():
    session, sink, _ws, marks, stops = session_for()
    await feed(session, {"event": "connected", "protocol": "Call", "version": "1.0.0"}, start_message("secret-token"))
    assert session.authenticated and session.stream_sid == STREAM and session.ready.is_set()
    await feed(
        session,
        media_message(b"\xff" * 160),
        {"event": "dtmf", "streamSid": STREAM, "dtmf": {"track": "inbound", "digit": "5"}},
        mark_message("pb_1"),
        {"event": "stop", "streamSid": STREAM, "stop": {"accountSid": ACCOUNT, "callSid": SID}},
    )
    assert sink.audio == [(CALL, bytes(320), 8000)]  # 160 mu-law silence bytes -> 320 PCM16 bytes at 8 kHz
    assert sink.dtmf == [(CALL, "5")] and marks == ["pb_1"] and stops == [True] and session.closed


async def test_nothing_is_acted_on_before_the_start_message_authenticates():
    session, sink, _ws, marks, stops = session_for()
    await feed(session, media_message(b"\xff" * 160), mark_message("x"), {"event": "stop", "streamSid": STREAM})
    assert sink.audio == [] and marks == [] and stops == [] and not session.authenticated and not session.closed
    assert session.stats["unauthenticated"] == 3


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (start_message("wrong-token"), "bad_token"),
        (start_message("secret-token", call_sid="CA" + "1" * 32), "wrong_call"),
        (start_message("secret-token", encoding="audio/x-alaw"), "bad_format"),
        (start_message("secret-token", sampleRate=16000), "bad_format"),
        (start_message("secret-token", channels=2), "bad_format"),
    ],
)
async def test_a_start_with_the_wrong_token_call_or_format_closes_the_session(message, reason):
    session, sink, _ws, _marks, _stops = session_for()
    await feed(session, message, media_message(b"\xff" * 160))
    assert session.closed and not session.authenticated and sink.audio == [] and session.stats[reason] == 1


async def test_a_start_without_a_token_or_with_a_forged_stream_sid_is_refused():
    session, *_ = session_for()
    bare = start_message("secret-token")
    del bare["start"]["customParameters"]
    await feed(session, bare)
    assert session.closed and not session.authenticated
    session, *_ = session_for()
    await feed(session, start_message("secret-token", stream="MZnot-a-stream-sid"), start_message("secret-token"))
    assert (
        session.stats["bad_start"] == 1 and session.authenticated
    )  # the garbage start was dropped, the real one counts


async def test_a_second_start_is_ignored_and_cannot_change_the_stream():
    session, *_ = session_for()
    await feed(session, start_message("secret-token"), start_message("secret-token", stream="MZ" + "9" * 32))
    assert session.stream_sid == STREAM and session.stats["repeated_start"] == 1


@pytest.mark.parametrize(
    "message",
    [
        media_message(b"\xff" * 160, stream="MZ" + "9" * 32),  # another stream
        media_message(b"\xff" * 160, track="outbound"),
        {"event": "media", "streamSid": STREAM, "media": {"track": "inbound", "payload": "!!!not base64!!!"}},
        {"event": "media", "streamSid": STREAM, "media": {"track": "inbound", "payload": ""}},
        {"event": "media", "streamSid": STREAM, "media": {"track": "inbound"}},
        {"event": "media", "streamSid": STREAM, "media": "x"},
        {"event": "media", "streamSid": STREAM, "media": {"track": "inbound", "payload": "A" * 40_000}},
        {"event": "dtmf", "streamSid": STREAM, "dtmf": {"digit": "99"}},
        {"event": "mark", "streamSid": STREAM, "mark": {"name": "bad name!"}},
        '{"event": ',
        "[]",
        '{"event": 5}',
        "x" * 70_000,
    ],
)
async def test_malformed_foreign_or_oversized_input_is_counted_and_never_raises(message):
    session, sink, _ws, marks, _stops = session_for()
    await feed(session, start_message("secret-token"))
    await feed(session, message)
    assert sink.audio == [] and sink.dtmf == [] and marks == [] and not session.closed
    assert sum(v for k, v in session.stats.items() if k not in {"start", "connected"}) == 1


async def test_unknown_events_are_ignored_and_a_flood_of_garbage_closes_the_session():
    session, *_ = session_for(max_invalid_frames=3)
    await feed(session, start_message("secret-token"), {"event": "future", "streamSid": STREAM})
    assert session.stats["ignored_event"] == 1 and not session.closed
    await feed(session, "bad", "bad", "bad")
    assert session.closed


async def test_a_sink_that_fails_does_not_end_the_session():
    sink = FakeSink(CALL)
    sink.audio_error = RuntimeError("downstream failure")
    session, *_ = session_for(sink=sink)
    await feed(session, start_message("secret-token"), media_message(b"\xff" * 160), media_message(b"\xff" * 160))
    assert session.stats["handler_error"] == 2 and not session.closed


async def test_run_ends_when_the_socket_closes():
    session, _sink, ws, *_ = session_for()
    ws.feed(start_message("secret-token"))
    ws.disconnect()
    await asyncio.wait_for(session.run(), 1.0)
    assert session.closed and session.authenticated


async def chunks(*pieces: bytes):
    for piece in pieces:
        yield piece


async def test_audio_is_sent_as_base64_mulaw_media_messages_and_a_mark_with_the_playback_name():
    session, _sink, ws, *_ = session_for()
    await feed(session, start_message("secret-token"))
    assert await session.send_audio_stream(chunks(b"\x10" * 800, b"\x11" * 800), mark="pb_7") is True
    frames = ws.frames
    media = [f for f in frames if f["event"] == "media"]
    assert [len(base64.b64decode(f["media"]["payload"])) for f in media] == [640, 640, 320]
    assert b"".join(base64.b64decode(f["media"]["payload"]) for f in media) == b"\x10" * 800 + b"\x11" * 800
    assert frames[-1] == {"event": "mark", "streamSid": STREAM, "mark": {"name": "pb_7"}}
    assert all(f["streamSid"] == STREAM for f in frames) and ws.sent[0].count(" ") == 0  # compact JSON


async def test_a_barge_in_clears_the_buffer_and_stops_sending_without_a_mark():
    session, _sink, ws, *_ = session_for()
    await feed(session, start_message("secret-token"))
    gate = asyncio.Event()

    async def slow():
        yield b"\x10" * 640
        await gate.wait()
        yield b"\x10" * 640

    task = asyncio.create_task(session.send_audio_stream(slow(), mark="pb_8"))
    await settle()
    await session.clear()
    gate.set()
    assert await task is False
    events = [f["event"] for f in ws.frames]
    assert events == ["media", "clear"] and ws.frames[1] == {"event": "clear", "streamSid": STREAM}


async def test_sending_needs_an_authenticated_session_and_an_open_socket():
    session, _sink, ws, *_ = session_for()
    with pytest.raises(ProviderError, match="not connected"):
        await session.send_audio_stream(chunks(b"x"), mark="m")
    await feed(session, start_message("secret-token"))
    ws.fail_send = True
    with pytest.raises(ProviderError, match="media stream closed"):
        await session.send_audio_stream(chunks(b"\x10" * 640), mark="m")
    assert session.closed


# ================================================================================================= provider
def test_capabilities_are_honest_and_the_kind_is_the_generic_other():
    provider, *_ = make(lambda **kw: __import__("sparta.config", fromlist=["Settings"]).Settings(_env_file=None, **kw))
    caps = provider.capabilities
    assert isinstance(provider, TelephonyProvider)
    assert (provider.name, provider.kind) == ("twilio", ProviderKind.OTHER)
    assert caps.can_play_audio and caps.can_stop_playback and caps.can_transfer and caps.can_hangup and caps.dtmf
    assert caps.receives_caller_audio and caps.simulated is False and caps.live_calls_supported is True
    assert caps.two_way_audio is False and "UNVERIFIED" in caps.note and "+91" in caps.note


@pytest.mark.parametrize("missing", ["twilio_account_sid", "twilio_auth_token", "twilio_callback_base_url"])
def test_live_calls_need_the_sid_the_token_and_the_callback_url(make_settings, missing):
    assert make(make_settings)[0].capabilities.live_calls_supported is True
    provider, *_ = make(make_settings, **{missing: None})
    assert provider.capabilities.live_calls_supported is False
    assert make(make_settings, tts=FakeTts(simulated=True))[0].capabilities.can_play_audio is False


async def test_the_voice_webhook_creates_the_call_once_and_answers_with_a_stream_to_this_server(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    result = await accept(provider, sink)
    assert result.call_id == CALL
    incoming = sink.incoming[0]
    assert (incoming.provider, incoming.provider_call_id, incoming.correlation_id) == ("twilio", SID, SID)
    assert (incoming.caller_number, incoming.called_number) == (CALLER, CALLED)
    stream = parse_twiml(result.twiml).find("./Connect/Stream")
    assert stream is not None and stream.attrib["url"] == f"wss://sparta.example.test/api/v1/media/twilio/{CALL}"
    assert stream.find("Parameter").attrib["value"] == stream_token(TOKEN, CALL)  # type: ignore[union-attr]
    assert provider.redeliver(SID) == result.twiml and "Reject" in provider.redeliver("CA" + "2" * 32)


async def test_two_concurrent_deliveries_of_the_same_call_create_one_call(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    gate = asyncio.Event()

    async def on_incoming(call):
        await gate.wait()
        await provider.answer(ProviderCallRef(CALL, provider_call_id=call.provider_call_id))

    sink.on_incoming = on_incoming
    first = asyncio.create_task(provider.handle_voice_webhook(FIELDS))
    second = asyncio.create_task(provider.handle_voice_webhook(FIELDS))
    await settle()
    gate.set()
    a, b = await asyncio.gather(first, second)
    assert a == b and len(sink.incoming) == 1


async def test_a_blocked_caller_is_rejected_not_answered(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    result = await accept(provider, sink, answer=False)  # the service ends a blocked number without answering
    assert parse_twiml(result.twiml).find("./Reject") is not None and provider._calls == {}


async def test_an_unusable_webhook_is_rejected_and_a_failed_acceptance_can_be_retried(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    for bad in ({}, {"CallSid": "CA123"}, {"CallSid": SID + "x"}):
        with pytest.raises(ProviderRejected, match="invalid call identifier"):
            await provider.handle_voice_webhook(bad)
    sink.incoming_error = RuntimeError("limit reached")
    with pytest.raises(RuntimeError):
        await provider.handle_voice_webhook(FIELDS)
    assert provider._pending == {}  # nothing is left behind
    sink.incoming_error = None
    assert (await accept(provider, sink)).call_id == CALL


async def test_phone_numbers_that_are_not_e164_are_not_passed_on(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink, fields={**FIELDS, "From": "anonymous", "To": "<script>"})
    assert sink.incoming[0].caller_number is None and sink.incoming[0].called_number is None


async def test_speech_is_sent_as_mulaw_then_a_mark_and_its_echo_finishes_the_playback(make_settings):
    provider, _client, sink, tts = make(make_settings)
    await accept(provider, sink)
    ws, _task = await attach(provider)
    assert provider.capabilities_for_call(CALL).two_way_audio is True
    playback = await provider.play(ref(), plan())
    await settle()
    assert tts.requests[0].output_format == "mulaw_8k" and tts.requests[0].trace_id == playback.playback_id
    frames = ws.frames
    media = [f for f in frames if f["event"] == "media"]
    assert b"".join(base64.b64decode(f["media"]["payload"]) for f in media) == bytes([7]) * 1600
    assert [f["mark"]["name"] for f in frames if f["event"] == "mark"] == [playback.playback_id]
    assert sink.finished == []  # not before Twilio says the audio has played
    ws.feed(mark_message(playback.playback_id))
    await settle()
    assert sink.finished == [(CALL, playback.playback_id)]


async def test_a_missing_mark_echo_does_not_hang_the_call_it_finishes_after_the_estimate(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    _ws, _task = await attach(provider)
    playback = await provider.play(ref(), plan())
    await asyncio.sleep(0.15)  # the estimate (20 ms) plus the shortened grace
    assert sink.finished == [(CALL, playback.playback_id)]


async def test_barge_in_clears_twilios_buffer_and_the_late_mark_echo_is_ignored(make_settings):
    provider, _client, sink, tts = make(make_settings)
    await accept(provider, sink)
    ws, _task = await attach(provider)
    tts.gate = asyncio.Event()  # the synthesiser stalls after its first chunk
    playback = await provider.play(ref(), plan())
    await settle()
    await provider.stop_playback(ref(), playback.playback_id)
    assert {"event": "clear", "streamSid": STREAM} in ws.frames
    assert tts.stopped == [playback.playback_id] and sink.finished == []
    ws.feed(mark_message(playback.playback_id))  # Twilio echoes the marks it dropped
    await settle()
    assert sink.finished == []
    tts.gate = None
    again = await provider.play(ref(), plan("And again."))
    await settle()
    ws.feed(mark_message(again.playback_id))
    await settle()
    assert sink.finished == [(CALL, again.playback_id)]  # the call recovers: the next line plays normally


async def test_speaking_without_a_connected_stream_reports_a_provider_error(make_settings):
    provider, _client, sink, _tts = make(make_settings, media_attach_timeout_s=0.05)
    await accept(provider, sink)
    await provider.play(ref(), plan())
    await asyncio.sleep(0.2)
    assert (CALL, "play", "the media stream is not connected") in sink.errors and sink.finished == []


async def test_a_real_tts_is_required_and_an_unknown_call_cannot_speak(make_settings):
    provider, _client, sink, _tts = make(make_settings, tts=FakeTts(simulated=True))
    await accept(provider, sink)
    with pytest.raises(ProviderRejected, match="real text-to-speech"):
        await provider.play(ref(), plan())
    other, *_ = make(make_settings)
    with pytest.raises(ProviderRejected, match="not active"):
        await other.play(ref(), plan())


async def test_a_failing_synthesiser_is_reported_and_does_not_report_a_finished_playback(make_settings):
    tts = FakeTts()
    tts.error = ProviderError("fake-tts", "tts", "synthesis failed")
    provider, _client, sink, _tts = make(make_settings, tts=tts)
    await accept(provider, sink)
    await attach(provider)
    await provider.play(ref(), plan())
    await settle()
    assert (CALL, "play", "synthesis failed") in sink.errors and sink.finished == []


async def test_caller_audio_reaches_the_sink_as_pcm16_at_8_khz(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    ws, _task = await attach(provider)
    ws.feed(media_message(bytes([0x00, 0x80] * 80)))
    await settle()
    assert sink.audio == [(CALL, ulaw_to_pcm16(bytes([0x00, 0x80] * 80)), 8000)]


async def test_twilio_stopping_the_stream_ends_the_call_once(make_settings):
    provider, client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    ws, task = await attach(provider)
    ws.feed({"event": "stop", "streamSid": STREAM, "stop": {"accountSid": ACCOUNT, "callSid": SID}})
    await asyncio.wait_for(task, 1.0)
    assert sink.hangups == [(CALL, "disconnected")] and provider._calls == {} and client.hangups == []


async def test_an_authenticated_socket_that_just_closes_ends_the_call(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    ws, task = await attach(provider)
    ws.disconnect()
    await asyncio.wait_for(task, 1.0)
    assert sink.hangups == [(CALL, "disconnected")]


async def test_a_strangers_socket_with_the_wrong_token_never_ends_anyones_call(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    ws, task = await attach(provider, token="guessed-token")
    ws.disconnect()
    await asyncio.wait_for(task, 1.0)
    assert sink.hangups == [] and CALL in provider._calls
    assert provider.capabilities_for_call(CALL).two_way_audio is False


async def test_a_reconnect_replaces_the_socket_without_ending_the_call(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    first_ws, first = await attach(provider)
    second_ws, second = await attach(provider)
    await asyncio.wait_for(first, 1.0)
    assert sink.hangups == [] and provider.capabilities_for_call(CALL).two_way_audio is True
    second_ws.disconnect()
    await asyncio.wait_for(second, 1.0)
    assert sink.hangups == [(CALL, "disconnected")] and first_ws is not second_ws


async def test_a_socket_that_cannot_prove_the_token_never_displaces_the_live_stream(make_settings):
    """Even with the upgrade signature switched off, only a socket that has authenticated can replace the live one."""
    provider, _client, sink, _tts = make(make_settings, twilio_verify_media_signature=False)
    await accept(provider, sink)
    _live_ws, live = await attach(provider)
    live_session = provider._calls[CALL].session
    assert live_session is not None and live_session.authenticated
    for bad_token in ("guessed-token", "tökén", "\ud800"):  # wrong, non-ASCII, a lone surrogate
        _stranger_ws, stranger = await attach(provider, token=bad_token)
        await asyncio.wait_for(stranger, 1.0)  # refused and closed on its own
        assert provider._calls[CALL].session is live_session and not live_session.closed and not live.done()
        assert provider.capabilities_for_call(CALL).two_way_audio is True
    assert sink.hangups == [] and sink.errors == []


async def test_a_socket_that_never_sends_start_is_closed_and_displaces_nothing(make_settings):
    provider, _client, sink, _tts = make(make_settings, media_start_timeout_s=0.05)
    await accept(provider, sink)
    _live_ws, live = await attach(provider)
    live_session = provider._calls[CALL].session
    idle_ws = FakeWebSocket()
    idle_ws.feed({"event": "connected", "protocol": "Call", "version": "1.0.0"})
    await asyncio.wait_for(provider.attach_media(CALL, idle_ws), 1.0)  # returns once the start timeout cancels it
    assert provider._calls[CALL].session is live_session and not live_session.closed and not live.done()
    assert sink.hangups == []


async def test_a_socket_that_authenticates_after_the_call_ended_is_dropped_not_attached(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    token = provider._calls[CALL].token
    late_ws = FakeWebSocket()
    late = asyncio.create_task(provider.attach_media(CALL, late_ws))
    await settle()  # pending: nothing sent yet
    await provider.hangup(ref(), "ended")
    late_ws.feed(start_message(token))
    await asyncio.wait_for(late, 1.0)
    assert CALL not in provider._calls and sink.hangups == []


async def test_hang_up_is_idempotent_and_ends_the_twilio_call(make_settings):
    provider, client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    _ws, task = await attach(provider)
    await provider.hangup(ref(), "ended")
    await provider.hangup(ref(), "ended")
    await asyncio.wait_for(task, 1.0)
    assert client.hangups == [SID] and sink.hangups == [] and provider._calls == {}  # our own hang-up is not "remote"
    with pytest.raises(ProviderRejected, match="already ended"):
        await provider.answer(ref())


@pytest.mark.parametrize("status", [400, 404])
async def test_a_call_that_is_already_over_is_not_an_error(make_settings, status):
    provider, client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    client.hangup_errors.append(ProviderRejected("twilio", "hangup", "gone", status=status))
    await provider.hangup(ref(), "ended")
    assert client.hangups == [SID]


async def test_other_hang_up_failures_surface_and_an_unanswered_call_is_never_answered_later(make_settings):
    provider, client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    client.hangup_errors.append(ProviderRejected("twilio", "hangup", "authentication failed", status=401))
    with pytest.raises(ProviderRejected):
        await provider.hangup(ref(), "ended")
    fresh, _c, _s, _t = make(make_settings)
    await fresh.hangup(ref("call_never_answered"), "blocked")
    with pytest.raises(ProviderRejected, match="already ended"):
        await fresh.answer(ref("call_never_answered"))


async def test_takeover_redirects_the_call_to_dial_the_owner_with_the_dialled_number_as_caller_id(make_settings):
    provider, client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    result = await provider.transfer(ref(), OWNER)
    assert result.accepted and not result.simulated and "dialling" in result.detail
    call_sid, twiml = client.redirects[0]
    assert call_sid == SID
    dial = parse_twiml(twiml).find("./Dial")
    assert dial is not None and dial.attrib["callerId"] == CALLED and dial.findtext("Number") == OWNER


async def test_takeover_uses_the_configured_caller_id_and_validates_everything(make_settings):
    provider, client, sink, _tts = make(make_settings, twilio_caller_id="+14155550123")
    await accept(provider, sink)
    assert (await provider.transfer(ref(), OWNER)).accepted
    assert 'callerId="+14155550123"' in client.redirects[0][1]
    for bad in (None, "", "12345", "+0123456789", "+91 98765 43210", "tel:+919876543210", OWNER + "<"):
        outcome = await provider.transfer(ref(), bad)
        assert not outcome.accepted and "valid phone number" in outcome.detail
    assert len(client.redirects) == 1
    missing, _c, _sink2, _t = make(make_settings)
    assert not (await missing.transfer(ref(), OWNER)).accepted  # an unknown call cannot be transferred
    noid, _c, sink3, _t = make(make_settings)
    await accept(noid, sink3, fields={**FIELDS, "To": ""})
    assert "caller id" in (await noid.transfer(ref(), OWNER)).detail


async def test_a_transfer_is_never_retried_and_a_failure_is_reported_honestly(make_settings):
    provider, client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    client.redirect_errors.append(ProviderError("twilio", "transfer", "service unavailable", retryable=True))
    outcome = await provider.transfer(ref(), OWNER)
    assert not outcome.accepted and "not accepted" in outcome.detail and len(client.redirects) == 1


async def test_the_takeover_waits_for_its_announcement_to_be_heard_before_it_redirects(make_settings):
    provider, client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    ws, _task = await attach(provider)
    playback = await provider.play(ref(), plan("Connecting you now."))
    await settle()
    transfer = asyncio.create_task(provider.transfer(ref(), OWNER))
    await settle()
    assert client.redirects == [] and not transfer.done()  # the stream would cut the announcement off
    ws.feed(mark_message(playback.playback_id))
    assert (await asyncio.wait_for(transfer, 1.0)).accepted and len(client.redirects) == 1


async def test_the_wait_for_the_announcement_is_bounded_and_skipped_without_a_stream(make_settings, monkeypatch):
    monkeypatch.setattr(twilio, "TRANSFER_SPEECH_WAIT_S", 0.05)
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    _ws, _task = await attach(provider)
    await provider.play(ref(), plan("Connecting you now.", est_duration_ms=5000))
    await settle()
    assert (await asyncio.wait_for(provider.transfer(ref(), OWNER), 1.0)).accepted  # no echo ever came

    quiet, quiet_client, quiet_sink, _t = make(make_settings, media_attach_timeout_s=30)
    await accept(quiet, quiet_sink)
    await quiet.play(ref(), plan())  # no media socket: the line cannot be heard, so there is nothing to wait for
    assert (await asyncio.wait_for(quiet.transfer(ref(), OWNER), 1.0)).accepted and len(quiet_client.redirects) == 1


async def test_a_terminal_status_callback_ends_the_call_and_other_statuses_do_not(make_settings):
    provider, _client, sink, _tts = make(make_settings)
    await accept(provider, sink)
    for ignored in (
        {"CallSid": SID, "CallStatus": "in-progress"},
        {"CallSid": "CA" + "3" * 32, "CallStatus": "completed"},
        {"CallSid": "bad", "CallStatus": "completed"},
    ):
        await provider.handle_status_callback(ignored)
    assert sink.hangups == []
    await provider.handle_status_callback({"CallSid": SID, "CallStatus": "completed"})
    assert sink.hangups == [(CALL, "disconnected")]


async def test_the_media_upgrade_signature_can_be_required_or_relaxed(make_settings):
    provider, *_ = make(make_settings)
    wss_url, variants = provider.media_urls(CALL)
    header = twilio_signature(TOKEN, wss_url, [])
    assert provider.verify_media_upgrade(CALL, header) and not provider.verify_media_upgrade(CALL, None)
    assert not provider.verify_media_upgrade("call_other", header)
    https_header = twilio_signature(TOKEN, wss_url.replace("wss://", "https://"), [])
    assert provider.verify_media_upgrade(CALL, https_header) and wss_url in variants
    relaxed, *_ = make(make_settings, twilio_verify_media_signature=False)
    assert relaxed.verify_media_upgrade(CALL, None)  # the per-call token still authenticates the socket
    with pytest.raises(Exception, match="call id"):
        provider.media_urls("../bad")


async def test_status_reports_health_and_never_the_credentials(make_settings):
    provider, *_ = make(make_settings)
    status = await provider.status()
    assert status.healthy and status.provider == "twilio" and status.extra["live_calls_supported"] == "true"
    assert TOKEN not in json.dumps(status.extra) and TOKEN not in status.detail
    quiet, *_ = make(make_settings, tts=FakeTts(simulated=True))
    degraded = await quiet.status()
    assert not degraded.healthy and "silent" in degraded.detail


async def test_closing_the_provider_ends_every_call_and_stops_playback(make_settings):
    provider, _client, sink, tts = make(make_settings)
    await accept(provider, sink)
    _ws, task = await attach(provider)
    tts.gate = asyncio.Event()
    await provider.play(ref(), plan())
    await settle()
    await provider.aclose()
    await asyncio.wait_for(task, 1.0)
    assert provider._calls == {}
