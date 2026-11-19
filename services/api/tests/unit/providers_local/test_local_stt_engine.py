"""The faster-whisper engine behind the local recogniser, against a fake ``faster_whisper`` module: loading and wiring only."""

import logging
import os
import sys
import threading
import time
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from sparta.config import Settings
from sparta.providers import local_models
from sparta.providers.base import ProviderUnavailable
from sparta.providers.fake_tone import tone
from sparta.providers.local_models import ModelFile, ModelSpec, sha256_file
from sparta.providers.stt.local import FasterWhisperEngine, LocalSpeechToText, max_new_tokens

MODEL_NOT_INSTALLED = "model 'small' is not installed: run `python -m sparta models fetch`"


class FakeWhisperModel:
    """Records how it was built and used; answers with canned segments."""

    instances: ClassVar[list["FakeWhisperModel"]] = []
    build_delay = 0.0
    build_error: Exception | None = None
    segments: ClassVar[list[SimpleNamespace]] = []
    language_probs: ClassVar[list[tuple[str, float]]] = [("en", 0.9), ("hi", 0.05), ("kn", 0.05)]

    def __init__(self, model_size_or_path: str, **kwargs: Any) -> None:
        if FakeWhisperModel.build_delay:
            time.sleep(FakeWhisperModel.build_delay)
        if FakeWhisperModel.build_error is not None:
            raise FakeWhisperModel.build_error
        self.path = model_size_or_path
        self.kwargs = kwargs
        self.detect_calls: list[Any] = []
        self.transcribe_calls: list[tuple[Any, dict[str, Any]]] = []
        self.consumed = 0
        FakeWhisperModel.instances.append(self)

    def detect_language(self, audio: Any, **kwargs: Any) -> tuple[str, float, list[tuple[str, float]]]:
        self.detect_calls.append(audio)
        top = FakeWhisperModel.language_probs[0]
        return top[0], top[1], list(FakeWhisperModel.language_probs)

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Iterator[SimpleNamespace], object]:
        self.transcribe_calls.append((audio, kwargs))

        def segments() -> Iterator[SimpleNamespace]:
            for segment in FakeWhisperModel.segments:
                self.consumed += 1
                yield segment

        return segments(), SimpleNamespace(language=kwargs.get("language"), language_probability=1.0)


def segment(text: str, *, tokens: int = 3, logprob: float = -0.2, compression: float = 1.2, no_speech: float = 0.01):
    return SimpleNamespace(
        text=text,
        tokens=list(range(tokens)),
        avg_logprob=logprob,
        compression_ratio=compression,
        no_speech_prob=no_speech,
    )


@pytest.fixture(autouse=True)
def fake_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    FakeWhisperModel.instances = []
    FakeWhisperModel.build_delay = 0.0
    FakeWhisperModel.build_error = None
    FakeWhisperModel.segments = [segment(" hello"), segment("there ", tokens=2, logprob=-0.4)]
    FakeWhisperModel.language_probs = [("en", 0.9), ("hi", 0.05), ("kn", 0.05)]


@pytest.fixture
def numpy() -> Any:
    return pytest.importorskip("numpy")


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "my-whisper"
    folder.mkdir()
    (folder / "config.json").write_text("{}", encoding="utf-8")
    (folder / "model.bin").write_bytes(b"\x00" * 16)
    return folder


@pytest.fixture
def engine_for(make_settings: Callable[..., Settings]) -> Callable[..., FasterWhisperEngine]:
    def make(**overrides: object) -> FasterWhisperEngine:
        settings = make_settings(**overrides)
        return FasterWhisperEngine(settings, local_models.stt_location(settings))

    return make


def pcm(ms: int = 1000) -> bytes:
    return tone(440.0, ms, 16000, 8000)


# --------------------------------------------------------------------------------------------------- loading
def test_the_model_is_loaded_from_a_local_directory_only_and_never_by_name(engine_for, model_dir, no_network):
    engine = engine_for(local_stt_model=str(model_dir), local_stt_cpu_threads=3)
    assert engine.unavailable() is None
    engine.load()
    (model,) = FakeWhisperModel.instances
    assert model.path == str(model_dir)  # a path: faster-whisper never resolves a name through the hub
    assert model.kwargs == {
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": 3,
        "num_workers": 1,
        "local_files_only": True,
    }
    assert os.environ["HF_HUB_OFFLINE"] == "1" and no_network == []


def test_onnx_runtime_telemetry_is_switched_off_before_the_engine_is_imported_and_again_through_its_api(
    engine_for, model_dir, monkeypatch
):
    calls: list[str] = []
    ort = types.ModuleType("onnxruntime")
    ort.disable_telemetry_events = lambda: calls.append("disabled")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)

    class CheckingModel(FakeWhisperModel):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append(f"engine built with ORT_DISABLE_TELEMETRY={os.environ.get('ORT_DISABLE_TELEMETRY')}")
            super().__init__(*args, **kwargs)

    sys.modules["faster_whisper"].WhisperModel = CheckingModel  # type: ignore[attr-defined]
    engine_for(local_stt_model=str(model_dir)).load()
    assert calls == ["disabled", "engine built with ORT_DISABLE_TELEMETRY=1"]
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"


