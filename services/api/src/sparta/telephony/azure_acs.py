"""Azure Communication Services (Call Automation) telephony adapter.

**Live ACS behaviour is UNVERIFIED.** No ACS resource exists in the development environment and no live PSTN call was
made: everything here is exercised only against fakes of the SDK client and of the media WebSocket. Facts used come
from ``docs/research/acs-android-verification.md``, in particular:

* ACS cannot acquire +91 (India) numbers directly, and standalone ACS telephony is scheduled to retire on 2028-09-30:
  for an Indian owner this adapter needs a Teams Phone Extensibility / Operator Connect route or another carrier.
* The media WebSocket key casing is documented inconsistently (the Python sample is PascalCase, the JavaScript
  serializer emits lower-case keys), so server -> ACS frames support both (``casing``) and the wire format must be
  confirmed in an integration test.
* The audience of ACS callback tokens (and the ``RSA256`` vs ``RS256`` algorithm name) are UNVERIFIED; see
  :mod:`sparta.telephony.webhooks`.

Shape of the integration:

* ``handle_incoming`` takes a verified ``Microsoft.Communication.IncomingCall`` Event Grid event, creates the Sparta call
  through the event sink and answers it with bidirectional PCM16 16 kHz media streaming over a WebSocket.
* ``attach_media`` runs one :class:`AcsMediaSession` per call: caller audio and DTMF flow to the sink, and speech from the
  TTS provider flows back as paced 20 ms frames (``stop_playback`` sends ``StopAudio`` for barge-in).
* ``handle_callback_event`` maps Call Automation callbacks to sink calls, idempotently by event id.

Webhook authentication (Entra bearer for Event Grid, JWT for callbacks and the media socket) is the router's job; the
``*_verifier`` helpers hand it ready-made verifiers.
"""

import asyncio
import base64
import binascii
import contextlib
import dataclasses
import itertools
import json
import logging
import re
from collections import Counter, OrderedDict
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import httpx

from sparta.clock import Clock, SystemClock
from sparta.config import ConfigurationError, Settings
from sparta.domain.enums import ProviderKind
from sparta.domain.models import SpeechPlan
from sparta.observability.metrics import PROVIDER_ERRORS, Metrics
from sparta.providers.azure_common import https_origin
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
from sparta.telephony.webhooks import (
    ACS_MEDIA_MAX_LIFETIME_S,
    EventGridEvent,
    JwtVerifier,
    acs_callback_verifier,
    incoming_call_from_event,
)
from sparta.telephony.webhooks import event_grid_verifier as build_event_grid_verifier

log = logging.getLogger("sparta.telephony.azure_acs")

PROVIDER = "azure"
FRAME_MS = 20
FRAME_S = FRAME_MS / 1000.0
DEFAULT_SAMPLE_RATE = 16000
OutputFormatName = Literal["pcm16_8k", "pcm16_16k", "pcm16_24k"]
OUTPUT_FORMAT_BY_RATE: dict[int, OutputFormatName] = {8000: "pcm16_8k", 16000: "pcm16_16k", 24000: "pcm16_24k"}
MAX_MESSAGE_CHARS = 65_536
MAX_FRAME_BYTES = 32_768
MAX_INVALID_FRAMES = 500
LEAD_MS = 100  # audio kept queued at ACS ahead of real time, to ride out scheduling jitter
CALLBACK_PATH = "/api/v1/webhooks/acs/callbacks"
MEDIA_PATH = "/api/v1/media/acs"
MAX_CALLBACK_EVENTS = 50
MAX_TRACKED = 1024
PENDING_TTL_S = 120.0  # the ring window is about 30 s: an unanswered incoming-call context is useless after that

NOTE = (
    "Azure Communication Services Call Automation with bidirectional media streaming. Live behaviour is UNVERIFIED: no "
    "live PSTN call was tested. ACS cannot acquire +91 (India) numbers directly, so an Indian owner needs a Teams Phone "
    "Extensibility / Operator Connect route or another carrier (see docs/research/acs-android-verification.md)."
)

_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DTMF = re.compile(r"[0-9A-Da-d*#]")
_E164 = re.compile(r"\+[1-9][0-9]{6,14}")

Casing = Literal["pascal", "camel"]


@dataclass(frozen=True)
class _Wire:
    kind: str
    audio: str
    data: str
    stop: str


# Key casing of server -> ACS frames. The documented Python sample is PascalCase; the JS serializer is camelCase.
_WIRE: dict[str, _Wire] = {
    "pascal": _Wire("Kind", "AudioData", "Data", "StopAudio"),
    "camel": _Wire("kind", "audioData", "data", "stopAudio"),
}


