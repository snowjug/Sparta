"""Settings and provider wiring for the local speech providers: parsing, validation, optional-package failures."""

import importlib.util

import pytest
from pydantic import ValidationError

from sparta.clock import VirtualClock
from sparta.config import ConfigurationError, Settings
from sparta.observability.metrics import Metrics
from sparta.providers.base import consumes_audio, produces_audio
from sparta.providers.stt.local import LocalSpeechToText
from sparta.providers.tts.local import LocalTextToSpeech
from sparta.services.providers import build_providers

PIP_HINT = "pip install 'sparta-api[local-speech]'"
ENV = (
    "SPARTA_LOCAL_MODEL_DIR",
    "SPARTA_LOCAL_STT_MODEL",
    "SPARTA_LOCAL_STT_DEVICE",
    "SPARTA_LOCAL_STT_COMPUTE_TYPE",
    "SPARTA_LOCAL_STT_CPU_THREADS",
    "SPARTA_LOCAL_TTS_VOICES",
    "SPARTA_LOCAL_TTS_FALLBACK_LOCALE",
    "SPARTA_LOCAL_MAX_CONCURRENT_INFERENCE",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def packages_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend neither optional engine is installed, whatever this environment has."""
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name in {"faster_whisper", "piper"} else real(name, *a)
    )


@pytest.fixture
def packages_present(monkeypatch: pytest.MonkeyPatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: object() if name in {"faster_whisper", "piper"} else real(name, *a),
    )


# ------------------------------------------------------------------------------------------------ the settings
def test_the_defaults_are_the_documented_ones():
    s = settings()
    assert s.local_model_dir == "./var/models" and s.local_stt_model == "small"
    assert (s.local_stt_device, s.local_stt_compute_type, s.local_stt_cpu_threads) == ("cpu", "int8", 4)
    assert s.local_tts_voices == [
        "en-IN=en_US-ljspeech-medium",
        "hi-IN=hi_IN-priyamvada-medium",
        "kn-IN=kn_IN-syspin_male-medium",
    ]
    assert s.local_tts_voice_map == {
        "en-IN": "en_US-ljspeech-medium",
        "hi-IN": "hi_IN-priyamvada-medium",
        "kn-IN": "kn_IN-syspin_male-medium",
    }
    assert (s.local_tts_fallback_locale, s.local_max_concurrent_inference) == ("en-IN", 1)
    assert (s.stt_provider, s.tts_provider) == ("simulator", "simulator")  # nothing local is on by default


def test_every_setting_reads_its_sparta_environment_variable(monkeypatch):
    monkeypatch.setenv("SPARTA_LOCAL_MODEL_DIR", "/models")
    monkeypatch.setenv("SPARTA_LOCAL_STT_MODEL", "large-v3-turbo")
    monkeypatch.setenv("SPARTA_LOCAL_STT_DEVICE", "auto")
    monkeypatch.setenv("SPARTA_LOCAL_STT_COMPUTE_TYPE", "int8_float16")
    monkeypatch.setenv("SPARTA_LOCAL_STT_CPU_THREADS", "8")
    monkeypatch.setenv("SPARTA_LOCAL_TTS_VOICES", "en-IN=a_voice, hi-IN=b_voice ,")
    monkeypatch.setenv("SPARTA_LOCAL_TTS_FALLBACK_LOCALE", "hi-IN")
    monkeypatch.setenv("SPARTA_LOCAL_MAX_CONCURRENT_INFERENCE", "2")
    s = settings()
    assert (s.local_model_dir, s.local_stt_model, s.local_stt_device) == ("/models", "large-v3-turbo", "auto")
    assert (s.local_stt_compute_type, s.local_stt_cpu_threads) == ("int8_float16", 8)
    assert s.local_tts_voices == ["en-IN=a_voice", "hi-IN=b_voice"] and s.local_tts_voice_map == {
        "en-IN": "a_voice",
        "hi-IN": "b_voice",
    }
    assert (s.local_tts_fallback_locale, s.local_max_concurrent_inference) == ("hi-IN", 2)


@pytest.mark.parametrize(
    "bad",
    [
        {"local_stt_cpu_threads": 0},
        {"local_stt_cpu_threads": 33},
        {"local_max_concurrent_inference": 0},
        {"local_max_concurrent_inference": 5},
        {"local_stt_device": "tpu"},
    ],
)
def test_out_of_range_values_are_refused(bad):
    with pytest.raises(ValidationError):
        settings(**bad)


def test_a_blank_fallback_locale_means_none(monkeypatch):
    assert settings(local_tts_fallback_locale="  ").local_tts_fallback_locale is None
    monkeypatch.setenv("SPARTA_LOCAL_TTS_FALLBACK_LOCALE", "")
    assert settings().local_tts_fallback_locale is None


def test_the_voice_map_normalises_locales_and_skips_what_is_malformed():
    s = settings(local_tts_voices="EN-in=one,hi-IN=two,nonsense,kn-IN=,ta-IN=bad/voice,en-IN=again,zh-Hant-TW=x")
    assert s.local_tts_voice_map == {"en-IN": "one", "hi-IN": "two"}


# ---------------------------------------------------------------------------------------------- problems()
def test_a_missing_engine_is_a_startup_problem_with_the_fix(packages_missing):
    stt_only = settings(stt_provider="local").problems()
    assert any("faster-whisper" in p and PIP_HINT in p and p.startswith("SPARTA_STT_PROVIDER=local") for p in stt_only)
    assert not any("piper" in p for p in stt_only)
    tts_only = settings(tts_provider="local").problems()
    assert any("piper-tts" in p and PIP_HINT in p and p.startswith("SPARTA_TTS_PROVIDER=local") for p in tts_only)
    both = settings(stt_provider="local", tts_provider="local").problems()
    assert sum(PIP_HINT in p for p in both) == 2


def test_nothing_is_checked_for_providers_that_are_not_local(packages_missing):
    s = settings(local_stt_model="not a model", local_tts_voices="garbage")
    assert s.problems() == []


def test_a_configuration_with_the_engines_present_and_valid_values_has_no_problem(packages_present, tmp_path):
    assert settings(stt_provider="local", tts_provider="local").problems() == []
    folder = tmp_path / "custom-model"
    folder.mkdir()
    assert settings(stt_provider="local", local_stt_model=str(folder)).problems() == []
    assert settings(stt_provider="local", local_stt_model="large-v3-turbo").problems() == []


def test_a_mistyped_or_empty_model_name_is_a_problem(packages_present):
    for bad in ("smal", "", "   ", "/does/not/exist"):
        problems = settings(stt_provider="local", local_stt_model=bad).problems()
        assert any("SPARTA_LOCAL_STT_MODEL" in p and "small, large-v3-turbo" in p for p in problems), bad


def test_malformed_voice_entries_are_problems(packages_present):
    problems = settings(tts_provider="local", local_tts_voices="en-IN=ok,hindi,hi-IN=../x,en-IN=twice").problems()
    assert sum("SPARTA_LOCAL_TTS_VOICES entry" in p for p in problems) == 3
    assert any("'hindi'" in p for p in problems) and any("'hi-IN=../x'" in p for p in problems)
    assert any(
        "must name at least one" in p for p in settings(tts_provider="local", local_tts_voices="nonsense").problems()
    )


def test_problems_from_the_other_guards_are_left_as_they_were(packages_present):
    problems = settings(stt_provider="local", telephony_provider="asterisk").problems()
    assert any("SPARTA_ASTERISK_WEBHOOK_SECRET" in p for p in problems)  # still reported alongside


# ----------------------------------------------------------------------------------------------- the factory
def build(**overrides: object):
    return build_providers(settings(**overrides), clock=VirtualClock(), metrics=Metrics())


@pytest.mark.parametrize(
    ("overrides", "package"),
    [({"stt_provider": "local"}, "faster-whisper"), ({"tts_provider": "local"}, "piper-tts")],
)
def test_the_factory_fails_at_startup_with_the_fix_when_an_engine_is_missing(
    packages_missing, tmp_path, overrides, package
):
    with pytest.raises(ConfigurationError) as raised:
        build(local_model_dir=str(tmp_path), **overrides)
    assert package in str(raised.value) and PIP_HINT in str(raised.value) and "=local requires" in str(raised.value)


async def test_the_factory_builds_the_local_providers_without_importing_an_engine(packages_present, tmp_path):
    providers = build(local_model_dir=str(tmp_path), stt_provider="local", tts_provider="local")
    assert isinstance(providers.stt, LocalSpeechToText) and isinstance(providers.tts, LocalTextToSpeech)
    assert consumes_audio(providers.stt) is True and produces_audio(providers.tts) is True
    assert providers.stt.meta.provider == "local-faster-whisper" and providers.tts.meta.provider == "local-piper"
    assert providers.tts.meta.model == "en_US-ljspeech-medium,hi_IN-priyamvada-medium,kn_IN-syspin_male-medium"
    assert providers.stt.ready() is not None  # no model has been fetched into the empty directory
    await providers.aclose()  # closes the recogniser and the synthesiser
    assert providers.stt._closed and providers.tts._closed


async def test_the_other_choices_are_untouched(tmp_path):
    providers = build(local_model_dir=str(tmp_path))
    assert providers.stt.meta.simulated and providers.tts.meta.simulated
    fake = build(stt_provider="fake", tts_provider="fake")
    assert fake.stt.meta.provider == "fake-tone" and fake.tts.meta.provider == "fake-tone"
