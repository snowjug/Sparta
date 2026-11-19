"""Audio helpers for the Docker SIP end-to-end test: build the caller's WAV timeline, read the recording of what the caller
heard, and find the tone-coded assistant lines in it (see ``sparta.providers.fake_tone``). Standard library only."""

import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path

from sparta.providers.fake_tone import encode_line_id, find_bursts, silence, tone

RATE = 8000
FRAME_MS = 20


def write_wav(path: Path, pcm: bytes, rate: int = RATE) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1 and handle.getsampwidth() == 2, "expected mono 16-bit PCM"
        return handle.readframes(handle.getnframes()), handle.getframerate()


def noise(ms: int, rate: int = RATE, amplitude: int = 9000) -> bytes:
    """Loud pseudo-random samples (a fixed generator, so the test is repeatable): audio that is not speech and carries no tones."""
    state = 0x2545F491
    out = array("h")
    for _ in range(rate * ms // 1000):
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        out.append((state % (2 * amplitude + 1)) - amplitude)
    return out.tobytes()


def utterance(phrase_id: int, rate: int = RATE, voiced_ms: int = 300, tail_ms: int = 900) -> tuple[bytes, int]:
    """One spoken phrase: the tone burst that carries its id, some voiced filler, then silence so the recogniser's voice
    activity detector ends the utterance. Returns ``(pcm, speech_ms)`` where ``speech_ms`` is the voiced part."""
    burst = encode_line_id(phrase_id, rate)
    voiced = tone(700, voiced_ms, rate, 8000)
    return burst + voiced + silence(tail_ms, rate), (len(burst) + len(voiced)) * 1000 // (rate * 2)


@dataclass
class Timeline:
    """The caller's microphone over the whole call: silence with sounds placed at given offsets."""

    rate: int = RATE
    parts: list[tuple[int, bytes]] = field(default_factory=list)

    def at(self, seconds: float, pcm: bytes) -> "Timeline":
        self.parts.append((int(seconds * self.rate) * 2, pcm))
        return self

    def render(self, total_seconds: float) -> bytes:
        size = int(total_seconds * self.rate) * 2
        buffer = bytearray(size)
        for offset, pcm in self.parts:
            end = min(size, offset + len(pcm))
            if offset < size:
                buffer[offset:end] = pcm[: end - offset]
        return bytes(buffer)


def audible_frames(pcm: bytes, rate: int = RATE, threshold: float = 1000.0) -> list[bool]:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    frame = rate * FRAME_MS // 1000
    flags: list[bool] = []
    for start in range(0, len(samples) - frame + 1, frame):
        energy = sum(samples[i] * samples[i] for i in range(start, start + frame))
        flags.append((energy / frame) ** 0.5 >= threshold)
    return flags


def segments(pcm: bytes, rate: int = RATE, merge_gap_ms: int = 160) -> list[tuple[int, int]]:
    """Audible stretches of the recording as ``(start ms, end ms)``; pauses shorter than ``merge_gap_ms`` do not split one."""
    out: list[list[int]] = []
    for index, loud in enumerate(audible_frames(pcm, rate)):
        if not loud:
            continue
        start, end = index * FRAME_MS, (index + 1) * FRAME_MS
        if out and start - out[-1][1] <= merge_gap_ms:
            out[-1][1] = end
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def heard_lines(pcm: bytes, rate: int = RATE) -> list[tuple[int, int]]:
    """The assistant lines in a recording as ``(offset ms, line id)``."""
    return find_bursts(pcm, rate)
