"""One AudioSocket connection: the handshake, caller audio in, paced speech out.

Reading never waits for the audio pipeline: Asterisk fails the call when its writes to a full socket do not complete, so
frames go into a bounded queue (the oldest is dropped, and counted, if the consumer falls far behind) and a separate task
hands them on. Speech is sent in exact 20 ms frames in real time (see ``pacer.py``); cancelling the sender is the whole
of "stop talking", because nothing is queued on Asterisk's side.
"""

import asyncio
import contextlib
import logging
import secrets
from collections import deque
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass

from sparta.clock import Clock
from sparta.telephony.asterisk.pacer import FRAME_S, FramePacer
from sparta.telephony.asterisk.protocol import (
    FRAME_BYTES,
    HANGUP_MESSAGE,
    KIND_AUDIO,
    KIND_DTMF,
    KIND_HANGUP,
    KIND_UUID,
    MAX_INBOUND_PAYLOAD,
    AudioSocketError,
    audio_message,
    check_audio,
    parse_dtmf,
    parse_uuid,
    read_message,
)

log = logging.getLogger("sparta.asterisk.media")

MAX_COALESCED_FRAMES = 25  # up to 500 ms of audio handed to the pipeline in one call after a stall
HANDSHAKE_MAX_PAYLOAD = 64
DRAIN_TIMEOUT_S = 2.0  # how long audio that arrived just before the end may still take to be handed on


@dataclass(frozen=True)
class MediaLimits:
    handshake_timeout_s: float = 3.0
    idle_timeout_s: float = 10.0
    lead_s: float = 0.040
    write_timeout_s: float = 2.0
    queue_frames: int = 250  # five seconds of 20 ms frames
    max_payload: int = MAX_INBOUND_PAYLOAD


AudioHandler = Callable[[bytes], Awaitable[None]]
DtmfHandler = Callable[[str], Awaitable[None]]


