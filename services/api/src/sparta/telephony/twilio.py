"""Twilio Programmable Voice telephony adapter (Media Streams, bidirectional).

**Live Twilio behaviour is UNVERIFIED.** No Twilio account was available: everything here is exercised only against
fakes of the REST client and of the media WebSocket. Facts used come from Twilio's documentation (Media Streams
WebSocket messages, the ``<Stream>`` TwiML noun, webhook security, the Call resource) as read on 2026-11-18; the
signature algorithm reproduces a published known-answer vector.

Why this adapter exists: Azure Communication Services cannot supply a number for a new customer (see
``docs/TELEPHONY.md``, "Provider decision"). The shape of the integration follows the ACS adapter so the rest of Sparta
does not change:

* ``POST /api/v1/webhooks/twilio/voice`` is the number's *voice webhook*. It verifies ``X-Twilio-Signature`` (HMAC-SHA1
  over the public URL and the sorted form fields, keyed with the auth token), creates the Sparta call through the event
  sink and answers with ``<Connect><Stream>`` TwiML pointing at this server's media WebSocket. A blocked caller or a call
  over a limit gets ``<Reject>`` instead (which Twilio does not bill).
* ``/api/v1/media/twilio/{call_id}`` is the bidirectional media WebSocket. Caller audio arrives as 8 kHz mu-law frames
  and is handed to the sink as PCM16; assistant speech goes back as mu-law ``media`` messages followed by a ``mark``
  whose echo says exactly when it finished playing; barge-in is a ``clear`` message.
* The socket is authenticated twice: Twilio's signature on the upgrade request, and a per-call token (an HMAC of the
  call id) that only the TwiML response carried and that Twilio returns in the ``start`` message
  (``<Stream>`` URLs cannot carry a query string, so the token travels as a ``<Parameter>``).
* Hang-up and takeover are REST updates of the Call resource (``Status=completed`` and inline ``Twiml`` with ``<Dial>``).
"""

import asyncio
import base64
import binascii
import contextlib
import dataclasses
import hashlib
import hmac
import itertools
import json
import logging
import re
from collections import Counter, OrderedDict
from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit
from xml.sax.saxutils import quoteattr

import httpx
from pydantic import SecretStr

from sparta.clock import Clock, SystemClock
from sparta.config import Settings
from sparta.domain.enums import ProviderKind
from sparta.domain.models import SpeechPlan
from sparta.observability.metrics import PROVIDER_ERRORS, PROVIDER_LATENCY_MS, Metrics
from sparta.providers.azure_common import error_for_status, error_for_transport, https_origin
from sparta.providers.base import (
    ProviderError,
    ProviderRejected,
    ProviderUnavailable,
    SynthesisRequest,
    TextToSpeechProvider,
)
from sparta.providers.resilience import BreakerState, CircuitBreaker, ResilientCaller
from sparta.providers.tts.ssml import estimate_duration_ms
from sparta.telephony.base import (
    IncomingCall,
    Playback,
    ProviderCallRef,
    ProviderStatus,
    TelephonyCapabilities,
    TelephonyEventSink,
    TransferResult,
)
from sparta.telephony.g711 import ulaw_to_pcm16

log = logging.getLogger("sparta.telephony.twilio")

PROVIDER = "twilio"
API_BASE = "https://api.twilio.com"
VOICE_PATH = "/api/v1/webhooks/twilio/voice"
STATUS_PATH = "/api/v1/webhooks/twilio/status"
MEDIA_PATH = "/api/v1/media/twilio"
SAMPLE_RATE = 8000
FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law
SEND_CHUNK_BYTES = FRAME_BYTES * 4  # 80 ms per media message
MAX_MESSAGE_CHARS = 65_536
MAX_PAYLOAD_BYTES = 16_384
MAX_INVALID_FRAMES = 500
MAX_FORM_FIELDS = 100
MAX_TRACKED = 1024
PENDING_TTL_S = 120.0
MARK_GRACE_S = 5.0  # how long past the estimated duration a missing mark echo is waited for
TRANSFER_SPEECH_WAIT_S = 8.0  # how long a takeover waits for its announcement to be heard before it redirects
TOKEN_CHARS = 32

CALL_SID = re.compile(r"CA[0-9a-f]{32}")
ACCOUNT_SID = re.compile(r"AC[0-9a-f]{32}")
STREAM_SID = re.compile(r"MZ[0-9a-f]{32}")
_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_MARK = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DTMF = re.compile(r"[0-9A-Da-d*#]")
_E164 = re.compile(r"\+[1-9][0-9]{6,14}")
_DEFAULT_PORTS = {"https": 443, "wss": 443, "http": 80, "ws": 80}

NOTE = (
    "Twilio Programmable Voice with bidirectional Media Streams. Live behaviour is UNVERIFIED: no live call was tested. "
    "An Indian (+91) number needs a Twilio regulatory bundle; see docs/TELEPHONY.md."
)


