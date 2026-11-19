"""Asterisk telephony adapter: LOCAL SIP calls, with no phone network involved.

A SIP client (Linphone, a desk phone, ``baresip``) registers to Asterisk and dials the Sparta extension. Asterisk's
dialplan asks this provider over authenticated HTTP whether to take the call, answers it, and connects its media to the
AudioSocket listener below. See ``docs/DECISIONS/ADR-ASTERISK-MEDIA-BRIDGE.md`` for why, and for the wire facts.

What this is **not**: a PSTN connection. A normal mobile or landline number cannot reach Sparta through it. That needs a
paid carrier, a number and a SIP trunk, none of which exist here.

The call flow, and what binds the media to the call:

1. ``POST /api/v1/webhooks/asterisk/incoming`` (HTTP Basic, constant-time secret check) creates the Sparta call through
   the event sink and returns ``ACCEPT <media id>`` (a random single-use UUID) or ``REJECT <reason>``.
2. The dialplan answers and runs ``AudioSocket(<media id>, <this host>:8090)``. Asterisk connects, announces the id first,
   and this provider claims it atomically: unknown, expired and already-claimed ids are refused, so a second connection
   can never replace the live stream.
3. Speech goes back as paced 20 ms frames; stopping is simply not sending. Caller DTMF is received but never interpreted.
4. Hang-up and takeover are the end of the socket. The dialplan then asks ``/next`` what to do (``HANGUP`` or
   ``DIAL <owner extension>``) and reports the end of the call to ``/ended``.
"""

import asyncio
import base64
import binascii
import contextlib
import dataclasses
import hmac
import itertools
import logging
import re
import secrets
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Mapping
from dataclasses import dataclass, field

from sparta.clock import Clock, SystemClock
from sparta.config import ConfigurationError, Settings
from sparta.domain.enums import ProviderKind
from sparta.domain.models import SpeechPlan
from sparta.observability.metrics import MEDIA_REJECTED, PROVIDER_LATENCY_MS, Metrics
from sparta.providers.base import (
    ProviderError,
    ProviderRejected,
    ProviderUnavailable,
    SynthesisRequest,
    TextToSpeechProvider,
    produces_audio,
)
from sparta.providers.tts.ssml import estimate_duration_ms
from sparta.telephony.asterisk.protocol import SAMPLE_RATE, AudioSocketError
from sparta.telephony.asterisk.server import AudioSocketServer, PeerPolicy
from sparta.telephony.asterisk.session import AudioSocketSession, MediaLimits
from sparta.telephony.base import (
    IncomingCall,
    Playback,
    ProviderCallRef,
    ProviderStatus,
    TelephonyCapabilities,
    TelephonyEventSink,
    TransferResult,
)

log = logging.getLogger("sparta.telephony.asterisk")

PROVIDER = "asterisk"
CALLBACK_USER = "asterisk"
INCOMING_PATH = "/api/v1/webhooks/asterisk/incoming"
NEXT_PATH = "/api/v1/webhooks/asterisk/next"
ENDED_PATH = "/api/v1/webhooks/asterisk/ended"
MAX_TRACKED = 1024
TRANSFER_SPEECH_WAIT_S = 8.0  # how long a takeover waits for its announcement to be sent before the socket closes
MEDIA_ATTACH_TIMEOUT_S = 10.0  # how long a spoken line waits for the media socket to connect

_CHANNEL = re.compile(r"[A-Za-z0-9._:\-]{1,64}")
_EXTENSION = re.compile(r"[0-9]{2,8}")
_DIAL_STATUS = re.compile(r"[A-Z_]{1,24}|-")
REJECT_REASONS = ("busy", "declined", "unavailable")


def _consume(task: "asyncio.Future[None]") -> None:
    if not task.cancelled():
        task.exception()  # retrieved here, so a failure after its waiter was cancelled is not reported as "never retrieved"


async def _shielded(call: Awaitable[None]) -> None:
    """Deliver an event to the call service so that tearing a call down cannot cancel it half-way through its database
    transaction: if the waiting task is cancelled, the delivery still runs to completion on its own."""
    inner = asyncio.ensure_future(call)
    inner.add_done_callback(_consume)
    await asyncio.shield(inner)


