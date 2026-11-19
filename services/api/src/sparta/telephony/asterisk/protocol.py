"""The AudioSocket wire format of Asterisk's ``res_audiosocket`` (verified against the 22.12.0 sources).

Every message is ``kind (1 byte) | payload length (2 bytes, big endian) | payload``. Asterisk connects to Sparta and
sends the call's UUID first, then caller audio (signed 16-bit little-endian PCM, mono, 8 kHz, usually 20 ms = 320 bytes)
and DTMF digits. Sparta may send audio and a hang-up and nothing else: Asterisk treats any other message as an error and
ends the call, and a zero-length payload as invalid.
"""

import asyncio
import uuid

KIND_HANGUP = 0x00
KIND_UUID = 0x01
KIND_DTMF = 0x03
KIND_AUDIO = 0x10

SAMPLE_RATE = 8000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * 2 * FRAME_MS // 1000  # 320
HEADER_BYTES = 3
MAX_INBOUND_PAYLOAD = 4096  # a 20 ms frame is 320 bytes; even a 100 ms burst fits with room to spare
DTMF_DIGITS = frozenset("0123456789*#ABCD")


class AudioSocketError(Exception):
    """The peer broke the protocol. ``reason`` is a short stable code, safe to log and to use as a metric label."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def encode(kind: int, payload: bytes = b"") -> bytes:
    """One message as a single bytes object. Send it with ONE write: Asterisk allows a partial payload only 5 ms to
    complete before it drops the call, so a header and a payload must never be sent separately."""
    if len(payload) > 0xFFFF:
        raise ValueError("AudioSocket payloads are at most 65535 bytes")
    return bytes((kind, len(payload) >> 8, len(payload) & 0xFF)) + payload


def audio_message(frame: bytes) -> bytes:
    if len(frame) < 2 or len(frame) % 2:
        raise ValueError("audio must be a whole number of 16-bit samples")
    return encode(KIND_AUDIO, frame)


HANGUP_MESSAGE = encode(KIND_HANGUP)


async def read_message(
    reader: asyncio.StreamReader, *, max_payload: int = MAX_INBOUND_PAYLOAD
) -> tuple[int, bytes] | None:
    """The next message, or ``None`` when the peer closed the stream cleanly between two messages."""
    try:
        header = await reader.readexactly(HEADER_BYTES)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise AudioSocketError("truncated_header") from None
    length = (header[1] << 8) | header[2]
    if length > max_payload:
        raise AudioSocketError("oversized")
    if length == 0:
        return header[0], b""
    try:
        return header[0], await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        raise AudioSocketError("truncated_payload") from None


def parse_uuid(payload: bytes) -> str:
    if len(payload) != 16:
        raise AudioSocketError("bad_uuid")
    return str(uuid.UUID(bytes=payload))


def parse_dtmf(payload: bytes) -> str:
    if len(payload) != 1 or chr(payload[0]) not in DTMF_DIGITS:
        raise AudioSocketError("bad_dtmf")
    return chr(payload[0])


def check_audio(payload: bytes) -> bytes:
    """Whole 16-bit samples only: an odd length means the stream is not what it claims to be."""
    if len(payload) < 2 or len(payload) % 2:
        raise AudioSocketError("bad_audio")
    return payload
