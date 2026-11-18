"""G.711 mu-law: the 8 kHz telephone format of Twilio Media Streams."""

import math
import struct

import pytest

from sparta.telephony.g711 import pcm16_to_ulaw, ulaw_to_pcm16


def samples(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


@pytest.mark.parametrize(
    ("ulaw", "pcm"),
    [(0xFF, 0), (0x7F, 0), (0x00, -32124), (0x80, 32124), (0x7E, -8), (0xFE, 8), (0xBF, 1980), (0x3F, -1980)],
)
def test_the_published_decoder_table_values(ulaw, pcm):
    assert samples(ulaw_to_pcm16(bytes([ulaw]))) == [pcm]


def test_decoding_doubles_the_length_and_a_frame_is_320_bytes():
    assert len(ulaw_to_pcm16(b"\xff" * 160)) == 320 and ulaw_to_pcm16(b"") == b""


def test_every_mulaw_byte_survives_a_round_trip_except_the_negative_zero():
    for value in range(256):
        again = pcm16_to_ulaw(ulaw_to_pcm16(bytes([value])))[0]
        assert again == value or (value == 0x7F and again == 0xFF), value  # +0 and -0 are the same sample


def test_encoding_a_sine_wave_stays_within_the_mulaw_quantisation_error():
    wave = [int(12000 * math.sin(2 * math.pi * 440 * n / 8000)) for n in range(800)]
    pcm = struct.pack(f"<{len(wave)}h", *wave)
    back = samples(ulaw_to_pcm16(pcm16_to_ulaw(pcm)))
    assert len(pcm16_to_ulaw(pcm)) == 800
    # mu-law is logarithmic: the error is at most about 3 % of the amplitude plus the bias
    assert all(abs(a - b) <= max(300, abs(a) * 0.04) for a, b in zip(wave, back, strict=True))


def test_extremes_and_odd_trailing_bytes_are_handled():
    assert pcm16_to_ulaw(struct.pack("<hh", 32767, -32768)) in (b"\x80\x00", b"\x80\x00")
    assert pcm16_to_ulaw(b"\x01") == b"" and pcm16_to_ulaw(b"\x00\x00\x01") == bytes([0xFF])
