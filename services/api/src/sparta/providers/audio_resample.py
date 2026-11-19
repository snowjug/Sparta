"""Sample-rate conversion for 16-bit PCM speech, in pure Python (standard library only).

The local speech providers need it in both directions: caller audio arrives at 8 kHz and the recogniser wants 16 kHz, and
the synthesiser makes 22.05 kHz audio that a telephone line takes at 8 kHz. It is a polyphase FIR resampler with a
Kaiser-windowed sinc low-pass (beta 5, ten zero crossings each side), the design SciPy's ``resample_poly`` uses by default,
so the result matches that function to within one least-significant bit of int16 rounding (the tests check this when SciPy
is installed). Doing it here keeps NumPy and SciPy out of the code that must be testable without the optional speech
packages. ``math.sumprod`` (Python 3.12+) makes it cheap: about 1 us per output sample, a few percent of real time.

Properties worth knowing:

* the output is aligned with the input (the filter delay is compensated) and has ``ceil(n * dst / src)`` samples;
* content above the lower of the two rates' Nyquist frequency is removed before decimation (no aliasing), but
  upsampling adds no information: 8 kHz audio stays band-limited to 4 kHz at 16 kHz;
* the signal is treated as zero outside the buffer, so two buffers resampled separately show a tiny edge effect (a few
  samples of filter ringing) where they meet. The synthesiser resamples one sentence at a time: sentences start and end in
  near silence, so the effect is inaudible, and it is not worth the state a streaming resampler would need.

Samples are little-endian PCM16 mono, as everywhere in the telephony path.
"""

import math
import sys
from array import array
from dataclasses import dataclass
from functools import lru_cache

KAISER_BETA = 5.0
ZERO_CROSSINGS = 10  # filter half-length, in samples of the lower of the two rates
_TRIM = 1e-12  # coefficients below this fraction of a phase's largest are dropped (a half-band phase is a single tap)
_PEAK = 32767
_FLOOR = -32768


def _bessel_i0(x: float) -> float:
    """Modified Bessel function of the first kind, order 0 (power series: ample precision for the Kaiser window)."""
    term = total = 1.0
    quarter = x * x / 4.0
    k = 1
    while term > 1e-17 * total:
        term *= quarter / (k * k)
        total += term
        k += 1
    return total


@dataclass(frozen=True)
class _Phase:
    offset: int  # index of the first tap relative to the newest input sample the output needs
    taps: tuple[float, ...]


@dataclass(frozen=True)
class _Bank:
    up: int
    down: int
    delay: int  # group delay of the prototype filter, in samples of the up-sampled signal
    phases: tuple[_Phase, ...]
    reach: int  # longest phase, which bounds how much zero padding a buffer needs


@lru_cache(maxsize=16)
def _bank(up: int, down: int) -> _Bank:
    """The polyphase filter bank that converts by ``up / down`` (coprime)."""
    longest = max(up, down)
    half = ZERO_CROSSINGS * longest
    length = 2 * half + 1
    window_norm = _bessel_i0(KAISER_BETA)
    proto = []
    for k in range(length):
        t = k - half
        sinc = 1.0 if t == 0 else math.sin(math.pi * t / longest) / (math.pi * t / longest)
        ratio = t / half
        window = _bessel_i0(KAISER_BETA * math.sqrt(max(0.0, 1.0 - ratio * ratio))) / window_norm
        proto.append(sinc * window)
    gain = up / sum(proto)  # each phase then sums to one: a constant signal keeps its level
    proto = [value * gain for value in proto]
    phases = []
    for r in range(up):
        # y[m] = sum_t proto[r + t * up] * x[q - t]; reversed, the taps line up with ascending sample indices
        taps = proto[r::up][::-1]
        top = max(abs(value) for value in taps)
        used = [i for i, value in enumerate(taps) if abs(value) > _TRIM * top]
        lo, hi = used[0], used[-1]
        phases.append(_Phase(offset=lo - len(taps) + 1, taps=tuple(taps[lo : hi + 1])))
    return _Bank(up=up, down=down, delay=half, phases=tuple(phases), reach=max(len(p.taps) - p.offset for p in phases))


def _samples(pcm: bytes) -> "array[int]":
    out = array("h")
    out.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        out.byteswap()
    return out


def _bytes(samples: "array[int]") -> bytes:
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tobytes()


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Convert little-endian PCM16 mono from ``src_rate`` to ``dst_rate`` Hz. A trailing odd byte is dropped."""
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("sample rates must be positive")
    samples = _samples(pcm)
    if src_rate == dst_rate or not samples:
        return _bytes(samples)
    divisor = math.gcd(src_rate, dst_rate)
    bank = _bank(dst_rate // divisor, src_rate // divisor)
    up, down = bank.up, bank.down
    count = len(samples)
    produced = -(-count * up // down)
    pad_left = bank.reach
    padded = [0.0] * pad_left
    padded.extend(map(float, samples))
    padded.extend([0.0] * (bank.delay // up + bank.reach + 2))
    out = array("h")
    append = out.append
    sumprod = math.sumprod
    phases = bank.phases
    delay = bank.delay
    for m in range(produced):
        newest, r = divmod(m * down + delay, up)
        phase = phases[r]
        start = newest + phase.offset + pad_left
        value = round(sumprod(phase.taps, padded[start : start + len(phase.taps)]))
        append(_PEAK if value > _PEAK else _FLOOR if value < _FLOOR else value)
    return _bytes(out)


def pcm16_rms(pcm: bytes) -> float:
    """Root-mean-square level of little-endian PCM16 mono, in sample units (0 for silence, up to 32768)."""
    samples = list(map(float, _samples(pcm)))
    if not samples:
        return 0.0
    return math.sqrt(math.sumprod(samples, samples) / len(samples))


def mix_to_mono_pcm16(pcm: bytes, channels: int) -> bytes:
    """Average interleaved PCM16 channels into one."""
    if channels < 1:
        raise ValueError("channels must be at least 1")
    samples = _samples(pcm)
    if channels == 1:
        return _bytes(samples)
    frames = len(samples) // channels
    mixed = array("h", (sum(samples[i * channels : (i + 1) * channels]) // channels for i in range(frames)))
    return _bytes(mixed)


__all__ = ["mix_to_mono_pcm16", "pcm16_rms", "resample_pcm16"]
