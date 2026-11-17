"""Validation of uploaded audio: declared type must match the bytes, size and duration are bounded.

Uploaded audio is only ever processed in memory and discarded. It is never written to disk or stored (raw audio storage
is off by default and refused in production).
"""

import struct
from dataclasses import dataclass

from sparta.services.errors import InvalidInput, PayloadTooLarge, UnsupportedMedia

ALLOWED = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
}


@dataclass(frozen=True)
class AudioInfo:
    container: str
    content_type: str
    size: int
    duration_s: float | None  # known only for WAV; other containers rely on the size bound and the STT provider


def sniff(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


MAX_WAV_CHUNKS = 32  # header chunks examined before the audio data; real files have fewer than ten


def wav_duration(data: bytes) -> float | None:
    """Upper bound on the seconds of PCM audio from the WAV header, or ``None`` if the header cannot be read.

    Only the first ``MAX_WAV_CHUNKS`` chunks are examined (a file of empty chunks must not keep the server busy) and,
    for PCM, the declared byte rate is checked against sample rate x channels x bits so a lying header cannot make a
    long recording look short.
    """
    try:
        pos, byte_rate = 12, 0
        for _ in range(MAX_WAV_CHUNKS):
            if pos + 8 > len(data):
                return None
            chunk_id = data[pos : pos + 4]
            (size,) = struct.unpack("<I", data[pos + 4 : pos + 8])
            if chunk_id == b"fmt ":
                if size < 16:
                    return None
                tag, channels, sample_rate, declared, _align, bits = struct.unpack("<HHIIHH", data[pos + 8 : pos + 24])
                byte_rate = declared
                if tag in (1, 0xFFFE) and channels and sample_rate and bits and bits % 8 == 0:
                    byte_rate = min(declared, sample_rate * channels * bits // 8) if declared else 0
            elif chunk_id == b"data":
                data_size = min(size, len(data) - pos - 8)
                return data_size / byte_rate if byte_rate else None
            pos += 8 + size + (size & 1)
    except struct.error:
        return None
    return None


def validate_audio(data: bytes, declared_type: str | None, *, max_bytes: int, max_seconds: int) -> AudioInfo:
    if len(data) > max_bytes:
        raise PayloadTooLarge(f"Audio is larger than the {max_bytes // 1_000_000} MB limit.")
    if not data:
        raise InvalidInput("The audio file is empty.")
    base = (declared_type or "").split(";", 1)[0].strip().lower()
    container = ALLOWED.get(base)
    if container is None:
        raise UnsupportedMedia("Unsupported audio type. Use WAV, Ogg or WebM.")
    if sniff(data) != container:
        raise UnsupportedMedia("The file contents do not match the declared audio type.")
    duration = wav_duration(data) if container == "wav" else None
    if container == "wav" and duration is None:
        raise InvalidInput("The WAV header could not be read. Use a standard PCM WAV file.")
    if duration is not None and duration > max_seconds:
        raise PayloadTooLarge(f"Audio is longer than the {max_seconds} second limit.")
    return AudioInfo(container=container, content_type=base, size=len(data), duration_s=duration)