NOTE = (
    "Local SIP through Asterisk: real two-way voice over IP on a trusted network. There is no phone-number (PSTN) "
    "connection, so ordinary mobile or landline callers cannot reach Sparta this way."
)


@dataclass(frozen=True)
class IncomingDecision:
    """What the dialplan is told: take the call (with its single-use media id) or refuse it."""

    accept: bool
    media_id: str | None = None
    reason: str = "unavailable"
    call_id: str | None = None

    def line(self) -> str:
        if self.accept and self.media_id:
            return f"ACCEPT {self.media_id}"
        return f"REJECT {self.reason if self.reason in REJECT_REASONS else 'unavailable'}"


@dataclass
class _Pending:
    call: IncomingCall
    at: float


@dataclass(eq=False)
class _Call:
    call_id: str
    channel: str
    media_id: str
    issued_at: float
    session: AudioSocketSession | None = None
    claimed: bool = False
    media_ready: asyncio.Event = field(default_factory=asyncio.Event)
    quiet: asyncio.Event = field(default_factory=asyncio.Event)
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    playbacks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    watchdog: asyncio.Task[None] | None = None
    hangup_requested: bool = False
    transfer: str = "none"  # none -> requested -> dialling
    next_action: str = "hangup"
    pending_lines: int = 0

    def __post_init__(self) -> None:
        self.quiet.set()