class AudioSocketSession:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        peer: str,
        clock: Clock,
        limits: MediaLimits | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._clock = clock
        self._limits = limits or MediaLimits()
        self.peer = peer
        self.session_id = secrets.token_hex(4)  # for logs; the media id itself is never logged
        self.closed = False
        self.connected_at = clock.monotonic()
        self.first_audio_at: float | None = None
        self.stats = {
            "frames_in": 0,
            "bytes_in": 0,
            "dropped_frames": 0,
            "dtmf": 0,
            "frames_out": 0,
            "bytes_out": 0,
            "resyncs": 0,
            "protocol_errors": 0,
        }
        self._inbound: deque[bytes] = deque()
        self._wake = asyncio.Event()
        self._finished = False

    # ------------------------------------------------------------------------------------ handshake
    async def handshake(self) -> str:
        """The media id Asterisk announces. It must be the first message and arrive in time."""
        try:
            message = await asyncio.wait_for(
                read_message(self._reader, max_payload=HANDSHAKE_MAX_PAYLOAD), self._limits.handshake_timeout_s
            )
        except TimeoutError:
            raise AudioSocketError("handshake_timeout") from None
        except (ConnectionError, OSError):
            raise AudioSocketError("handshake_reset") from None
        if message is None:
            raise AudioSocketError("closed_before_id")
        kind, payload = message
        if kind != KIND_UUID:
            raise AudioSocketError("first_message_not_id")
        return parse_uuid(payload)

    # ------------------------------------------------------------------------------------- inbound
    async def run(self, *, on_audio: AudioHandler, on_dtmf: DtmfHandler) -> str:
        """Read until the connection ends and return why: ``hangup``, ``idle``, ``reset`` or ``protocol:<reason>``.

        Audio that arrived before the end is still delivered (the caller's last words count), within a short bound."""
        deliver = asyncio.ensure_future(self._deliver(on_audio))
        try:
            reason = await self._read_loop(on_dtmf)
            self._finished = True
            self._wake.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(deliver), DRAIN_TIMEOUT_S)
            return reason
        finally:
            deliver.cancel()
            await asyncio.gather(deliver, return_exceptions=True)

    async def _read_loop(self, on_dtmf: DtmfHandler) -> str:
        while True:
            try:
                message = await asyncio.wait_for(
                    read_message(self._reader, max_payload=self._limits.max_payload), self._limits.idle_timeout_s
                )
            except TimeoutError:
                return "idle"
            except AudioSocketError as exc:
                self.stats["protocol_errors"] += 1
                return f"protocol:{exc.reason}"
            except (ConnectionError, OSError):
                return "reset"
            if message is None:
                return "hangup"
            kind, payload = message
            try:
                if kind == KIND_AUDIO:
                    self._enqueue(check_audio(payload))
                elif kind == KIND_DTMF:
                    self.stats["dtmf"] += 1
                    await on_dtmf(parse_dtmf(payload))
                elif kind == KIND_HANGUP:
                    return "hangup"
                else:
                    raise AudioSocketError("unexpected_message")
            except AudioSocketError as exc:
                self.stats["protocol_errors"] += 1
                return f"protocol:{exc.reason}"

    def _enqueue(self, frame: bytes) -> None:
        if self.first_audio_at is None:
            self.first_audio_at = self._clock.monotonic()
        if len(self._inbound) >= self._limits.queue_frames:
            self._inbound.popleft()
            self.stats["dropped_frames"] += 1
        self._inbound.append(frame)
        self.stats["frames_in"] += 1
        self.stats["bytes_in"] += len(frame)
        self._wake.set()

    async def _deliver(self, on_audio: AudioHandler) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._inbound:
                batch = [self._inbound.popleft() for _ in range(min(len(self._inbound), MAX_COALESCED_FRAMES))]
                try:
                    await on_audio(b"".join(batch))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # one bad batch must not stop the call hearing the caller
                    log.warning("caller audio handler failed", extra={"error_type": type(exc).__name__})
            if self._finished:
                return

    # ------------------------------------------------------------------------------------ outbound
    async def send_audio_stream(self, chunks: AsyncIterable[bytes]) -> bool:
        """Send speech in real time as 20 ms frames, then wait until the far end has had time to play it.

        ``True`` when all of it was sent and played out; ``False`` when the connection closed first. Cancelling the
        caller stops sending at once (the unrecallable remainder is about the lead)."""
        pacer = FramePacer(self._clock, lead_s=self._limits.lead_s)
        carry = bytearray()
        try:
            async for chunk in chunks:
                carry += chunk
                while len(carry) >= FRAME_BYTES:
                    frame = bytes(carry[:FRAME_BYTES])
                    del carry[:FRAME_BYTES]
                    if not await self._send_frame(pacer, frame):
                        return False
            if carry and not await self._send_frame(pacer, bytes(carry) + bytes(FRAME_BYTES - len(carry))):
                return False
            if pacer.frames:
                await self._clock.sleep(pacer.remaining_s(), tag="media")
            return not self.closed
        finally:
            self.stats["resyncs"] += pacer.resyncs

    async def _send_frame(self, pacer: FramePacer, frame: bytes) -> bool:
        if self.closed:
            return False
        await pacer.wait_turn()
        if self.closed:
            return False
        try:
            self._writer.write(audio_message(frame))  # one write: header and payload must not be split
            await asyncio.wait_for(self._writer.drain(), self._limits.write_timeout_s)
        except (ConnectionError, OSError, TimeoutError):
            await self.close()
            return False
        self.stats["frames_out"] += 1
        self.stats["bytes_out"] += len(frame)
        return True

    # ------------------------------------------------------------------------------------- closing
    async def close(self, *, hang_up: bool = False) -> None:
        """Close the connection. With ``hang_up`` Asterisk is told first, so its dialplan continues cleanly."""
        if self.closed:
            return
        self.closed = True
        if hang_up and not self._writer.is_closing():
            with contextlib.suppress(Exception):
                self._writer.write(HANGUP_MESSAGE)
                await asyncio.wait_for(self._writer.drain(), 0.5)
        with contextlib.suppress(Exception):
            self._writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._writer.wait_closed(), 1.0)


__all__ = ["FRAME_S", "AudioSocketSession", "MediaLimits"]
