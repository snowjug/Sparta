"""Tone-coded audio for the fake speech providers (tests and local plumbing checks only, never production).

A fake recogniser cannot understand speech, but a test that plays *audio* through SIP, Asterisk and a media bridge still
wants to prove that real samples arrive intact. So a "line" is identified by a small integer that is rendered as a short
burst of tones and read back from the samples:

* the caller side of a test plays ``encode_line_id(n)`` followed by any voiced filler; the fake recogniser decodes ``n``
  and answers with the phrase registered for it (``providers/stt/fake_phrases.py``);
* the fake synthesiser starts every assistant line with the burst of ``line_id_for(text)`` and fills the rest with a steady
  tone, so a recording of the call shows which lines were spoken, when, and for how long (a barge-in cuts the tone short).

The burst is two sync symbols, two data symbols (the id as two nibbles) and a check symbol, 40 ms each. Frequencies sit on
multiples of 25 Hz, so every 40 ms window holds a whole number of cycles at any sample rate that is a multiple of 1 kHz and
a wrong sample rate or byte order makes the burst unreadable. Everything is pure Python (no NumPy) and little-endian PCM16.
"""

import math
import zlib
from array import array

SYMBOL_MS = 40
SYNC_HZ = 600.0
SYMBOL_HZ: tuple[float, ...] = tuple(900.0 + 150.0 * i for i in range(16))  # 900 ... 3150 Hz, inside the telephone band
FILLER_HZ = 440.0
AMPLITUDE = 12_000
FILLER_AMPLITUDE = 8_000
BURST_SYMBOLS = 5
BURST_MS = BURST_SYMBOLS * SYMBOL_MS
MAX_SCAN_MS = 3_000  # the burst opens a line: nothing past the first seconds is searched
_MIN_RMS = 1_200.0
_MIN_DOMINANCE = 0.55


def line_id_for(text: str) -> int:
    """The id of an assistant line: a stable 8-bit hash of its text (collisions are possible and harmless)."""
    return zlib.crc32(text.encode("utf-8")) & 0xFF


def tone(freq_hz: float, ms: int, rate: int, amplitude: int = AMPLITUDE) -> bytes:
    """``ms`` of a sine tone as little-endian PCM16 mono."""
    count = rate * ms // 1000
    step = 2.0 * math.pi * freq_hz / rate
    return array("h", [int(amplitude * math.sin(step * i)) for i in range(count)]).tobytes()


def silence(ms: int, rate: int) -> bytes:
    return bytes(rate * ms // 1000 * 2)


def encode_line_id(line_id: int, rate: int) -> bytes:
    """The 200 ms burst that carries ``line_id`` (0..255)."""
    if not 0 <= line_id <= 0xFF:
        raise ValueError("a line id is one byte")
    hi, lo = line_id >> 4, line_id & 0x0F
    check = (hi ^ lo ^ 0x0A) & 0x0F
    parts = [tone(SYNC_HZ, SYMBOL_MS, rate)] * 2
    parts += [tone(SYMBOL_HZ[symbol], SYMBOL_MS, rate) for symbol in (hi, lo, check)]
    return b"".join(parts)


def _samples(pcm16: bytes) -> "array[int]":
    out = array("h")
    out.frombytes(pcm16[: len(pcm16) // 2 * 2])
    return out


def _goertzel(samples: "array[int]", start: int, count: int, rate: int, freq_hz: float) -> float:
    coeff = 2.0 * math.cos(2.0 * math.pi * freq_hz / rate)
    s_prev = s_prev2 = 0.0
    for i in range(start, start + count):
        s = samples[i] + coeff * s_prev - s_prev2
        s_prev2, s_prev = s_prev, s
    return s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2


def _dominance(samples: "array[int]", start: int, count: int, rate: int, freq_hz: float) -> float:
    """The fraction of the window's energy that sits at ``freq_hz`` (about 1.0 for a pure tone of that frequency)."""
    energy = sum(samples[i] * samples[i] for i in range(start, start + count))
    if energy <= 0 or math.sqrt(energy / count) < _MIN_RMS:
        return 0.0
    return _goertzel(samples, start, count, rate, freq_hz) / (energy * count / 2.0)


def _symbol_at(samples: "array[int]", start: int, count: int, rate: int) -> int | None:
    best, best_power = None, 0.0
    energy = sum(samples[i] * samples[i] for i in range(start, start + count))
    if energy <= 0 or math.sqrt(energy / count) < _MIN_RMS:
        return None
    for index, freq in enumerate(SYMBOL_HZ):
        power = _goertzel(samples, start, count, rate, freq)
        if power > best_power:
            best, best_power = index, power
    if best is None or best_power / (energy * count / 2.0) < _MIN_DOMINANCE:
        return None
    return best


def decode_line_id(pcm16: bytes, rate: int) -> int | None:
    """The id carried by the first burst in ``pcm16``, or ``None`` when there is no intact burst."""
    samples = _samples(pcm16)
    window = rate * SYMBOL_MS // 1000
    hop = max(1, rate * 10 // 1000)
    last = min(len(samples) - BURST_SYMBOLS * window, rate * MAX_SCAN_MS // 1000)
    for start in range(0, last + 1, hop):
        if _dominance(samples, start, window, rate, SYNC_HZ) < _MIN_DOMINANCE:
            continue
        if _dominance(samples, start + window, window, rate, SYNC_HZ) < _MIN_DOMINANCE:
            continue
        hi = _symbol_at(samples, start + 2 * window, window, rate)
        lo = _symbol_at(samples, start + 3 * window, window, rate)
        check = _symbol_at(samples, start + 4 * window, window, rate)
        if hi is None or lo is None or check is None:
            continue
        if check == (hi ^ lo ^ 0x0A) & 0x0F:
            return (hi << 4) | lo
    return None


def tone_duration_ms(pcm16: bytes, rate: int, *, rms_threshold: float = 1_000.0) -> int:
    """How much of ``pcm16`` is audible (frames of 20 ms above ``rms_threshold``): a barge-in shortens it."""
    samples = _samples(pcm16)
    frame = rate * 20 // 1000
    loud = 0
    for start in range(0, len(samples) - frame + 1, frame):
        energy = sum(samples[i] * samples[i] for i in range(start, start + frame))
        if math.sqrt(energy / frame) >= rms_threshold:
            loud += 20
    return loud
