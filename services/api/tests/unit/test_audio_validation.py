"""Uploaded WAV files: the header walk is bounded and a lying header cannot hide a long recording."""

import struct
import time

import pytest

from sparta.providers.stt.azure import pcm16_to_wav, wav_duration_s
from sparta.services.audio_validation import MAX_WAV_CHUNKS, validate_audio, wav_duration
from sparta.services.errors import InvalidInput, PayloadTooLarge


def wav(seconds: float, *, rate: int = 16000, declared_byte_rate: int | None = None) -> bytes:
    pcm = b"\x00\x00" * int(rate * seconds)
    audio = bytearray(pcm16_to_wav(pcm, rate))
    if declared_byte_rate is not None:
        struct.pack_into("<I", audio, 28, declared_byte_rate)  # fmt chunk: byte rate
    return bytes(audio)


def test_a_normal_wav_reports_its_duration_and_passes():
    info = validate_audio(wav(2.0), "audio/wav", max_bytes=8_000_000, max_seconds=120)
    assert info.container == "wav" and info.duration_s == pytest.approx(2.0)


def test_a_header_that_lies_about_the_byte_rate_cannot_hide_a_long_recording():
    long_but_claims_to_be_short = wav(30.0, declared_byte_rate=0xFFFFFFFF)
    assert wav_duration(long_but_claims_to_be_short) == pytest.approx(30.0)
    assert wav_duration_s(long_but_claims_to_be_short) == pytest.approx(30.0)
    with pytest.raises(PayloadTooLarge):
        validate_audio(long_but_claims_to_be_short, "audio/wav", max_bytes=8_000_000, max_seconds=10)


def test_a_file_of_empty_chunks_is_rejected_quickly_instead_of_walked_to_the_end():
    junk = b"JUNK" + struct.pack("<I", 0)
    data = b"RIFF" + struct.pack("<I", 4) + b"WAVE" + junk * 900_000  # about 7 MB of zero-length chunks
    started = time.perf_counter()
    assert wav_duration(data) is None and wav_duration_s(data) is None
    with pytest.raises(InvalidInput):
        validate_audio(data, "audio/wav", max_bytes=8_000_000, max_seconds=120)
    assert time.perf_counter() - started < 0.5


def test_the_data_chunk_is_found_after_a_few_extra_header_chunks_but_not_after_many():
    extra = b"LIST" + struct.pack("<I", 4) + b"INFO"
    canonical = wav(1.0)
    header, rest = canonical[:12], canonical[12:]
    assert wav_duration(header + extra * 5 + rest) == pytest.approx(1.0)
    assert wav_duration(header + extra * (MAX_WAV_CHUNKS + 1) + rest) is None


def test_an_unreadable_wav_header_is_a_client_error_not_a_silent_pass():
    truncated = wav(1.0)[:30]
    with pytest.raises(InvalidInput):
        validate_audio(truncated, "audio/wav", max_bytes=8_000_000, max_seconds=120)