def test_an_operator_choice_for_the_engine_environment_is_respected(engine_for, model_dir, monkeypatch):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    engine_for(local_stt_model=str(model_dir)).load()
    assert (os.environ["ORT_DISABLE_TELEMETRY"], os.environ["HF_HUB_OFFLINE"]) == ("0", "0")


def test_the_device_compute_type_and_concurrency_follow_the_settings(engine_for, model_dir):
    engine_for(
        local_stt_model=str(model_dir),
        local_stt_device="auto",
        local_stt_compute_type="int8_float16",
        local_max_concurrent_inference=2,
    ).load()
    kwargs = FakeWhisperModel.instances[0].kwargs
    assert (kwargs["device"], kwargs["compute_type"], kwargs["num_workers"]) == ("auto", "int8_float16", 2)


def test_the_model_is_built_once_however_many_threads_ask_first(engine_for, model_dir):
    FakeWhisperModel.build_delay = 0.05
    engine = engine_for(local_stt_model=str(model_dir))
    threads = [threading.Thread(target=engine.load) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(FakeWhisperModel.instances) == 1


def test_a_model_that_is_not_installed_is_unavailable_with_the_fix_and_nothing_is_built(engine_for, no_network):
    engine = engine_for()
    assert engine.unavailable() == MODEL_NOT_INSTALLED
    with pytest.raises(ProviderUnavailable, match=MODEL_NOT_INSTALLED):
        engine.load()
    assert FakeWhisperModel.instances == [] and no_network == []


def test_the_startup_warning_says_what_is_missing(make_settings, caplog):
    with caplog.at_level(logging.WARNING, logger="sparta.local_stt"):
        LocalSpeechToText(make_settings())
    assert any(MODEL_NOT_INSTALLED in record.getMessage() for record in caplog.records)


def test_a_name_that_is_neither_in_the_manifest_nor_a_directory_is_reported_as_such(engine_for):
    problem = engine_for(local_stt_model="smal").unavailable()
    assert problem is not None and "unknown model 'smal'" in problem


def test_a_directory_without_a_model_is_not_installed(engine_for, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "lacks config.json or model.bin" in (engine_for(local_stt_model=str(empty)).unavailable() or "")


def test_a_manifest_model_counts_as_installed_only_when_every_file_has_the_pinned_size(
    engine_for, make_settings, monkeypatch, tmp_path
):
    spec = ModelSpec(
        key="small",
        kind="stt",
        repo="owner/repo",
        revision="a" * 40,
        files=(ModelFile("config.json", "0" * 64, 2), ModelFile("model.bin", "1" * 64, 16)),
        summary="",
        licence="",
        caveat="",
    )
    monkeypatch.setattr(local_models, "STT_MODELS", {"small": spec})
    folder = tmp_path / "models" / "stt" / "small"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}", encoding="utf-8")
    assert engine_for().unavailable() == MODEL_NOT_INSTALLED  # model.bin is missing
    (folder / "model.bin").write_bytes(b"\x00" * 15)
    assert engine_for().unavailable() == MODEL_NOT_INSTALLED  # truncated: one byte short
    (folder / "model.bin").write_bytes(b"\x00" * 16)
    engine = engine_for()
    assert engine.unavailable() is None
    engine.load()
    assert FakeWhisperModel.instances[0].path == str(folder)
    assert sha256_file(folder / "config.json")  # (the hashes are for ``models verify``: loading only checks sizes)


def test_a_model_that_fails_to_load_is_unavailable_without_leaking_details(engine_for, model_dir, caplog):
    FakeWhisperModel.build_error = RuntimeError(r"cannot open C:\secret\place\model.bin")
    engine = engine_for(local_stt_model=str(model_dir))
    with caplog.at_level(logging.ERROR, logger="sparta.local_stt"), pytest.raises(ProviderUnavailable) as raised:
        engine.load()
    assert "could not be loaded (RuntimeError)" in raised.value.message and "secret" not in raised.value.message
    assert any(r.exc_info for r in caplog.records)  # the details are logged for the operator
    FakeWhisperModel.build_error = None
    engine.load()  # a later attempt can succeed (the operator fixed the model)
    assert len(FakeWhisperModel.instances) == 1


def test_a_missing_faster_whisper_package_is_unavailable_with_the_fix(engine_for, model_dir, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # `import faster_whisper` now raises ImportError
    with pytest.raises(ProviderUnavailable, match=r"pip install 'sparta-api\[local-speech\]'"):
        engine_for(local_stt_model=str(model_dir)).load()


# ------------------------------------------------------------------------------------------- recognition
def test_a_forced_language_skips_detection_and_decodes_deterministically(engine_for, model_dir, numpy):
    engine = engine_for(local_stt_model=str(model_dir))
    found = engine.recognise(pcm(500), "hi", ("hi",))
    (model,) = FakeWhisperModel.instances
    assert model.detect_calls == []
    audio, options = model.transcribe_calls[0]
    assert audio.dtype == numpy.float32 and audio.shape == (8000,)
    assert float(abs(audio).max()) <= 1.0 and float(abs(audio).max()) > 0.1
    assert options["language"] == "hi" and options["task"] == "transcribe"
    assert options["temperature"] == 0.0 and options["condition_on_previous_text"] is False
    assert options["vad_filter"] is True and options["beam_size"] == 5
    assert options["max_new_tokens"] == 47  # 32 + 30 tokens per second x 0.5 s: a looping decoder is cut off early
    assert found.language == "hi"


@pytest.mark.parametrize(
    ("seconds", "limit"), [(0.0, 32), (-1.0, 32), (0.5, 47), (4.0, 152), (13.0, 400), (20.0, 400), (600.0, 400)]
)
def test_the_decoder_limit_scales_with_the_audio_and_stays_below_whispers_own(seconds, limit):
    assert max_new_tokens(seconds) == limit


def test_detection_is_restricted_to_the_candidates(engine_for, model_dir, numpy):
    FakeWhisperModel.language_probs = [("ur", 0.50), ("hi", 0.30), ("en", 0.15), ("kn", 0.05)]
    engine = engine_for(local_stt_model=str(model_dir))
    found = engine.recognise(pcm(500), None, ("en", "hi", "kn"))
    (model,) = FakeWhisperModel.instances
    assert len(model.detect_calls) == 1 and model.transcribe_calls[0][1]["language"] == "hi"
    assert found.language == "hi"
    FakeWhisperModel.language_probs = [("ur", 0.9), ("en", 0.05), ("kn", 0.05)]
    assert engine.recognise(pcm(500), None, ("en", "kn")).language == "en"  # a tie between candidates: the first


def test_segments_are_joined_and_their_logprobs_weighted_by_token_count(engine_for, model_dir, numpy):
    FakeWhisperModel.segments = [
        segment(" hello", tokens=3, logprob=-0.2),
        segment("   "),
        segment("world ", tokens=1, logprob=-1.0),
    ]
    found = engine_for(local_stt_model=str(model_dir)).recognise(pcm(), "en", ("en",))
    assert found.text == "hello world"
    assert found.mean_logprob == pytest.approx((-0.2 * 3 + -1.0 * 1) / 4)
    assert found.suspect is False
    assert (
        FakeWhisperModel.instances[0].consumed == 3
    )  # the generator was run to the end: that is where inference happens


@pytest.mark.parametrize(
    "bad",
    [segment("la la la la", compression=3.1), segment("thank you", no_speech=0.8)],
    ids=["repetition", "not speech"],
)
def test_whispers_failure_indicators_mark_the_recognition_suspect(engine_for, model_dir, numpy, bad):
    FakeWhisperModel.segments = [segment("fine"), bad]
    assert engine_for(local_stt_model=str(model_dir)).recognise(pcm(), "en", ("en",)).suspect is True


def test_no_segments_means_no_text_and_no_score(engine_for, model_dir, numpy):
    FakeWhisperModel.segments = []
    found = engine_for(local_stt_model=str(model_dir)).recognise(pcm(), "en", ("en",))
    assert (found.text, found.mean_logprob, found.suspect) == ("", None, False)


def test_warming_up_runs_both_the_decoder_and_the_voice_filter_once(engine_for, model_dir, numpy):
    engine = engine_for(local_stt_model=str(model_dir))
    engine.warm()
    (model,) = FakeWhisperModel.instances
    assert [options["vad_filter"] for _, options in model.transcribe_calls] == [False, True]
    assert all(options["max_new_tokens"] == 4 and options["language"] == "en" for _, options in model.transcribe_calls)
    assert model.consumed == 2 * len(FakeWhisperModel.segments)


async def test_the_provider_runs_the_real_engine_end_to_end_without_the_network(
    make_settings, model_dir, numpy, no_network
):
    FakeWhisperModel.segments = [segment(" I'm calling from your bank.", tokens=7, logprob=-0.1)]
    stt = LocalSpeechToText(make_settings(local_stt_model=str(model_dir)))
    try:
        stream = await stt.start_stream(candidate_locales=["en-IN"], locale_hint=None, trace_id="t", sample_rate=8000)
        await stream.push_audio(tone(440.0, 1500, 8000, 8000))
        await stream.flush()
        (event,) = [e async for e in stream.events()]
        assert (event.text, event.language) == ("I'm calling from your bank.", "en-IN")
        assert event.confidence == pytest.approx(0.904837, rel=1e-4)  # exp(-0.1), under the 0.95 English ceiling
        audio, options = FakeWhisperModel.instances[0].transcribe_calls[0]
        assert audio.shape == (24000,) and options["language"] == "en"  # 1.5 s at 16 kHz, one candidate: no detection
        assert no_network == []
    finally:
        await stt.aclose()
