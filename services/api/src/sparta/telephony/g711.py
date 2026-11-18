"""G.711 mu-law, the 8 kHz telephone audio format of Twilio Media Streams.

Pure Python on purpose: the standard library's ``audioop`` was removed in Python 3.13 and Sparta supports 3.12 and newer.
Decoding is a table lookup (256 entries); encoding exists for tests and for any provider whose synthesiser cannot emit
mu-law itself (the Azure voices can: ``raw-8khz-8bit-mono-mulaw``).
"""

import struct

_BIAS = 0x84
_CLIP = 32635


def _decode_sample(value: int) -> int:
    value = ~value & 0xFF
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0F
    sample = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return -sample if value & 0x80 else sample


# The little-endian 16-bit encoding of every possible mu-law byte.
_DECODED: tuple[bytes, ...] = tuple(struct.pack("<h", _decode_sample(i)) for i in range(256))


def ulaw_to_pcm16(data: bytes) -> bytes:
    """Mu-law bytes to little-endian signed 16-bit PCM (twice as many bytes)."""
    table = _DECODED
    return b"".join([table[b] for b in data])


def _encode_sample(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    magnitude = min(-sample if sample < 0 else sample, _CLIP) + _BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not magnitude & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def pcm16_to_ulaw(pcm: bytes) -> bytes:
    """Little-endian signed 16-bit PCM to mu-law bytes (half as many bytes). A trailing odd byte is ignored."""
    count = len(pcm) // 2
    return bytes([_encode_sample(s) for s in struct.unpack(f"<{count}h", pcm[: count * 2])])
