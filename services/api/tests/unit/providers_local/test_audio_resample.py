"""The pure-Python resampler behind the local speech providers: length, level, aliasing, edge cases, and SciPy parity."""

import math
from array import array

import pytest

from sparta.providers.audio_resample import mix_to_mono_pcm16, pcm16_rms, resample_pcm16
from sparta.providers.fake_tone import silence, tone


def samples(pcm: bytes) -> "array[int]":
    out = array("h")
    out.frombytes(pcm)
    return out


def amplitude_at(pcm: bytes, rate: int, freq_hz: float) -> float:
    """Amplitude of the ``freq_hz`` component of ``pcm`` (correlation with a sine and a cosine)."""
    data = samples(pcm)
    step = 2.0 * math.pi * freq_hz / rate
    re = sum(x * math.cos(step * i) for i, x in enumerate(data))
    im = sum(x * math.sin(step * i) for i, x in enumerate(data))
    return 2.0 * math.hypot(re, im) / len(data)


@pytest.mark.parametrize(
    ("src", "dst"),
    [(8000, 16000), (22050, 8000), (22050, 16000), (22050, 24000), (48000, 16000), (16000, 8000), (44100, 24000)],
)
@pytest.mark.parametrize("count", [1, 7, 1234])
def test_the_output_has_ceil_n_times_ratio_samples(src, dst, count):
    out = resample_pcm16(bytes(2 * count), src, dst)
    assert len(out) == 2 * math.ceil(count * dst / src)


@pytest.mark.parametrize(("src", "dst"), [(8000, 16000), (22050, 8000), (16000, 8000), (22050, 24000)])
def test_a_tone_in_the_pass_band_keeps_its_frequency_and_level(src, dst):
    out = resample_pcm16(tone(1000.0, 500, src, 10_000), src, dst)
    assert amplitude_at(out, dst, 1000.0) == pytest.approx(10_000, rel=0.02)
    assert amplitude_at(out, dst, 1500.0) < 200  # nothing leaks into a neighbouring frequency


def test_a_constant_level_is_preserved():
    data = array("h", [1500] * 3000).tobytes()
    for src, dst in [(8000, 16000), (22050, 8000)]:
        middle = samples(resample_pcm16(data, src, dst))
        core = middle[len(middle) // 4 : 3 * len(middle) // 4]
        assert min(core) >= 1498 and max(core) <= 1502


def test_content_above_the_new_nyquist_frequency_is_removed_before_decimation():
    out = resample_pcm16(tone(6000.0, 400, 22050, 10_000), 22050, 8000)  # 6 kHz cannot exist at 8 kHz
    assert amplitude_at(out, 8000, 2000.0) < 100  # its alias would land at 2 kHz
    assert pcm16_rms(out) < 100


def test_upsampling_adds_nothing_above_the_original_band():
    out = resample_pcm16(tone(1000.0, 500, 8000, 10_000), 8000, 16000)
    assert amplitude_at(out, 16000, 7000.0) < 100  # the image of 1 kHz at 7 kHz is suppressed


def test_up_then_down_returns_the_original_signal():
    original = tone(600.0, 400, 8000, 8000)
    mixed = array("h", [a + b for a, b in zip(samples(original), samples(tone(1700.0, 400, 8000, 4000)), strict=True)])
    back = samples(resample_pcm16(resample_pcm16(mixed.tobytes(), 8000, 16000), 16000, 8000))
    assert len(back) == len(mixed)
    worst = max(abs(a - b) for a, b in zip(mixed[40:-40], back[40:-40], strict=True))
    assert worst < 120  # about 1% of the 12,000 peak


def test_the_same_rate_is_a_copy_and_a_trailing_odd_byte_is_dropped():
    data = tone(440.0, 50, 8000)
    assert resample_pcm16(data, 8000, 8000) == data
    assert resample_pcm16(data + b"\x07", 8000, 8000) == data
    assert len(resample_pcm16(data + b"\x07", 8000, 16000)) == 2 * len(data)


def test_empty_input_and_invalid_rates():
    assert resample_pcm16(b"", 8000, 16000) == b""
    assert resample_pcm16(b"\x01", 8000, 16000) == b""
    for bad in ((0, 8000), (8000, 0), (-1, 8000)):
        with pytest.raises(ValueError):
            resample_pcm16(b"\x00\x00", *bad)


def test_full_scale_square_waves_saturate_instead_of_wrapping():
    square = array("h", ([32767] * 12 + [-32768] * 12) * 40).tobytes()
    for src, dst in [(8000, 16000), (22050, 8000)]:
        out = samples(resample_pcm16(square, src, dst))  # overshoot beyond int16 must clip, not raise or wrap
        assert max(out) <= 32767 and min(out) >= -32768
        assert max(out) > 30_000 and min(out) < -30_000


def test_silence_stays_silence():
    assert set(resample_pcm16(silence(100, 8000), 8000, 16000)) == {0}


def test_rms_and_mono_mix():
    assert pcm16_rms(b"") == 0.0
    assert pcm16_rms(silence(20, 8000)) == 0.0
    assert pcm16_rms(array("h", [1000] * 100).tobytes()) == pytest.approx(1000.0)
    stereo = array("h", [100, 300, -50, 50, 7, 9]).tobytes()
    assert list(samples(mix_to_mono_pcm16(stereo, 2))) == [200, 0, 8]
    assert mix_to_mono_pcm16(stereo, 1) == stereo
    with pytest.raises(ValueError):
        mix_to_mono_pcm16(stereo, 0)


@pytest.mark.parametrize(("src", "dst"), [(8000, 16000), (22050, 8000), (44100, 16000), (16000, 8000)])
def test_the_result_matches_scipy_resample_poly(src, dst):
    np = pytest.importorskip("numpy")
    signal = pytest.importorskip("scipy.signal")
    rng = np.random.default_rng(3)
    t = np.arange(int(src * 0.7)) / src
    wave = 6000 * np.sin(2 * np.pi * 440 * t) + 3000 * np.sin(2 * np.pi * 1700 * t) + 500 * rng.standard_normal(len(t))
    pcm = np.clip(wave, -32768, 32767).astype("<i2").tobytes()
    divisor = math.gcd(src, dst)
    expected = np.clip(
        np.round(signal.resample_poly(np.frombuffer(pcm, dtype="<i2").astype(float), dst // divisor, src // divisor)),
        -32768,
        32767,
    )
    actual = np.frombuffer(resample_pcm16(pcm, src, dst), dtype="<i2")
    assert len(actual) == len(expected)
    assert np.abs(actual - expected).max() <= 1  # the same filter: at most a rounding difference