# ------------------------------------------------------------------------------------------- request signatures
def twilio_signature(auth_token: str, url: str, fields: Sequence[tuple[str, str]]) -> str:
    """``X-Twilio-Signature``: base64 of HMAC-SHA1 over ``url`` followed by every field name and value, sorted.

    Algorithm from Twilio's "Validating requests" page; reproduces the published vector (see the tests).
    """
    data = url + "".join(f"{name}{value}" for name, value in sorted(fields))
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def url_variants(url: str, *, schemes: Sequence[str] = ()) -> list[str]:
    """The URL as configured, with and without its default port (Twilio may sign either form), per scheme."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    host_part = f"[{host}]" if ":" in host else host
    out: list[str] = []
    for scheme in (parts.scheme, *schemes):
        default = _DEFAULT_PORTS.get(scheme)
        netlocs = [parts.netloc]
        if parts.port is None and default is not None:
            netlocs.append(f"{host_part}:{default}")
        elif parts.port is not None and parts.port == default:
            netlocs.append(host_part)
        for netloc in netlocs:
            candidate = parts._replace(scheme=scheme, netloc=netloc).geturl()
            if candidate not in out:
                out.append(candidate)
    return out


def verify_twilio_signature(
    auth_token: str, header: str | None, urls: Sequence[str], fields: Sequence[tuple[str, str]]
) -> bool:
    if not header or len(header) > 128:
        return False
    return any(hmac.compare_digest(twilio_signature(auth_token, url, fields), header) for url in urls)


def stream_token(auth_token: str, call_id: str) -> str:
    """Per-call secret returned by Twilio in the ``start`` message: an HMAC of the call id, never the auth token."""
    key = hashlib.sha256(b"sparta-twilio-stream-token\0" + auth_token.encode("utf-8")).digest()
    return hmac.new(key, call_id.encode("ascii"), hashlib.sha256).hexdigest()[:TOKEN_CHARS]


# ------------------------------------------------------------------------------------------------------ TwiML
_XML = '<?xml version="1.0" encoding="UTF-8"?>'


def stream_twiml(ws_url: str, token: str) -> str:
    return (
        f"{_XML}<Response><Connect><Stream url={quoteattr(ws_url)}>"
        f'<Parameter name="token" value={quoteattr(token)}/></Stream></Connect></Response>'
    )


def reject_twiml(reason: str = "busy") -> str:
    return f"{_XML}<Response><Reject reason={quoteattr(reason)}/></Response>"


def dial_twiml(destination: str, caller_id: str) -> str:
    return (
        f"{_XML}<Response><Dial callerId={quoteattr(caller_id)}><Number>{destination}</Number></Dial>"
        "<Say>The person could not be reached. Goodbye.</Say><Hangup/></Response>"
    )


# --------------------------------------------------------------------------------------------------- REST client
@runtime_checkable
class TwilioClientPort(Protocol):
    """The two Call-resource updates Sparta needs, plus a read used by the doctor."""

    async def hang_up(self, call_sid: str) -> None: ...

    async def redirect(self, call_sid: str, twiml: str) -> None: ...


class HttpTwilioClient:
    """:class:`TwilioClientPort` over the Twilio REST API (HTTP Basic with the account SID and auth token)."""

    def __init__(
        self,
        account_sid: str,
        auth_token: SecretStr,
        http: httpx.AsyncClient,
        *,
        base_url: str = API_BASE,
        timeout_s: float = 6.0,
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        self._http = http
        self._base = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def _update(self, stage: str, call_sid: str, form: dict[str, str]) -> None:
        if not CALL_SID.fullmatch(call_sid) or not ACCOUNT_SID.fullmatch(self._sid):
            raise ProviderRejected(PROVIDER, stage, "invalid call or account identifier")
        url = f"{self._base}/2010-04-01/Accounts/{self._sid}/Calls/{call_sid}.json"
        try:
            response = await self._http.post(
                url,
                data=form,
                auth=httpx.BasicAuth(self._sid, self._token.get_secret_value()),
                headers={"Accept": "application/json"},
                timeout=self._timeout_s,
                follow_redirects=False,
            )
        except (httpx.HTTPError, OSError) as exc:
            raise error_for_transport(PROVIDER, stage, exc, self._timeout_s) from None
        error = error_for_status(PROVIDER, stage, response.status_code)
        if error is not None:
            raise error

    async def hang_up(self, call_sid: str) -> None:
        await self._update("hangup", call_sid, {"Status": "completed"})

    async def redirect(self, call_sid: str, twiml: str) -> None:
        await self._update("transfer", call_sid, {"Twiml": twiml})


# ---------------------------------------------------------------------------------------------- media WebSocket
@runtime_checkable
class WebSocketLike(Protocol):
    async def receive_text(self) -> str: ...

    async def send_text(self, data: str) -> None: ...


class TwilioMediaSession:
    """One call's media WebSocket: parses Twilio -> server messages and sends server -> Twilio audio.

    Messages in (``event`` selects the kind)::

        {"event":"connected","protocol":"Call","version":"1.0.0"}
        {"event":"start","start":{"streamSid","callSid","tracks","customParameters","mediaFormat"},"streamSid"}
        {"event":"media","media":{"track":"inbound","chunk","timestamp","payload":"<base64 mu-law>"},"streamSid"}
        {"event":"dtmf","dtmf":{"track":"inbound","digit":"1"},"streamSid"}
        {"event":"mark","mark":{"name":"..."},"streamSid"}
        {"event":"stop","stop":{"accountSid","callSid"},"streamSid"}

    Messages out::

        {"event":"media","streamSid":"MZ...","media":{"payload":"<base64 mu-law 8 kHz>"}}
        {"event":"mark","streamSid":"MZ...","mark":{"name":"..."}}
        {"event":"clear","streamSid":"MZ..."}

    Nothing is acted on before the ``start`` message carries the right call SID and the per-call token. Malformed,
    oversized or unexpected input is counted and dropped, never raised; the session ends after
    ``max_invalid_frames`` invalid frames.
    """

    def __init__(
        self,
        call_id: str,
        websocket: WebSocketLike,
        sink: TelephonyEventSink,
        *,
        expected_token: str,
        expected_call_sid: str | None,
        on_mark: Any = None,
        on_stop: Any = None,
        metrics: Metrics | None = None,
        max_invalid_frames: int = MAX_INVALID_FRAMES,
    ) -> None:
        self._call_id = call_id
        self._ws = websocket
        self._sink = sink
        self._token = expected_token
        self._call_sid = expected_call_sid
        self._on_mark = on_mark
        self._on_stop = on_stop
        self._metrics = metrics or Metrics()
        self._max_invalid = max_invalid_frames
        self.stream_sid: str | None = None
        self.authenticated = False
        self.closed = False
        self.stats: Counter[str] = Counter()
        self.ready = asyncio.Event()
        self._invalid = 0
        self._generation = 0
        self._write_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()

    # ------------------------------------------------------------------------------------- Twilio -> server
    async def run(self) -> None:
        try:
            while not self.closed:
                try:
                    text = await self._ws.receive_text()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    break  # disconnect: framework-specific exception types are deliberately not imported
                await self.handle_message(text)
        finally:
            self.closed = True

    async def handle_message(self, text: str) -> None:
        try:
            await self._dispatch(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._drop("handler_error", invalid=False)
            log.warning("media message handling failed", extra={"call_id": self._call_id, "error": type(exc).__name__})

    def _drop(self, reason: str, *, invalid: bool = True) -> None:
        self.stats[reason] += 1
        self._metrics.inc(PROVIDER_ERRORS, provider=PROVIDER, stage="media", kind=reason)
        if invalid:
            self._invalid += 1
            if self._invalid >= self._max_invalid:
                self.closed = True

    async def _dispatch(self, text: str) -> None:
        if not isinstance(text, str) or len(text) > MAX_MESSAGE_CHARS:
            self._drop("too_large")
            return
        try:
            message = json.loads(text)
        except (ValueError, RecursionError):
            self._drop("malformed")
            return
        event = message.get("event") if isinstance(message, dict) else None
        if not isinstance(event, str):
            self._drop("malformed")
            return
        if event == "connected":
            self.stats["connected"] += 1
            return
        if event == "start":
            self._on_start(message.get("start"))
            return
        if not self.authenticated:
            self._drop("unauthenticated")  # nothing is acted on before a valid start message
            return
        if message.get("streamSid") != self.stream_sid:
            self._drop("wrong_stream")
            return
        if event == "media":
            await self._on_media(message.get("media"))
        elif event == "dtmf":
            await self._on_dtmf(message.get("dtmf"))
        elif event == "mark":
            self._on_mark_message(message.get("mark"))
        elif event == "stop":
            self.stats["stop"] += 1
            self.closed = True
            if self._on_stop is not None:
                await self._on_stop()
        else:
            self.stats["ignored_event"] += 1

    def _on_start(self, start: object) -> None:
        if self.authenticated:
            self._drop("repeated_start")
            return
        if not isinstance(start, dict):
            self._drop("bad_start")
            return
        stream_sid, call_sid = start.get("streamSid"), start.get("callSid")
        params = start.get("customParameters")
        token = params.get("token") if isinstance(params, dict) else None
        fmt = start.get("mediaFormat")
        good_format = (
            isinstance(fmt, dict)
            and fmt.get("encoding") == "audio/x-mulaw"
            and fmt.get("sampleRate") == SAMPLE_RATE
            and fmt.get("channels") == 1
        )
        if not isinstance(stream_sid, str) or not STREAM_SID.fullmatch(stream_sid):
            self._drop("bad_start")
        elif self._call_sid is not None and call_sid != self._call_sid:
            self._fail_auth("wrong_call")
        elif not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            self._fail_auth("bad_token")
        elif not good_format:
            self._fail_auth("bad_format")
        else:
            self.stream_sid = stream_sid
            self.authenticated = True
            self.stats["start"] += 1
            self.ready.set()

    def _fail_auth(self, reason: str) -> None:
        self._drop(reason)
        self.closed = True  # a socket that fails authentication is closed, not retried

    async def _on_media(self, media: object) -> None:
        if not isinstance(media, dict) or media.get("track") != "inbound":
            self._drop("bad_media")
            return
        payload = media.get("payload")
        if not isinstance(payload, str) or not payload or len(payload) > MAX_PAYLOAD_BYTES * 4 // 3 + 8:
            self._drop("bad_media")
            return
        try:
            ulaw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            self._drop("bad_media")
            return
        if not ulaw or len(ulaw) > MAX_PAYLOAD_BYTES:
            self._drop("bad_media")
            return
        self.stats["audio_frames"] += 1
        await self._sink.caller_audio(self._call_id, ulaw_to_pcm16(ulaw), SAMPLE_RATE)

    async def _on_dtmf(self, dtmf: object) -> None:
        digit = dtmf.get("digit") if isinstance(dtmf, dict) else None
        if not isinstance(digit, str) or not _DTMF.fullmatch(digit):
            self._drop("bad_dtmf")
            return
        self.stats["dtmf"] += 1
        await self._sink.caller_dtmf(self._call_id, digit.upper())

    def _on_mark_message(self, mark: object) -> None:
        name = mark.get("name") if isinstance(mark, dict) else None
        if not isinstance(name, str) or not _MARK.fullmatch(name):
            self._drop("bad_mark")
            return
        self.stats["marks"] += 1
        if self._on_mark is not None:
            self._on_mark(name)

    # ------------------------------------------------------------------------------------- server -> Twilio
    async def _send_json(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, separators=(",", ":"))
        try:
            async with self._write_lock:
                await self._ws.send_text(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.closed = True
            raise ProviderError(PROVIDER, "media", "media stream closed") from None

    async def send_audio_stream(self, chunks: AsyncIterable[bytes], *, mark: str) -> bool:
        """Send mu-law audio, then a ``mark`` named ``mark``. ``False`` when interrupted (no mark is sent).

        Twilio buffers what it receives and plays it in order, so nothing is paced here; a barge-in empties that
        buffer with ``clear``.
        """
        if not self.authenticated or self.stream_sid is None:
            raise ProviderError(PROVIDER, "media", "the media stream is not connected")
        sid = self.stream_sid
        iterator = chunks.__aiter__()
        async with self._send_lock:
            generation = self._generation
            buffer = bytearray()
            try:
                async for chunk in iterator:
                    buffer += chunk
                    while len(buffer) >= SEND_CHUNK_BYTES:
                        piece = bytes(buffer[:SEND_CHUNK_BYTES])
                        del buffer[:SEND_CHUNK_BYTES]
                        if self.closed or generation != self._generation:
                            return False
                        await self._send_json(self._media(sid, piece))
                if buffer:
                    if self.closed or generation != self._generation:
                        return False
                    await self._send_json(self._media(sid, bytes(buffer)))
                if self.closed or generation != self._generation:
                    return False
                await self._send_json({"event": "mark", "streamSid": sid, "mark": {"name": mark}})
                return True
            finally:
                closer = getattr(iterator, "aclose", None)
                if closer is not None:
                    await closer()

    @staticmethod
    def _media(sid: str, ulaw: bytes) -> dict[str, Any]:
        return {"event": "media", "streamSid": sid, "media": {"payload": base64.b64encode(ulaw).decode("ascii")}}

    async def clear(self) -> None:
        """Barge-in: abort what is being sent and empty what Twilio has buffered."""
        self._generation += 1
        if not self.closed and self.stream_sid is not None:
            await self._send_json({"event": "clear", "streamSid": self.stream_sid})

    async def close(self) -> None:
        self.closed = True
        self._generation += 1


# ---------------------------------------------------------------------------------------------------- provider
@dataclass
class _Pending:
    call: IncomingCall
    at: float


@dataclass(eq=False)
class _Call:
    call_id: str
    call_sid: str
    called_number: str | None
    token: str
    session: TwilioMediaSession | None = None
    media_task: asyncio.Task[None] | None = None
    media_ready: asyncio.Event = field(default_factory=asyncio.Event)
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    playbacks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    marks: dict[str, asyncio.Event] = field(default_factory=dict)
    hangup_requested: bool = False
    transfer: str = "none"


@dataclass(frozen=True)
class VoiceResult:
    """What the voice webhook answers: the TwiML and the Sparta call it created (``None`` when it rejected the call)."""

    twiml: str
    call_id: str | None


class TwilioTelephonyProvider:
    """:class:`~sparta.telephony.base.TelephonyProvider` for Twilio. See the module docstring."""

    name = PROVIDER
    kind = ProviderKind.OTHER  # the stored provider kind stays the generic one: no change to the API contract

    def __init__(
        self,
        settings: Settings,
        *,
        tts: TextToSpeechProvider,
        client: TwilioClientPort | None = None,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
        http: httpx.AsyncClient | None = None,
        media_attach_timeout_s: float = 10.0,
    ) -> None:
        self._settings = settings
        self._tts = tts
        self._client = client
        self._clock = clock or SystemClock()
        self._metrics = metrics or Metrics()
        self._http = http
        self._media_attach_timeout_s = media_attach_timeout_s
        self._sink: TelephonyEventSink | None = None
        self._calls: dict[str, _Call] = {}
        self._ended: OrderedDict[str, None] = OrderedDict()
        self._pending: OrderedDict[str, _Pending] = OrderedDict()
        self._incoming: OrderedDict[str, asyncio.Task[VoiceResult]] = OrderedDict()
        self._counter = itertools.count(1)
        breaker = CircuitBreaker(clock=self._clock)
        self._callers = {
            stage: ResilientCaller(
                PROVIDER,
                stage,
                timeout_s=settings.provider_timeout_s,
                max_retries=0 if stage == "transfer" else settings.provider_max_retries,
                breaker=breaker,
                clock=self._clock,
                metrics=self._metrics,
            )
            for stage in ("hangup", "transfer")
        }
        self._breaker = breaker
        self.live_configured = bool(
            settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_callback_base_url
        )
        self.capabilities = TelephonyCapabilities(
            can_answer=True,
            can_play_audio=not tts.meta.simulated,
            can_stop_playback=True,  # a `clear` message
            can_transfer=True,  # Call-resource update with <Dial> (live behaviour UNVERIFIED)
            can_hangup=True,
            receives_caller_audio=True,
            two_way_audio=False,  # per call: see capabilities_for_call()
            dtmf=True,
            simulated=False,
            live_calls_supported=self.live_configured,
            note=NOTE,
        )

    # --------------------------------------------------------------------------------------- wiring
    def bind(self, sink: TelephonyEventSink) -> None:
        self._sink = sink

    def _require_sink(self) -> TelephonyEventSink:
        if self._sink is None:
            raise ProviderUnavailable(PROVIDER, "events", "the provider is not bound to an event sink")
        return self._sink

    def _auth_token(self) -> str:
        token = self._settings.twilio_auth_token
        if token is None:
            raise ProviderUnavailable(PROVIDER, "twilio", "Twilio is not configured")
        return token.get_secret_value()

    def _get_client(self) -> TwilioClientPort:
        if self._client is None:
            sid, token = self._settings.twilio_account_sid, self._settings.twilio_auth_token
            if not sid or token is None or self._http is None:
                raise ProviderUnavailable(PROVIDER, "twilio", "Twilio is not configured")
            self._client = HttpTwilioClient(sid, token, self._http, timeout_s=self._settings.provider_timeout_s)
        return self._client

    def _base(self) -> str:
        base = https_origin(self._settings.twilio_callback_base_url)
        if base is None:
            raise ProviderUnavailable(PROVIDER, "twilio", "SPARTA_TWILIO_CALLBACK_BASE_URL must be an https URL")
        return base

    def webhook_url(self, path: str) -> str:
        """The public URL Twilio was told to call (and signed): the configured origin plus ``path``."""
        return f"{self._base()}{path}"

    def media_urls(self, call_id: str) -> tuple[str, list[str]]:
        """``(wss URL for the TwiML, every URL form the upgrade request's signature may cover)``."""
        if not _CALL_ID.fullmatch(call_id):
            raise ProviderUnavailable(PROVIDER, "twilio", "invalid call id")
        base = self._base()
        https_url = f"{base}{MEDIA_PATH}/{call_id}"
        wss_url = "wss://" + https_url.removeprefix("https://")
        return wss_url, url_variants(wss_url, schemes=("https",))

    def verify_webhook(self, path: str, header: str | None, fields: Sequence[tuple[str, str]]) -> bool:
        urls = url_variants(self.webhook_url(path))
        return verify_twilio_signature(self._auth_token(), header, urls, fields)

    def verify_media_upgrade(self, call_id: str, header: str | None) -> bool:
        if not self._settings.twilio_verify_media_signature:
            return True  # the per-call token in the start message still authenticates the socket
        _, urls = self.media_urls(call_id)
        return verify_twilio_signature(self._auth_token(), header, urls, [])

    # ------------------------------------------------------------------------------------ capabilities
    def capabilities_for_call(self, call_id: str) -> TelephonyCapabilities:
        state = self._calls.get(call_id)
        attached = (
            state is not None and state.session is not None and state.session.authenticated and not state.session.closed
        )
        return dataclasses.replace(self.capabilities, two_way_audio=attached)

    async def status(self) -> ProviderStatus:
        tts_ready = not self._tts.meta.simulated
        detail = NOTE if tts_ready else "Text-to-speech is simulated, so live calls would be silent. " + NOTE
        return ProviderStatus(
            provider=self.name,
            kind=self.kind,
            healthy=self.live_configured and tts_ready and self._breaker.state is not BreakerState.OPEN,
            simulated=False,
            detail=detail,
            extra={
                "live_calls_supported": str(self.live_configured).lower(),
                "active_calls": str(len(self._calls)),
                "media_sessions": str(sum(1 for c in self._calls.values() if c.session is not None)),
                "circuit": self._breaker.state.value,
            },
        )

    # -------------------------------------------------------------------------------------- incoming
    async def handle_voice_webhook(self, fields: Mapping[str, str]) -> VoiceResult:
        """Handle one verified voice-webhook request. Idempotent per ``CallSid`` (Twilio retries on timeouts)."""
        sink = self._require_sink()
        call_sid = fields.get("CallSid", "")
        if not CALL_SID.fullmatch(call_sid):
            raise ProviderRejected(PROVIDER, "incoming", "invalid call identifier")
        task = self._incoming.get(call_sid)
        if task is None:
            task = asyncio.ensure_future(self._accept_incoming(fields, call_sid, sink))
            self._incoming[call_sid] = task
            while len(self._incoming) > MAX_TRACKED:
                self._incoming.popitem(last=False)
        try:
            return await asyncio.shield(task)
        except BaseException:
            if task.done():
                self._incoming.pop(call_sid, None)  # a failed acceptance may be retried by a redelivery
            raise

    async def _accept_incoming(self, fields: Mapping[str, str], call_sid: str, sink: TelephonyEventSink) -> VoiceResult:
        now = self._clock.monotonic()
        while self._pending and (
            len(self._pending) >= MAX_TRACKED or next(iter(self._pending.values())).at < now - PENDING_TTL_S
        ):
            self._pending.popitem(last=False)
        caller, called = fields.get("From") or None, fields.get("To") or None
        incoming = IncomingCall(
            provider=PROVIDER,
            provider_call_id=call_sid,
            caller_number=caller if caller and _E164.fullmatch(caller) else None,
            called_number=called if called and _E164.fullmatch(called) else None,
            display_name=None,  # a caller-name lookup is a paid add-on and not needed
            correlation_id=call_sid,
            received_at=self._clock.now(),
        )
        self._pending[call_sid] = _Pending(incoming, now)
        try:
            call_id = await sink.incoming_call(incoming)  # a limit or policy rejection is raised to the route
        finally:
            self._pending.pop(call_sid, None)
        state = self._calls.get(call_id)
        if state is None or call_id in self._ended:
            return VoiceResult(reject_twiml("rejected"), call_id)  # a blocked caller: ended before it was answered
        return VoiceResult(self._stream_twiml(state), call_id)

    def redeliver(self, call_sid: str) -> str:
        """The TwiML for a repeated voice webhook of a call that was already accepted."""
        for state in self._calls.values():
            if state.call_sid == call_sid:
                return self._stream_twiml(state)
        return reject_twiml("rejected")

    def _stream_twiml(self, state: _Call) -> str:
        wss_url, _ = self.media_urls(state.call_id)
        return stream_twiml(wss_url, state.token)

    # --------------------------------------------------------------------------------------- answer
    async def answer(self, call: ProviderCallRef) -> None:
        """The TwiML response is the answer; this registers the call so the media socket and speech can attach."""
        if call.call_id in self._ended:
            raise ProviderRejected(PROVIDER, "answer", "the call has already ended")
        if call.call_id in self._calls:
            return
        pending = self._pending.get(call.provider_call_id or "")
        if pending is None:
            raise ProviderRejected(PROVIDER, "answer", "no incoming call for this id")
        self._calls[call.call_id] = _Call(
            call_id=call.call_id,
            call_sid=pending.call.provider_call_id,
            called_number=pending.call.called_number,
            token=stream_token(self._auth_token(), call.call_id),
        )

    # ------------------------------------------------------------------------------------- playback
    async def play(self, call: ProviderCallRef, plan: SpeechPlan) -> Playback:
        state = self._calls.get(call.call_id)
        if state is None:
            raise ProviderRejected(PROVIDER, "play", "the call is not active")
        if self._tts.meta.simulated:
            raise ProviderRejected(
                PROVIDER, "play", "a real text-to-speech provider is required to speak on a live call"
            )
        playback_id = f"pb_{call.call_id[-8:]}_{next(self._counter)}"
        state.marks[playback_id] = asyncio.Event()  # registered now so a takeover can wait for this line to be heard
        state.playbacks[playback_id] = asyncio.ensure_future(self._run_playback(state, playback_id, plan))
        duration = plan.est_duration_ms or estimate_duration_ms(plan.text, plan.locale, plan.rate)
        return Playback(playback_id=playback_id, call_id=call.call_id, duration_ms=max(duration, 1), simulated=False)

    async def _run_playback(self, state: _Call, playback_id: str, plan: SpeechPlan) -> None:
        finished = False
        try:
            async with state.play_lock:  # one line at a time, in order
                session = await self._wait_for_media(state)
                request = SynthesisRequest(
                    text=plan.text,
                    locale=plan.locale,
                    voice_id=plan.voice_id,
                    rate=plan.rate,
                    style=plan.style,
                    output_format="mulaw_8k",
                    trace_id=playback_id,
                )
                echo = state.marks.setdefault(playback_id, asyncio.Event())
                started = self._clock.monotonic()
                sent = await session.send_audio_stream(self._ulaw(request, started), mark=playback_id)
                if sent:
                    estimate = (
                        plan.est_duration_ms or estimate_duration_ms(plan.text, plan.locale, plan.rate)
                    ) / 1000.0
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(echo.wait(), estimate + MARK_GRACE_S)
                    finished = echo.is_set() or not session.closed
            if not finished:
                await self._report_error(state.call_id, "play", "the media stream closed during playback")
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            await self._report_error(state.call_id, "play", exc.message)
        except Exception as exc:
            log.warning("playback failed", extra={"call_id": state.call_id, "error_type": type(exc).__name__})
            await self._report_error(state.call_id, "play", "playback failed")
        finally:
            state.playbacks.pop(playback_id, None)
            state.marks.pop(playback_id, None)
        if finished and self._sink is not None:
            try:
                await self._sink.playback_finished(state.call_id, playback_id)
            except Exception as exc:
                log.warning("playback completion failed", extra={"error_type": type(exc).__name__})

    async def _ulaw(self, request: SynthesisRequest, started: float) -> AsyncIterator[bytes]:
        first = True
        async for chunk in self._tts.synthesize_stream(request):
            if not chunk.data:
                continue
            if first:
                first = False
                self._metrics.observe(
                    PROVIDER_LATENCY_MS,
                    (self._clock.monotonic() - started) * 1000.0,
                    provider=PROVIDER,
                    stage="tts_first_audio",
                )
            yield chunk.data

    async def _wait_for_media(self, state: _Call) -> TwilioMediaSession:
        session = state.session
        if session is None or session.closed or not session.authenticated:
            try:
                await asyncio.wait_for(state.media_ready.wait(), timeout=self._media_attach_timeout_s)
            except TimeoutError:
                raise ProviderError(PROVIDER, "play", "the media stream is not connected") from None
            session = state.session
        if session is None or not session.authenticated:
            raise ProviderError(PROVIDER, "play", "the media stream is not connected")
        return session

    async def stop_playback(self, call: ProviderCallRef, playback_id: str) -> None:
        state = self._calls.get(call.call_id)
        if state is None:
            return
        task = state.playbacks.get(playback_id)
        if task is not None:
            task.cancel()  # first: a cancelled playback must never report "finished"
        if state.session is not None:
            try:
                await state.session.clear()  # also empties what Twilio has already buffered
            except ProviderError as exc:
                log.debug("clear could not be sent: %s", exc.message)
        with contextlib.suppress(ProviderError):
            await self._tts.stop_playback(playback_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
            state.playbacks.pop(playback_id, None)  # a task cancelled before it started never runs its own cleanup
            state.marks.pop(playback_id, None)

    # --------------------------------------------------------------------------------- end of a call
    async def hangup(self, call: ProviderCallRef, reason: str) -> None:
        """End the call. Idempotent: the service calls this at the end of every call, including remote hang-ups."""
        state = self._calls.get(call.call_id)
        if state is None:
            self._tombstone(call.call_id)
            if call.provider_call_id:
                self._pending.pop(call.provider_call_id, None)
            return
        if state.hangup_requested:
            return
        state.hangup_requested = True
        call_sid = state.call_sid
        await self._finish_call(state)
        client = self._get_client()
        try:
            await self._callers["hangup"].call(lambda: client.hang_up(call_sid), trace_id=call.call_id)
        except ProviderError as exc:
            if exc.status not in (400, 404):  # the call is already over
                raise

    def _tombstone(self, call_id: str) -> None:
        self._ended[call_id] = None
        while len(self._ended) > MAX_TRACKED:
            self._ended.popitem(last=False)

    async def _finish_call(self, state: _Call) -> None:
        self._calls.pop(state.call_id, None)
        self._tombstone(state.call_id)
        current = asyncio.current_task()
        others = [t for t in state.playbacks.values() if t is not current]
        if state.media_task is not None and state.media_task is not current:
            others.append(state.media_task)
        for task in others:
            task.cancel()
        if others:
            await asyncio.gather(*others, return_exceptions=True)
        if state.session is not None:
            await state.session.close()

    async def _remote_hangup(self, state: _Call, reason: str) -> None:
        await self._finish_call(state)
        if self._sink is not None:
            await self._sink.remote_hangup(state.call_id, reason)

    async def _report_error(self, call_id: str, stage: str, message: str) -> None:
        if self._sink is None:
            return
        try:
            await self._sink.provider_error(call_id, stage, message)
        except Exception as exc:
            log.warning("provider error could not be reported", extra={"error_type": type(exc).__name__})

    # ---------------------------------------------------------------------------------------- transfer
    async def transfer(self, call: ProviderCallRef, destination: str | None) -> TransferResult:
        """Redirect the live call to ``<Dial>`` the owner's phone. The Stream ends and the caller hears the owner."""
        if not destination or not _E164.fullmatch(destination):
            return TransferResult(False, False, "No valid phone number is set to take this call over.")
        state = self._calls.get(call.call_id)
        if state is None:
            return TransferResult(False, False, "The call is not connected, so it cannot be transferred.")
        caller_id = self._settings.twilio_caller_id or state.called_number
        if not caller_id or not _E164.fullmatch(caller_id):
            return TransferResult(
                False, False, "No Twilio number is known to present as the caller id of the transfer."
            )
        client = self._get_client()
        twiml = dial_twiml(destination, caller_id)
        call_sid = state.call_sid
        await self._let_speech_finish(state)
        try:
            await self._callers["transfer"].call(lambda: client.redirect(call_sid, twiml), trace_id=call.call_id)
        except ProviderError as exc:
            return TransferResult(False, False, f"The transfer was not accepted ({exc.message}).")
        state.transfer = "requested"
        return TransferResult(True, False, "Transfer requested: Twilio is dialling your phone.")

    async def _let_speech_finish(self, state: _Call) -> None:
        """The redirect replaces the stream, so a line still being played (the announcement of the transfer) would be
        cut off: wait, a bounded time, until Twilio reports it played. The call service holds its call lock here but
        the mark echoes arrive on the media socket, so nothing waits on that lock."""
        session = state.session
        if session is None or not session.authenticated or session.closed:
            return
        echoes = [event.wait() for event in list(state.marks.values())]
        if echoes:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.gather(*echoes), TRANSFER_SPEECH_WAIT_S)

    # ------------------------------------------------------------------------------------ media socket
    async def attach_media(self, call_id: str, websocket: WebSocketLike) -> None:
        """Run the media session for ``call_id`` until its WebSocket closes. The route verified the upgrade first."""
        sink = self._require_sink()
        state = self._calls.get(call_id)
        if state is None:
            raise ProviderRejected(PROVIDER, "media", "unknown or ended call")
        if state.media_task is not None and not state.media_task.done():
            state.media_task.cancel()
        if state.session is not None:
            await state.session.close()

        def on_mark(name: str) -> None:
            event = state.marks.get(name)
            if event is not None:
                event.set()

        async def on_stop() -> None:
            await self._remote_hangup(state, "disconnected")

        session = TwilioMediaSession(
            call_id,
            websocket,
            sink,
            expected_token=state.token,
            expected_call_sid=state.call_sid,
            on_mark=on_mark,
            on_stop=on_stop,
            metrics=self._metrics,
        )
        task = asyncio.ensure_future(session.run())
        state.session, state.media_task = session, task
        watcher = asyncio.ensure_future(self._announce_ready(state, session))
        try:
            await asyncio.wait({task})
        finally:
            watcher.cancel()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await session.close()
            ended_here = state.session is session
            if ended_here:
                state.session = None
                state.media_ready.clear()
        if (
            ended_here
            and session.authenticated
            and call_id in self._calls
            and not session.stats["stop"]
            and not state.hangup_requested
        ):
            # Twilio closed (or lost) an authenticated socket without a stop message: with nothing after <Connect>
            # the call is over. A socket that never authenticated (a stranger's) must not end anyone's call.
            await self._remote_hangup(state, "disconnected")

    async def _announce_ready(self, state: _Call, session: TwilioMediaSession) -> None:
        await session.ready.wait()
        if state.session is session:
            state.media_ready.set()

    # ---------------------------------------------------------------------------------- status webhook
    async def handle_status_callback(self, fields: Mapping[str, str]) -> None:
        """A verified call-status webhook: a terminal status ends the call here if the stream did not."""
        status = fields.get("CallStatus", "")
        call_sid = fields.get("CallSid", "")
        if status not in {"completed", "busy", "no-answer", "failed", "canceled"} or not CALL_SID.fullmatch(call_sid):
            return
        for state in list(self._calls.values()):
            if state.call_sid == call_sid:
                await self._remote_hangup(state, "disconnected")
                break

    # -------------------------------------------------------------------------------------- lifecycle
    async def aclose(self) -> None:
        for state in list(self._calls.values()):
            await self._finish_call(state)
        for task in list(self._incoming.values()):
            if not task.done():
                task.cancel()


def build_twilio_provider(
    settings: Settings,
    *,
    tts: TextToSpeechProvider,
    http: httpx.AsyncClient | None = None,
    clock: Clock | None = None,
    metrics: Metrics | None = None,
) -> TwilioTelephonyProvider:
    return TwilioTelephonyProvider(settings, tts=tts, clock=clock, metrics=metrics, http=http)