# ------------------------------------------------------------------------------------------ SDK client port
@runtime_checkable
class AcsClientPort(Protocol):
    """The three Call Automation operations Sparta needs. ``provider_call_id`` is the call-connection id."""

    async def answer_call(self, incoming_call_context: str, callback_url: str, media_streaming_ws_url: str) -> str:
        """Answer an incoming call with media streaming enabled; returns the call-connection id."""
        ...

    async def hang_up(self, provider_call_id: str, for_everyone: bool) -> None: ...

    async def transfer_to_phone(self, provider_call_id: str, destination: str) -> None: ...


def _sdk_error(stage: str, exc: Exception) -> ProviderError:
    """A sanitised error for an SDK exception: only an HTTP status is ever kept, never the message or its URL."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in (401, 403):
            return ProviderRejected(PROVIDER, stage, "authentication failed", status=status)
        if status in (400, 422):
            return ProviderRejected(PROVIDER, stage, f"request rejected (HTTP {status})", status=status)
        if status in (404, 409):
            return ProviderError(PROVIDER, stage, "the call no longer exists or cannot do that now", status=status)
        if status == 429 or status >= 500:
            message = "rate limited" if status == 429 else f"service unavailable (HTTP {status})"
            return ProviderError(PROVIDER, stage, message, retryable=True, status=status)
        return ProviderError(PROVIDER, stage, f"unexpected response (HTTP {status})", status=status)
    try:
        from azure.core.exceptions import ServiceRequestError, ServiceResponseError

        if isinstance(exc, ServiceRequestError | ServiceResponseError):
            return ProviderError(PROVIDER, stage, "network error", retryable=True)
    except ImportError:  # pragma: no cover - azure-core always ships with the SDK
        pass
    return ProviderError(PROVIDER, stage, "request failed")


class SdkAcsClient:
    """:class:`AcsClientPort` over ``azure-communication-callautomation`` (imported lazily; the blocking SDK calls run
    in worker threads). A timed-out call cannot be interrupted in its thread, so retries of ``answer_call`` are bounded
    by the caller. Not exercised against a live service.
    """

    def __init__(self, connection_string: str, *, source_caller_id: str | None = None) -> None:
        from azure.communication.callautomation import CallAutomationClient

        self._client = CallAutomationClient.from_connection_string(connection_string)
        self._source_caller_id = source_caller_id  # an ACS-owned number: UNVERIFIED whether PSTN transfer needs it

    async def answer_call(self, incoming_call_context: str, callback_url: str, media_streaming_ws_url: str) -> str:
        return await asyncio.to_thread(self._answer, incoming_call_context, callback_url, media_streaming_ws_url)

    def _answer(self, incoming_call_context: str, callback_url: str, ws_url: str) -> str:
        from azure.communication.callautomation import (
            AudioFormat,
            MediaStreamingAudioChannelType,
            MediaStreamingContentType,
            MediaStreamingOptions,
            StreamingTransportType,
        )

        options = MediaStreamingOptions(
            transport_url=ws_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM16_K_MONO,
            enable_dtmf_tones=True,
        )
        try:
            properties = self._client.answer_call(incoming_call_context, callback_url, media_streaming=options)
        except Exception as exc:
            raise _sdk_error("answer", exc) from None
        connection_id = getattr(properties, "call_connection_id", None)
        if not isinstance(connection_id, str) or not connection_id:
            raise ProviderError(PROVIDER, "answer", "ACS did not return a call connection id")
        return connection_id

    async def hang_up(self, provider_call_id: str, for_everyone: bool) -> None:
        await asyncio.to_thread(self._hang_up, provider_call_id, for_everyone)

    def _hang_up(self, connection_id: str, for_everyone: bool) -> None:
        try:
            self._client.get_call_connection(connection_id).hang_up(is_for_everyone=for_everyone)
        except Exception as exc:
            raise _sdk_error("hangup", exc) from None

    async def transfer_to_phone(self, provider_call_id: str, destination: str) -> None:
        await asyncio.to_thread(self._transfer, provider_call_id, destination)

    def _transfer(self, connection_id: str, destination: str) -> None:
        from azure.communication.callautomation import PhoneNumberIdentifier

        caller_id = PhoneNumberIdentifier(self._source_caller_id) if self._source_caller_id else None
        try:
            self._client.get_call_connection(connection_id).transfer_call_to_participant(
                target_participant=PhoneNumberIdentifier(destination), source_caller_id_number=caller_id
            )
        except Exception as exc:
            raise _sdk_error("transfer", exc) from None

    async def aclose(self) -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._client.close)


# --------------------------------------------------------------------------------------- media WebSocket
@runtime_checkable
class WebSocketLike(Protocol):
    """The two methods of a text WebSocket (a Starlette ``WebSocket`` satisfies this)."""

    async def receive_text(self) -> str: ...

    async def send_text(self, data: str) -> None: ...


def _lowered(value: object) -> dict[str, Any] | None:
    return {str(k).lower(): v for k, v in value.items()} if isinstance(value, dict) else None


class AcsMediaSession:
    """One call's media WebSocket: parses ACS -> server frames and sends paced server -> ACS audio.

    Frames in (key casing is not trusted: matched case-insensitively)::

        {"kind":"AudioMetadata","audioMetadata":{"subscriptionId","encoding","sampleRate","channels","length"}}
        {"kind":"AudioData","audioData":{"timestamp","participantRawID","data":"<base64>","silent":false}}
        {"kind":"DtmfData","dtmfData":{"data":"3"}}

    Frames out (``casing="pascal"``, the documented Python sample)::

        {"Kind":"AudioData","AudioData":{"Data":"<base64>"},"StopAudio":null}
        {"Kind":"StopAudio","AudioData":null,"StopAudio":{}}

    Malformed, oversized or unexpected input is counted and dropped, never raised. Silent frames are forwarded (their
    timing matters to the VAD). The session ends after ``max_invalid_frames`` invalid frames.
    """

    def __init__(
        self,
        call_id: str,
        websocket: WebSocketLike,
        sink: TelephonyEventSink,
        *,
        casing: Casing = "pascal",
        clock: Clock | None = None,
        metrics: Metrics | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        lead_ms: int = LEAD_MS,
        max_message_chars: int = MAX_MESSAGE_CHARS,
        max_frame_bytes: int = MAX_FRAME_BYTES,
        max_invalid_frames: int = MAX_INVALID_FRAMES,
    ) -> None:
        if casing not in _WIRE:
            raise ValueError("casing must be 'pascal' or 'camel'")
        self._call_id = call_id
        self._ws = websocket
        self._sink = sink
        self._wire = _WIRE[casing]
        self._clock = clock or SystemClock()
        self._metrics = metrics or Metrics()
        self._lead_s = lead_ms / 1000.0
        self._max_message_chars = max_message_chars
        self._max_frame_bytes = max_frame_bytes
        self._max_invalid_frames = max_invalid_frames
        self.sample_rate = sample_rate
        self.closed = False
        self.stats: Counter[str] = Counter()
        self._invalid = 0
        self._format_ok = True
        self._generation = 0
        self._send_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    @property
    def frame_bytes(self) -> int:
        """Bytes in one 20 ms PCM16 mono frame (640 at 16 kHz)."""
        return self.sample_rate * FRAME_MS // 1000 * 2

    # ------------------------------------------------------------------------------ ACS -> server
    async def run(self) -> None:
        """Receive until the socket closes (any ``receive_text`` failure), the session is closed or abused."""
        try:
            while not self.closed:
                try:
                    text = await self._ws.receive_text()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    break  # disconnect/close: framework-specific exception types are deliberately not imported
                await self.handle_message(text)
        finally:
            self.closed = True

    async def handle_message(self, text: str) -> None:
        """Handle one text frame from ACS. Never raises on bad input."""
        try:
            await self._dispatch(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._drop("handler_error", invalid=False)
            log.warning(
                "media frame handling failed", extra={"call_id": self._call_id, "error_type": type(exc).__name__}
            )

    def _drop(self, reason: str, *, invalid: bool = True) -> None:
        self.stats[reason] += 1
        self._metrics.inc(PROVIDER_ERRORS, provider=PROVIDER, stage="media", kind=reason)
        if invalid:
            self._invalid += 1
            if self._invalid >= self._max_invalid_frames:
                self.closed = True

    async def _dispatch(self, text: str) -> None:
        if not isinstance(text, str) or len(text) > self._max_message_chars:
            self._drop("too_large")
            return
        try:
            frame = json.loads(text)
        except (ValueError, RecursionError):
            self._drop("malformed")
            return
        fields = _lowered(frame)
        kind = fields.get("kind") if fields else None
        if fields is None or not isinstance(kind, str):
            self._drop("malformed")
            return
        match kind.lower():
            case "audiometadata":
                self._on_metadata(_lowered(fields.get("audiometadata")))
            case "audiodata":
                await self._on_audio(_lowered(fields.get("audiodata")))
            case "dtmfdata":
                await self._on_dtmf(_lowered(fields.get("dtmfdata")))
            case _:
                self.stats["ignored_kind"] += 1  # e.g. transcription frames: not requested, safely ignored

    def _on_metadata(self, data: dict[str, Any] | None) -> None:
        rate = data.get("samplerate") if data else None
        channels = data.get("channels") if data else None
        encoding = data.get("encoding") if data else None
        self._format_ok = (
            type(rate) is int
            and rate in OUTPUT_FORMAT_BY_RATE
            and type(channels) is int
            and channels == 1
            and isinstance(encoding, str)
            and encoding.upper().startswith("PCM")
        )
        if self._format_ok and isinstance(rate, int):
            self.sample_rate = rate
            self.stats["metadata"] += 1
        else:
            self._drop("bad_format")

    async def _on_audio(self, data: dict[str, Any] | None) -> None:
        if data is None:
            self._drop("bad_audio")
            return
        if not self._format_ok:
            self._drop("bad_format")
            return
        raw = data.get("data")
        if raw in (None, ""):
            if data.get("silent") is not True:
                self._drop("bad_audio")
                return
            pcm = bytes(self.frame_bytes)  # a silent frame without a payload still advances the timeline
        else:
            if not isinstance(raw, str) or len(raw) > self._max_frame_bytes * 4 // 3 + 8:
                self._drop("too_large")
                return
            try:
                pcm = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                self._drop("bad_audio")
                return
            if not pcm or len(pcm) % 2 or len(pcm) > self._max_frame_bytes:
                self._drop("bad_audio")
                return
        self.stats["audio_frames"] += 1
        await self._sink.caller_audio(self._call_id, pcm, self.sample_rate)

    async def _on_dtmf(self, data: dict[str, Any] | None) -> None:
        digit = data.get("data") if data else None
        if not isinstance(digit, str) or not _DTMF.fullmatch(digit):
            self._drop("bad_dtmf")
            return
        self.stats["dtmf"] += 1
        await self._sink.caller_dtmf(self._call_id, digit.upper())

    # ------------------------------------------------------------------------------ server -> ACS
    def _audio_frame(self, pcm: bytes) -> dict[str, Any]:
        wire = self._wire
        return {wire.kind: "AudioData", wire.audio: {wire.data: base64.b64encode(pcm).decode("ascii")}, wire.stop: None}

    def _stop_frame(self) -> dict[str, Any]:
        wire = self._wire
        return {wire.kind: "StopAudio", wire.audio: None, wire.stop: {}}

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

    async def send_audio(self, pcm16: bytes) -> None:
        """Send PCM16 mono audio (at :attr:`sample_rate`) to the caller as paced 20 ms frames."""

        async def once() -> AsyncIterator[bytes]:
            yield pcm16

        await self.send_audio_stream(once())

    async def send_audio_stream(self, chunks: AsyncIterable[bytes]) -> None:
        """Send streamed PCM16 audio in real time: at most ``lead_ms`` ahead of playback, padded to whole frames.

        Returns early (without error) when :meth:`stop_audio` or :meth:`close` is called meanwhile.
        """
        iterator = chunks.__aiter__()
        async with self._send_lock:
            generation = self._generation
            frame_bytes = self.frame_bytes
            buffer = bytearray()
            queued_until = self._clock.monotonic()
            try:
                async for chunk in iterator:
                    buffer += chunk
                    while len(buffer) >= frame_bytes:
                        frame = bytes(buffer[:frame_bytes])
                        del buffer[:frame_bytes]
                        queued_until = await self._send_paced(frame, queued_until, generation)
                        if queued_until < 0:
                            return
                if buffer:
                    await self._send_paced(bytes(buffer) + bytes(frame_bytes - len(buffer)), queued_until, generation)
            finally:
                closer = getattr(iterator, "aclose", None)
                if closer is not None:
                    await closer()

    async def _send_paced(self, frame: bytes, queued_until: float, generation: int) -> float:
        """Send one frame when pacing allows; returns the new queued-until time, or -1 if interrupted."""
        wait = queued_until - self._clock.monotonic() - (self._lead_s - FRAME_S)
        if wait > 1e-6:
            await self._clock.sleep(wait)
        if self.closed or generation != self._generation:
            return -1.0
        await self._send_json(self._audio_frame(frame))
        return max(queued_until, self._clock.monotonic()) + FRAME_S

    async def stop_audio(self) -> None:
        """Barge-in: abort any audio being sent and tell ACS to clear what it has queued (``StopAudio``)."""
        self._generation += 1
        if not self.closed:
            await self._send_json(self._stop_frame())

    async def close(self) -> None:
        self.closed = True
        self._generation += 1


# ------------------------------------------------------------------------------------------------ provider
@dataclass
class _Pending:
    context: str
    at: float


@dataclass(eq=False)
class _Call:
    call_id: str
    server_call_id: str | None
    context: str | None
    connection_id: str | None = None
    session: AcsMediaSession | None = None
    media_task: asyncio.Task[None] | None = None
    media_ready: asyncio.Event = field(default_factory=asyncio.Event)
    answer_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    playbacks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    seen_events: OrderedDict[str, None] = field(default_factory=OrderedDict)
    connected: bool = False
    hangup_requested: bool = False
    transfer: Literal["none", "requested", "accepted", "failed"] = "none"


def _result_suffix(data: dict[str, Any]) -> str:
    info = data.get("resultInformation")
    if isinstance(info, dict):
        parts = [str(v) for v in (info.get("code"), info.get("subCode")) if type(v) is int]
        if parts:
            return f" (code {'.'.join(parts)})"
    return ""


class AzureAcsTelephonyProvider:
    """:class:`TelephonyProvider` for Azure Communication Services. See the module docstring for what is UNVERIFIED."""

    name = PROVIDER
    kind = ProviderKind.AZURE

    def __init__(
        self,
        settings: Settings,
        *,
        tts: TextToSpeechProvider,
        client: AcsClientPort | None = None,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
        http: httpx.AsyncClient | None = None,
        media_casing: Casing = "pascal",
        media_attach_timeout_s: float = 10.0,
    ) -> None:
        self._settings = settings
        self._tts = tts
        self._client = client
        self._clock = clock or SystemClock()
        self._metrics = metrics or Metrics()
        self._http = http
        self._casing: Casing = media_casing
        self._media_attach_timeout_s = media_attach_timeout_s
        self._sink: TelephonyEventSink | None = None
        self._calls: dict[str, _Call] = {}
        self._ended: OrderedDict[str, None] = OrderedDict()  # call ids that were ended: they must never be (re)answered
        self._pending: OrderedDict[str, _Pending] = OrderedDict()
        self._incoming: OrderedDict[str, asyncio.Task[str]] = OrderedDict()
        self._counter = itertools.count(1)
        self._verifiers: dict[str, JwtVerifier] = {}
        breaker = CircuitBreaker(clock=self._clock)  # one breaker: if ACS is down, every operation is
        self._callers = {
            stage: ResilientCaller(
                PROVIDER,
                stage,
                timeout_s=settings.provider_timeout_s,
                max_retries=0 if stage == "transfer" else settings.provider_max_retries,  # a transfer is not idempotent
                breaker=breaker,
                clock=self._clock,
                metrics=self._metrics,
            )
            for stage in ("answer", "hangup", "transfer")
        }
        self._breaker = breaker
        self.live_configured = bool(
            settings.acs_connection_string and settings.acs_callback_base_url and settings.acs_resource_id
        )
        self.capabilities = TelephonyCapabilities(
            can_answer=True,
            can_play_audio=not tts.meta.simulated,  # speech is TTS PCM injected over the media socket
            can_stop_playback=True,  # StopAudio on the media socket
            can_transfer=True,  # transfer_call_to_participant to a phone number (PSTN behaviour UNVERIFIED)
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

    def _get_client(self) -> AcsClientPort:
        if self._client is None:
            connection_string = self._settings.acs_connection_string
            if not connection_string:
                raise ProviderUnavailable(PROVIDER, "acs", "Azure Communication Services is not configured")
            try:
                self._client = SdkAcsClient(connection_string.get_secret_value())
            except ImportError:
                raise ProviderUnavailable(
                    PROVIDER, "acs", "the azure-communication-callautomation package is not installed"
                ) from None
            except Exception:  # the SDK's message can quote the connection string: never let it through
                raise ProviderUnavailable(
                    PROVIDER, "acs", "the Azure Communication Services connection string is invalid"
                ) from None
        return self._client

    def _urls(self, call_id: str) -> tuple[str, str]:
        base = https_origin(self._settings.acs_callback_base_url)
        if base is None or not _CALL_ID.fullmatch(call_id):
            raise ProviderUnavailable(PROVIDER, "answer", "SPARTA_ACS_CALLBACK_BASE_URL must be an https URL")
        return f"{base}{CALLBACK_PATH}/{call_id}", f"wss://{base.removeprefix('https://')}{MEDIA_PATH}/{call_id}"

    def callback_verifier(self) -> JwtVerifier:
        """Verifier for Call Automation callbacks (cached). Needs the shared HTTP client and the ACS resource id."""
        return self._verifier("callback", lambda http: acs_callback_verifier(self._settings, http, clock=self._clock))

    def media_verifier(self) -> JwtVerifier:
        """Verifier for the media WebSocket upgrade (tokens are documented to last 24 h; audience UNVERIFIED)."""
        return self._verifier(
            "media",
            lambda http: acs_callback_verifier(
                self._settings, http, max_lifetime_s=ACS_MEDIA_MAX_LIFETIME_S, clock=self._clock
            ),
        )

    def event_grid_verifier(self) -> JwtVerifier:
        """Verifier for Event Grid secure-webhook deliveries (Entra bearer token)."""
        return self._verifier(
            "event_grid", lambda http: build_event_grid_verifier(self._settings, http, clock=self._clock)
        )

    def _verifier(self, name: str, build: Callable[[httpx.AsyncClient], JwtVerifier]) -> JwtVerifier:
        if name not in self._verifiers:
            if self._http is None:
                raise ConfigurationError(["an HTTP client is required to fetch signing keys for webhook verification"])
            self._verifiers[name] = build(self._http)
        return self._verifiers[name]

    # ------------------------------------------------------------------------------------ capabilities
    def capabilities_for_call(self, call_id: str) -> TelephonyCapabilities:
        """Provider capabilities with ``two_way_audio`` true only while this call has a live media socket."""
        state = self._calls.get(call_id)
        attached = state is not None and state.session is not None and not state.session.closed
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
    async def handle_incoming(self, event: EventGridEvent) -> str:
        """Handle one verified ``Microsoft.Communication.IncomingCall`` event; returns the Sparta call id.

        Idempotent: Event Grid may deliver an event more than once (even concurrently), and a call is created once per
        ``serverCallId``. Answer failures are reported to the sink, not raised, so Event Grid does not redeliver a call
        whose ring window has already passed. A call that Sparta ends before answering (for example a blocked caller)
        is left to ring out: reject/redirect are not part of the telephony port.
        """
        sink = self._require_sink()
        call = incoming_call_from_event(event, self._clock.now())
        key = call.provider_call_id
        task = self._incoming.get(key)
        if task is None:
            task = asyncio.ensure_future(self._accept_incoming(call, sink))
            self._incoming[key] = task
            while len(self._incoming) > MAX_TRACKED:
                self._incoming.popitem(last=False)
        try:
            return await asyncio.shield(task)
        except BaseException:
            if task.done():
                self._incoming.pop(key, None)  # a failed acceptance may be retried by a redelivery
            raise

    async def _accept_incoming(self, call: IncomingCall, sink: TelephonyEventSink) -> str:
        # The service answers (and starts speaking) from inside incoming_call(), before it returns the call id, so the
        # answer context must already be findable by serverCallId.
        now = self._clock.monotonic()
        while self._pending and (
            len(self._pending) >= MAX_TRACKED or next(iter(self._pending.values())).at < now - PENDING_TTL_S
        ):
            self._pending.popitem(last=False)
        self._pending[call.provider_call_id] = _Pending(call.context or "", now)
        call_id = await sink.incoming_call(call)
        if call_id in self._ended:
            return call_id  # the service ended it before it was answered
        state = self._state_for(call_id, call.provider_call_id, call.context)
        try:
            await self._ensure_answered(state)
        except ProviderError as exc:
            await self._report_error(call_id, "answer", exc.message)
            await self._remote_hangup(state, "answer_failed")
        return call_id

    def _state_for(self, call_id: str, server_call_id: str | None, context: str | None) -> _Call:
        state = self._calls.get(call_id)
        if state is None:
            state = self._calls[call_id] = _Call(call_id, server_call_id, context)
        return state

    # --------------------------------------------------------------------------------------- answer
    async def answer(self, call: ProviderCallRef) -> None:
        if call.call_id in self._ended:
            raise ProviderRejected(PROVIDER, "answer", "the call has already ended")
        state = self._calls.get(call.call_id)
        if state is None:
            pending = self._pending.get(call.provider_call_id) if call.provider_call_id else None
            context = call.provider_context or (pending.context if pending else None)
            if not context:
                raise ProviderRejected(PROVIDER, "answer", "no incoming call context for this call")
            state = self._state_for(call.call_id, call.provider_call_id, context)
        await self._ensure_answered(state)

    async def _ensure_answered(self, state: _Call) -> None:
        async with state.answer_lock:
            if state.connection_id is not None:
                return
            if not state.context:
                raise ProviderRejected(PROVIDER, "answer", "no incoming call context for this call")
            callback_url, ws_url = self._urls(state.call_id)
            client, context = self._get_client(), state.context
            state.connection_id = await self._callers["answer"].call(
                lambda: client.answer_call(context, callback_url, ws_url), trace_id=state.call_id
            )
            state.context = None  # the context is single-use: do not keep it around
            if state.server_call_id:
                self._pending.pop(state.server_call_id, None)

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
                    output_format=OUTPUT_FORMAT_BY_RATE[session.sample_rate],
                    trace_id=playback_id,
                )
                await session.send_audio_stream(self._pcm(request))
                finished = not session.closed
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
        if finished and self._sink is not None:
            try:
                await self._sink.playback_finished(state.call_id, playback_id)
            except Exception as exc:
                log.warning("playback completion failed", extra={"error_type": type(exc).__name__})

    async def _pcm(self, request: SynthesisRequest) -> AsyncIterator[bytes]:
        async for chunk in self._tts.synthesize_stream(request):
            if chunk.data:
                yield chunk.data

    async def _wait_for_media(self, state: _Call) -> AcsMediaSession:
        if state.session is None or state.session.closed:
            try:
                await asyncio.wait_for(state.media_ready.wait(), timeout=self._media_attach_timeout_s)
            except TimeoutError:
                raise ProviderError(PROVIDER, "play", "the media stream is not connected") from None
        if state.session is None:
            raise ProviderError(PROVIDER, "play", "the media stream is not connected")
        return state.session

    async def stop_playback(self, call: ProviderCallRef, playback_id: str) -> None:
        state = self._calls.get(call.call_id)
        if state is None:
            return
        task = state.playbacks.get(playback_id)
        if task is not None:
            task.cancel()  # first: a cancelled playback must never report "finished"
        if state.session is not None:
            try:
                await state.session.stop_audio()  # also clears audio already queued at ACS, even if nothing is running
            except ProviderError as exc:
                log.debug("StopAudio could not be sent: %s", exc.message)
        with contextlib.suppress(ProviderError):
            await self._tts.stop_playback(playback_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    # --------------------------------------------------------------------------------- end of a call
    async def hangup(self, call: ProviderCallRef, reason: str) -> None:
        """End the call. Idempotent: the service calls this at the end of every call, including remote hang-ups."""
        state = self._calls.get(call.call_id)
        if state is None:
            self._tombstone(call.call_id)  # ended before it was answered (or already finished): never answer it later
            if call.provider_call_id:
                self._pending.pop(call.provider_call_id, None)
            return
        if state.hangup_requested:
            return
        state.hangup_requested = True
        connection_id = state.connection_id
        await self._finish_call(state)
        if connection_id is None:
            return
        client = self._get_client()
        try:
            await self._callers["hangup"].call(lambda: client.hang_up(connection_id, True), trace_id=call.call_id)
        except ProviderError as exc:
            if exc.status not in (404, 409):  # 404/409: the call is already gone
                raise

    def _tombstone(self, call_id: str) -> None:
        self._ended[call_id] = None
        while len(self._ended) > MAX_TRACKED:
            self._ended.popitem(last=False)

    async def _finish_call(self, state: _Call) -> None:
        """Forget the call and stop everything running for it (safe to call from one of its own playback tasks)."""
        self._calls.pop(state.call_id, None)
        self._tombstone(state.call_id)
        if state.server_call_id:
            self._pending.pop(state.server_call_id, None)
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
        """Ask ACS to transfer the call to ``destination`` (E.164). Acceptance is only *requested*: the outcome arrives
        later as ``CallTransferAccepted`` / ``CallTransferFailed``. Real PSTN transfer is UNVERIFIED (including for +91).
        """
        if not destination or not _E164.fullmatch(destination):
            return TransferResult(False, False, "No valid phone number is set to take this call over.")
        state = self._calls.get(call.call_id)
        if state is None or state.connection_id is None:
            return TransferResult(False, False, "The call is not connected, so it cannot be transferred.")
        connection_id = state.connection_id
        try:
            client = self._get_client()
            await self._callers["transfer"].call(
                lambda: client.transfer_to_phone(connection_id, destination), trace_id=call.call_id
            )
        except ProviderError as exc:
            return TransferResult(False, False, f"The transfer was not accepted ({exc.message}).")
        state.transfer = "requested"
        return TransferResult(True, False, "Transfer requested; Azure reports the outcome asynchronously.")

    # ------------------------------------------------------------------------------------ media socket
    async def attach_media(self, call_id: str, websocket: WebSocketLike) -> None:
        """Run the media session for ``call_id`` until its WebSocket closes. The route must authenticate the upgrade
        first (see :meth:`media_verifier`). A reconnect replaces the previous socket.
        """
        sink = self._require_sink()
        state = self._calls.get(call_id)
        if state is None:
            raise ProviderRejected(PROVIDER, "media", "unknown or ended call")
        if state.media_task is not None and not state.media_task.done():
            state.media_task.cancel()
        if state.session is not None:
            await state.session.close()
        session = AcsMediaSession(
            call_id, websocket, sink, casing=self._casing, clock=self._clock, metrics=self._metrics
        )
        task = asyncio.ensure_future(session.run())
        state.session, state.media_task = session, task
        state.media_ready.set()
        try:
            await asyncio.wait({task})
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await session.close()
            if state.session is session:
                state.session = None
                state.media_ready.clear()

    # ---------------------------------------------------------------------------------------- callbacks
    async def handle_callback_event(self, call_id: str, payload: object) -> None:
        """Handle a verified Call Automation callback body (one event or a list of events). Idempotent by event id."""
        events = payload if isinstance(payload, list) else [payload]
        for raw in events[:MAX_CALLBACK_EVENTS]:
            if isinstance(raw, dict):
                await self._handle_one_callback(call_id, raw)

    async def _handle_one_callback(self, call_id: str, raw: dict[str, Any]) -> None:
        state = self._calls.get(call_id)
        if state is None:
            return  # a late or duplicate event for a call that is already finished
        event_id, event_type = raw.get("id"), raw.get("type")
        if isinstance(event_id, str) and event_id:
            if event_id in state.seen_events:
                return
            state.seen_events[event_id] = None
            while len(state.seen_events) > 256:
                state.seen_events.popitem(last=False)
        raw_data = raw.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        connection_id = data.get("callConnectionId")
        if isinstance(connection_id, str) and connection_id:
            if state.connection_id is None:
                state.connection_id = connection_id  # the callback can beat the answer_call response
            elif connection_id != state.connection_id:
                return  # an event for some other call connection
        name = event_type.rsplit(".", maxsplit=1)[-1] if isinstance(event_type, str) else ""
        suffix = _result_suffix(data)
        match name:
            case "CallConnected":
                state.connected = True
            case "CallDisconnected":
                await self._remote_hangup(state, "transferred" if state.transfer == "accepted" else "disconnected")
            case "AnswerFailed":
                await self._report_error(call_id, "answer", f"Azure could not answer the call{suffix}")
                await self._remote_hangup(state, "answer_failed")
            case "PlayFailed":
                await self._report_error(call_id, "play", f"Azure reported a media playback failure{suffix}")
            case "MediaStreamingFailed":
                await self._report_error(call_id, "media", f"Azure reported a media streaming failure{suffix}")
            case "CallTransferAccepted":
                state.transfer = "accepted"
            case "CallTransferFailed":
                state.transfer = "failed"
                await self._report_error(call_id, "transfer", f"Azure reported that the transfer failed{suffix}")
            case _:
                self._metrics.inc(PROVIDER_ERRORS, provider=PROVIDER, stage="callback", kind="ignored_event")

    # -------------------------------------------------------------------------------------- lifecycle
    async def aclose(self) -> None:
        for state in list(self._calls.values()):
            await self._finish_call(state)
        for task in list(self._incoming.values()):
            if not task.done():
                task.cancel()
        client_close = getattr(self._client, "aclose", None)
        if client_close is not None:
            await client_close()


def build_acs_provider(
    settings: Settings,
    *,
    tts: TextToSpeechProvider,
    http: httpx.AsyncClient | None = None,
    clock: Clock | None = None,
    metrics: Metrics | None = None,
) -> AzureAcsTelephonyProvider:
    """The configured ACS provider. The Call Automation SDK client is created lazily on first use, so building the
    provider needs neither the optional SDK nor valid credentials; ``http`` is the shared client used by the
    ``*_verifier`` helpers to fetch signing keys.
    """
    return AzureAcsTelephonyProvider(settings, tts=tts, clock=clock, metrics=metrics, http=http)