class AsteriskTelephonyProvider:
    """:class:`~sparta.telephony.base.TelephonyProvider` for a local Asterisk. See the module docstring."""

    name = PROVIDER
    kind = ProviderKind.ASTERISK

    def __init__(
        self,
        settings: Settings,
        *,
        tts: TextToSpeechProvider,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
        media_attach_timeout_s: float = MEDIA_ATTACH_TIMEOUT_S,
    ) -> None:
        self._settings = settings
        self._tts = tts
        self._clock = clock or SystemClock()
        self._metrics = metrics or Metrics()
        self._media_attach_timeout_s = media_attach_timeout_s
        secret = settings.asterisk_secret()
        self._secret = secret.encode("utf-8") if secret else None
        self._sink: TelephonyEventSink | None = None
        self._calls: dict[str, _Call] = {}
        self._by_channel: dict[str, _Call] = {}
        self._by_media_id: dict[str, _Call] = {}
        self._spent: OrderedDict[str, None] = OrderedDict()
        self._ended: OrderedDict[str, None] = OrderedDict()
        self._pending: dict[str, _Pending] = {}
        self._incoming: OrderedDict[str, asyncio.Task[IncomingDecision]] = OrderedDict()
        self._counter = itertools.count(1)
        self._limits = MediaLimits(
            handshake_timeout_s=settings.asterisk_handshake_timeout_s,
            idle_timeout_s=settings.asterisk_idle_timeout_s,
            lead_s=settings.asterisk_playback_lead_ms / 1000.0,
        )
        self._peers = PeerPolicy(settings.asterisk_media_peers, clock=self._clock)
        self._server = AudioSocketServer(
            host=settings.asterisk_media_bind,
            port=settings.asterisk_media_port,
            peers=self._peers,
            handler=self._on_connection,
            max_connections=settings.asterisk_max_media_connections,
            metrics=self._metrics,
        )
        self.live_configured = self._secret is not None
        owner = settings.asterisk_owner_extension
        self.capabilities = TelephonyCapabilities(
            can_answer=True,
            can_play_audio=produces_audio(tts),
            can_stop_playback=True,
            can_transfer=True,  # rings the owner's SIP extension
            can_hangup=True,
            receives_caller_audio=True,
            two_way_audio=False,  # per call: see capabilities_for_call()
            dtmf=True,
            simulated=False,
            live_calls_supported=self.live_configured,
            note=NOTE,
            takeover_destination=owner,
            takeover_note=f"Take Over rings SIP extension {owner} on this local server. It does not call a phone number.",
        )

    # --------------------------------------------------------------------------------------- wiring
    def bind(self, sink: TelephonyEventSink) -> None:
        self._sink = sink

    def _require_sink(self) -> TelephonyEventSink:
        if self._sink is None:
            raise ProviderUnavailable(PROVIDER, "events", "the provider is not bound to an event sink")
        return self._sink

    async def start(self) -> None:
        """Open the media listener. Called once at startup (never for the hermetic replay containers)."""
        try:
            await self._server.start()
        except OSError as exc:
            raise ConfigurationError(
                [
                    f"Cannot listen for Asterisk media on {self._settings.asterisk_media_bind}:"
                    f"{self._settings.asterisk_media_port} ({exc.strerror or type(exc).__name__}); "
                    "change SPARTA_ASTERISK_MEDIA_PORT or stop whatever holds the port"
                ]
            ) from exc
        log.info("asterisk media listener started", extra={"port": self._server.port})

    @property
    def media_port(self) -> int:
        return self._server.port

    def verify_callback(self, authorization: str | None) -> bool:
        """HTTP Basic with the shared secret, compared in constant time. No secret configured means nothing passes."""
        if self._secret is None or not authorization:
            return False
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            user, _, password = base64.b64decode(value.strip(), validate=True).partition(b":")
        except (binascii.Error, ValueError):
            return False
        user_ok = hmac.compare_digest(user, CALLBACK_USER.encode())
        secret_ok = hmac.compare_digest(password, self._secret)
        return user_ok and secret_ok

    async def peer_allowed(self, address: str) -> bool:
        """Whether a request or connection from ``address`` comes from an allowed peer (Asterisk)."""
        return await self._peers.allows(address)

    def capabilities_for_call(self, call_id: str) -> TelephonyCapabilities:
        state = self._calls.get(call_id)
        attached = state is not None and state.session is not None and not state.session.closed
        return dataclasses.replace(self.capabilities, two_way_audio=attached)

    async def status(self) -> ProviderStatus:
        listening = self._server.listening
        speech_ready = produces_audio(self._tts)
        detail = NOTE
        if not self.live_configured:
            detail = "The callback secret is not set. " + NOTE
        elif not listening:
            detail = "The media listener is not running. " + NOTE
        elif not speech_ready:
            detail = "Text-to-speech is simulated, so calls would be silent. " + NOTE
        return ProviderStatus(
            provider=self.name,
            kind=self.kind,
            healthy=self.live_configured and listening and speech_ready,
            simulated=False,
            detail=detail,
            extra={
                "live_calls_supported": str(self.live_configured).lower(),
                "connection": "local_sip",
                "pstn": "not_configured",
                "listening": str(listening).lower(),
                "active_calls": str(len(self._calls)),
                "media_sessions": str(sum(1 for c in self._calls.values() if c.session is not None)),
                "pending_media": str(len(self._by_media_id)),
                "media_connections": str(self._server.connections),
            },
        )

    # -------------------------------------------------------------------------------------- incoming
    async def handle_incoming(self, fields: Mapping[str, str]) -> IncomingDecision:
        """The dialplan's question for one new call. Idempotent per channel: a repeat gets the same answer."""
        sink = self._require_sink()
        channel = fields.get("channel", "")
        if not _CHANNEL.fullmatch(channel):
            raise ProviderRejected(PROVIDER, "incoming", "invalid channel id")
        if fields.get("exten", "") != self._settings.asterisk_extension:
            return IncomingDecision(False, reason="declined")
        task = self._incoming.get(channel)
        if task is None:
            task = asyncio.ensure_future(self._accept_incoming(fields, channel, sink))
            self._incoming[channel] = task
            while len(self._incoming) > MAX_TRACKED:
                self._incoming.popitem(last=False)
        try:
            return await asyncio.shield(task)
        except BaseException:
            if task.done():
                self._incoming.pop(channel, None)  # a failed acceptance may be tried again
            raise

    async def _accept_incoming(
        self, fields: Mapping[str, str], channel: str, sink: TelephonyEventSink
    ) -> IncomingDecision:
        if len(self._calls) + len(self._pending) >= self._settings.max_active_calls:
            return IncomingDecision(False, reason="busy")
        caller = fields.get("caller", "")
        label = f"SIP {caller}" if _EXTENSION.fullmatch(caller) else None
        incoming = IncomingCall(
            provider=PROVIDER,
            provider_call_id=channel,
            caller_number=None,  # a SIP extension is not a phone number: no per-number throttle, nothing to mask
            called_number=None,
            display_name=label,
            correlation_id=channel,
            received_at=self._clock.now(),
        )
        self._pending[channel] = _Pending(incoming, self._clock.monotonic())
        try:
            call_id = await sink.incoming_call(incoming)  # a limit or policy rejection is raised to the route
        except ProviderError:
            return IncomingDecision(False, reason="unavailable")
        finally:
            self._pending.pop(channel, None)
        state = self._calls.get(call_id)
        if state is None or call_id in self._ended:
            return IncomingDecision(False, reason="declined", call_id=call_id)  # blocked: ended before it was answered
        return IncomingDecision(True, media_id=state.media_id, call_id=call_id)

    async def answer(self, call: ProviderCallRef) -> None:
        """The ACCEPT answer is the answer; this registers the call and issues its single-use media id."""
        if call.call_id in self._ended:
            raise ProviderRejected(PROVIDER, "answer", "the call has already ended")
        if call.call_id in self._calls:
            return
        pending = self._pending.get(call.provider_call_id or "")
        if pending is None:
            raise ProviderRejected(PROVIDER, "answer", "no incoming call for this id")
        state = _Call(
            call_id=call.call_id,
            channel=pending.call.provider_call_id,
            media_id=str(uuid.UUID(bytes=secrets.token_bytes(16), version=4)),
            issued_at=self._clock.monotonic(),
        )
        self._calls[call.call_id] = state
        self._by_channel[state.channel] = state
        self._by_media_id[state.media_id] = state
        state.watchdog = asyncio.ensure_future(self._expire_unclaimed(state))

    async def _expire_unclaimed(self, state: _Call) -> None:
        """Asterisk must use the media id in time; if it never does the call is over."""
        await self._clock.sleep(self._settings.asterisk_claim_ttl_s, tag="watchdog")
        if state.claimed or self._calls.get(state.call_id) is not state:
            return
        self._metrics.inc(MEDIA_REJECTED, provider=PROVIDER, reason="never_connected")
        log.warning("media never connected", extra={"call_id": state.call_id})
        await self._remote_hangup(state, "media_never_connected")

    # ------------------------------------------------------------------------------------ media socket
    async def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, peer: str) -> None:
        session = AudioSocketSession(reader, writer, peer=peer, clock=self._clock, limits=self._limits)
        state: _Call | None = None
        try:
            try:
                media_id = await session.handshake()
            except AudioSocketError as exc:
                self._refuse(exc.reason)
                return
            state = self._claim(media_id)
            if state is None:
                return
            state.session = session
            state.media_ready.set()
            if state.watchdog is not None:
                state.watchdog.cancel()
            self._metrics.observe(
                PROVIDER_LATENCY_MS,
                (self._clock.monotonic() - state.issued_at) * 1000.0,
                provider=PROVIDER,
                stage="media_connect",
            )
            sink = self._require_sink()
            call_id = state.call_id

            async def on_audio(pcm: bytes) -> None:
                await sink.caller_audio(call_id, pcm, SAMPLE_RATE)

            async def on_dtmf(digit: str) -> None:
                await sink.caller_dtmf(call_id, digit)

            reason = await session.run(on_audio=on_audio, on_dtmf=on_dtmf)
            if reason.startswith("protocol:"):
                self._metrics.inc(MEDIA_REJECTED, provider=PROVIDER, reason=reason.removeprefix("protocol:"))
            if session.first_audio_at is not None:
                self._metrics.observe(
                    PROVIDER_LATENCY_MS,
                    (session.first_audio_at - session.connected_at) * 1000.0,
                    provider=PROVIDER,
                    stage="first_caller_audio",
                )
        finally:
            await session.close()
            if state is not None and state.session is session:
                state.session = None
                state.media_ready.clear()
                if self._calls.get(state.call_id) is state and not state.hangup_requested and state.transfer == "none":
                    await self._remote_hangup(state, "disconnected")

    def _claim(self, media_id: str) -> _Call | None:
        """Atomically turn a media id into the call's live stream. No await between the lookup and the claim."""
        state = self._by_media_id.pop(media_id, None)
        if state is None:
            self._refuse("already_used" if media_id in self._spent else "unknown_id")
            return None
        self._spent[media_id] = None
        while len(self._spent) > MAX_TRACKED:
            self._spent.popitem(last=False)
        if self._calls.get(state.call_id) is not state or state.hangup_requested:
            self._refuse("call_ended")
            return None
        state.claimed = True
        return state

    def _refuse(self, reason: str) -> None:
        self._metrics.inc(MEDIA_REJECTED, provider=PROVIDER, reason=reason)
        log.warning("media connection refused", extra={"reason": reason})

    # ------------------------------------------------------------------------------------- playback
    async def play(self, call: ProviderCallRef, plan: SpeechPlan) -> Playback:
        state = self._calls.get(call.call_id)
        if state is None:
            raise ProviderRejected(PROVIDER, "play", "the call is not active")
        if not produces_audio(self._tts):
            raise ProviderRejected(
                PROVIDER, "play", "a real text-to-speech provider is required to speak on a live call"
            )
        playback_id = f"pb_{call.call_id[-8:]}_{next(self._counter)}"
        state.pending_lines += 1  # counted now, so a takeover knows this line is on its way
        state.quiet.clear()
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
                    output_format="pcm16_8k",
                    trace_id=playback_id,
                )
                started = self._clock.monotonic()
                finished = await session.send_audio_stream(self._pcm(request, started))
            # A stream that closed mid-line is not a provider failure: the caller hung up (the media session reports
            # that as a remote hang-up), or Sparta ended or handed over the call itself.
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            await self._report_error(state.call_id, "play", exc.message)
        except Exception as exc:
            log.warning("playback failed", extra={"call_id": state.call_id, "error_type": type(exc).__name__})
            await self._report_error(state.call_id, "play", "playback failed")
        finally:
            state.playbacks.pop(playback_id, None)
            state.pending_lines = max(0, state.pending_lines - 1)
            if state.pending_lines == 0:
                state.quiet.set()
        if finished and self._sink is not None:
            try:
                await _shielded(self._sink.playback_finished(state.call_id, playback_id))
            except Exception as exc:
                log.warning("playback completion failed", extra={"error_type": type(exc).__name__})

    async def _pcm(self, request: SynthesisRequest, started: float) -> AsyncIterator[bytes]:
        first = True
        async for chunk in self._tts.synthesize_stream(request):
            if not chunk.data:
                continue
            if chunk.sample_rate != SAMPLE_RATE or chunk.encoding != "pcm16":
                raise ProviderRejected(
                    PROVIDER, "play", f"speech arrived as {chunk.encoding} at {chunk.sample_rate} Hz, not 8 kHz PCM"
                )
            if first:
                first = False
                self._metrics.observe(
                    PROVIDER_LATENCY_MS,
                    (self._clock.monotonic() - started) * 1000.0,
                    provider=PROVIDER,
                    stage="tts_first_audio",
                )
            yield chunk.data

    async def _wait_for_media(self, state: _Call) -> AudioSocketSession:
        session = state.session
        if session is None or session.closed:
            try:
                await asyncio.wait_for(state.media_ready.wait(), timeout=self._media_attach_timeout_s)
            except TimeoutError:
                raise ProviderError(PROVIDER, "play", "the media stream is not connected") from None
            session = state.session
        if session is None or session.closed:
            raise ProviderError(PROVIDER, "play", "the media stream is not connected")
        return session

    async def stop_playback(self, call: ProviderCallRef, playback_id: str) -> None:
        state = self._calls.get(call.call_id)
        if state is None:
            return
        task = state.playbacks.get(playback_id)
        if task is not None:
            task.cancel()  # first: a cancelled playback must never report "finished"
        with contextlib.suppress(ProviderError):
            await self._tts.stop_playback(playback_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
            if state.playbacks.pop(playback_id, None) is not None:  # cancelled before it ever ran its own clean-up
                state.pending_lines = max(0, state.pending_lines - 1)
                if state.pending_lines == 0:
                    state.quiet.set()

    # --------------------------------------------------------------------------------- end of a call
    async def hangup(self, call: ProviderCallRef, reason: str) -> None:
        """End the call. Idempotent: the service calls this at the end of every call, including remote hang-ups."""
        state = self._calls.get(call.call_id)
        if state is None:
            self._tombstone(call.call_id)
            return
        if state.hangup_requested:
            return
        state.hangup_requested = True
        state.next_action = "hangup"
        await self._finish_call(state, hang_up=True)

    def _tombstone(self, call_id: str) -> None:
        self._ended[call_id] = None
        while len(self._ended) > MAX_TRACKED:
            self._ended.popitem(last=False)

    async def _finish_call(self, state: _Call, *, hang_up: bool = False) -> None:
        if self._calls.get(state.call_id) is state:
            self._calls.pop(state.call_id, None)
        if self._by_channel.get(state.channel) is state:
            self._by_channel.pop(state.channel, None)
        self._by_media_id.pop(state.media_id, None)
        self._tombstone(state.call_id)
        current = asyncio.current_task()
        others = [t for t in state.playbacks.values() if t is not current]
        if state.watchdog is not None and state.watchdog is not current:
            others.append(state.watchdog)
        for task in others:
            task.cancel()
        if others:
            await asyncio.gather(*others, return_exceptions=True)
        state.quiet.set()
        if state.session is not None:
            await state.session.close(hang_up=hang_up)

    async def _remote_hangup(self, state: _Call, reason: str) -> None:
        if self._calls.get(state.call_id) is not state:
            return  # already finished (this is the second of several signals that the call is over)
        await self._finish_call(state)
        if self._sink is not None:
            await _shielded(self._sink.remote_hangup(state.call_id, reason))

    async def _report_error(self, call_id: str, stage: str, message: str) -> None:
        if self._sink is None:
            return
        try:
            await _shielded(self._sink.provider_error(call_id, stage, message))
        except Exception as exc:
            log.warning("provider error could not be reported", extra={"error_type": type(exc).__name__})

    # ---------------------------------------------------------------------------------------- transfer
    async def transfer(self, call: ProviderCallRef, destination: str | None) -> TransferResult:
        """Hand the call to the owner's SIP extension: the socket ends, then the dialplan rings the extension.

        Only the configured owner extension can be rung: a destination is never taken from a caller or a request."""
        owner = self._settings.asterisk_owner_extension
        if not destination or destination != owner:
            return TransferResult(False, False, "Only the configured owner SIP extension can take a call over.")
        state = self._calls.get(call.call_id)
        if state is None or state.session is None or state.session.closed:
            return TransferResult(False, False, "The call's audio is not connected, so it cannot be handed over.")
        if state.transfer != "none":
            return TransferResult(True, False, f"Transfer already requested: ringing SIP extension {owner}.")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(state.quiet.wait(), TRANSFER_SPEECH_WAIT_S)  # the announcement is heard first
        state.transfer = "requested"
        state.next_action = f"dial:{owner}"
        await state.session.close(hang_up=True)
        return TransferResult(True, False, f"Transfer requested: ringing SIP extension {owner} on this local server.")

    # ----------------------------------------------------------------------------- dialplan follow-ups
    def handle_next(self, channel: str) -> str:
        """What the dialplan does after the media socket ended: ``DIAL <extension>`` or ``HANGUP``."""
        state = self._by_channel.get(channel)
        if state is not None and state.transfer == "requested" and state.next_action.startswith("dial:"):
            state.transfer = "dialling"
            return "DIAL " + state.next_action.removeprefix("dial:")
        return "HANGUP"

    async def handle_ended(self, channel: str, dial_status: str) -> None:
        """The dialplan's report that the call is over (idempotent: the call may already be finished)."""
        state = self._by_channel.get(channel)
        if state is None:
            return
        if state.transfer != "none" and _DIAL_STATUS.fullmatch(dial_status) and dial_status not in ("ANSWER", "-"):
            await self._report_error(
                state.call_id, "transfer", f"The owner's extension was not reached ({dial_status.lower()})."
            )
        await self._remote_hangup(state, "disconnected")

    # ------------------------------------------------------------------------------------- lifecycle
    async def aclose(self) -> None:
        for state in list(self._calls.values()):
            await self._finish_call(state, hang_up=True)
        for task in list(self._incoming.values()):
            if not task.done():
                task.cancel()
        await self._server.aclose()


def build_asterisk_provider(
    settings: Settings, *, tts: TextToSpeechProvider, clock: Clock | None = None, metrics: Metrics | None = None
) -> AsteriskTelephonyProvider:
    return AsteriskTelephonyProvider(settings, tts=tts, clock=clock, metrics=metrics)
