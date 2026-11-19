"""``python -m sparta models list | fetch | verify``: readable output, honest exit codes, no URL or secret ever printed."""

import hashlib
from pathlib import Path

import httpx
import pytest

from sparta import cli
from sparta.config import Settings
from sparta.providers import local_models as lm
from sparta.providers.local_models import ModelFile, ModelSpec

STT_BYTES = {"config.json": b'{"a": 1}', "model.bin": bytes(range(256)) * 20}
VOICE_BYTES = {"hi_IN-test-medium.onnx": b"onnx" * 300, "hi_IN-test-medium.onnx.json": b"{}"}


def spec(key: str, kind: str, data: dict[str, bytes], **extra: object) -> ModelSpec:
    return ModelSpec(
        key=key,
        kind=kind,  # type: ignore[arg-type]
        repo="owner/repo",
        revision="d" * 40,
        files=tuple(ModelFile(n, hashlib.sha256(b).hexdigest(), len(b)) for n, b in data.items()),
        summary=f"The {key} test model",
        licence="MIT for tests",
        caveat="Experimental: tests only.",
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """A tiny manifest, a settings object pointing at a temporary directory, and a mock Hugging Face."""
    stt = spec("small", "stt", STT_BYTES)
    voice = spec("hi_IN-test-medium", "tts", VOICE_BYTES, language="hi", gender="female")
    monkeypatch.setattr(lm, "STT_MODELS", {"small": stt})
    monkeypatch.setattr(lm, "VOICES", {voice.key: voice})
    root = tmp_path / "models"
    settings = Settings(_env_file=None, local_model_dir=str(root), local_tts_voices="hi-IN=hi_IN-test-medium")
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    state: dict[str, object] = {"root": root, "requests": [], "tamper": False, "files": {**STT_BYTES, **VOICE_BYTES}}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)  # type: ignore[union-attr]
        name = request.url.path.rsplit("/", 1)[-1]
        if request.url.host == "huggingface.co":
            return httpx.Response(
                302, headers={"location": f"https://cdn-lfs.huggingface.co/x/{name}?X-Amz-Signature=SECRETSIGNATURE"}
            )
        body: bytes = state["files"][name]  # type: ignore[index]
        if state["tamper"]:
            body = b"\x00" * len(body)
        return httpx.Response(200, content=body)

    monkeypatch.setattr(
        lm, "new_client", lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    )
    return state


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


# ------------------------------------------------------------------------------------------------------ list
def test_list_shows_the_manifest_licences_and_what_is_missing(world, capsys):
    code, out, err = run(capsys, "models", "list")
    assert (code, err) == (0, "")
    assert "Speech-to-text (faster-whisper)" in out and "Text-to-speech voices (Piper)" in out
    assert "small" in out and "hi_IN-test-medium" in out and "[hi-IN]" in out
    assert "not installed: run `python -m sparta models fetch`" in out
    assert "Licence: MIT for tests" in out and "Experimental: tests only." in out
    assert "GPL-3.0-or-later" in out and "pip install 'sparta-api[local-speech]'" in out
    assert " * small" in out  # the model the settings use is starred


def test_list_reflects_what_is_installed_and_accepts_another_directory(world, capsys, tmp_path):
    assert run(capsys, "models", "fetch")[0] == 0
    capsys.readouterr()
    _, out, _ = run(capsys, "models", "list")
    assert out.count("installed (sizes match; SHA-256 not checked)") == 2
    _, elsewhere, _ = run(capsys, "models", "list", "--dir", str(tmp_path / "empty"))
    assert str(tmp_path / "empty") in elsewhere and "installed (sizes match" not in elsewhere


# ---------------------------------------------------------------------------------------------------- fetch
def test_fetch_downloads_what_the_settings_use_and_says_what_it_is_getting(world, capsys):
    code, out, err = run(capsys, "models", "fetch")
    assert (code, err) == (0, "")
    root = world["root"]
    assert (root / "stt" / "small" / "model.bin").read_bytes() == STT_BYTES["model.bin"]  # type: ignore[operator]
    assert (root / "tts" / "hi_IN-test-medium" / "hi_IN-test-medium.onnx").is_file()  # type: ignore[operator]
    assert "Licence: MIT for tests. Experimental: tests only." in out  # shown before anything is downloaded
    assert out.index("Licence: MIT for tests") < out.index("model.bin: 100%")
    assert "2 file(s) downloaded, 0 already present, all SHA-256 verified" in out and "models verify" in out
    assert "SECRETSIGNATURE" not in out and "huggingface" not in out  # no URL is ever printed
    requests_before = len(world["requests"])  # type: ignore[arg-type]
    code, out, _ = run(capsys, "models", "fetch")
    assert code == 0 and "already complete" in out and "0 file(s) downloaded, 2 already present" in out
    assert len(world["requests"]) == requests_before  # type: ignore[arg-type]  # nothing was requested again


def test_fetch_takes_models_and_voices_by_name_and_can_skip_either(world, capsys):
    assert run(capsys, "models", "fetch", "--stt", "none", "--voices", "none")[1].startswith("Nothing to fetch")
    code, out, _ = run(capsys, "models", "fetch", "--stt", "none", "--voices", "hi")
    assert code == 0 and "hi_IN-test-medium" in out and "small:" not in out
    assert not (world["root"] / "stt").exists()  # type: ignore[operator]
    code, out, _ = run(
        capsys, "models", "fetch", "--stt", "small", "--voices", "none", "--dir", str(world["root"] / "other")
    )  # type: ignore[operator]
    assert code == 0 and (world["root"] / "other" / "stt" / "small" / "config.json").is_file()  # type: ignore[operator]


def test_fetch_refuses_unknown_names_before_downloading_anything(world, capsys):
    code, out, err = run(capsys, "models", "fetch", "--voices", "fr")
    assert code == 2 and out == "" and "unknown voice 'fr'" in err
    code, _, err = run(capsys, "models", "fetch", "--stt", "huge")
    assert code == 2 and "unknown speech-to-text model 'huge'" in err
    assert world["requests"] == []


def test_a_download_that_does_not_match_its_pin_fails_loudly_and_installs_nothing(world, capsys):
    world["tamper"] = True
    code, out, err = run(capsys, "models", "fetch", "--voices", "none")
    assert code == 1 and "error: " in err and "SHA-256 mismatch" in err
    assert "SECRETSIGNATURE" not in out + err and "X-Amz" not in out + err
    folder = world["root"] / "stt" / "small"  # type: ignore[operator]
    assert not any(folder.glob("*.part")) and not (folder / "config.json").exists()


def test_a_directory_that_cannot_be_written_is_a_readable_error_not_a_traceback(world, capsys, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("in the way", encoding="utf-8")
    code, _, err = run(capsys, "models", "fetch", "--dir", str(blocker))
    assert code == 1 and err.startswith("error: could not write to") and "Traceback" not in err


# --------------------------------------------------------------------------------------------------- verify
def test_verify_with_nothing_installed_says_so(world, capsys):
    code, out, _ = run(capsys, "models", "verify")
    assert code == 0 and "nothing is installed yet" in out


def test_verify_passes_for_good_files_and_fails_for_a_changed_one(world, capsys):
    run(capsys, "models", "fetch")
    capsys.readouterr()
    code, out, _ = run(capsys, "models", "verify")
    assert code == 0 and "OK       small: installed, SHA-256 verified" in out and "OK       hi_IN-test-medium" in out
    (world["root"] / "stt" / "small" / "model.bin").write_bytes(b"\x00" * len(STT_BYTES["model.bin"]))  # type: ignore[operator]
    code, out, _ = run(capsys, "models", "verify")
    assert code == 1 and "FAILED   small: CORRUPT" in out and "model.bin does not match the pinned SHA-256" in out
    assert "OK       hi_IN-test-medium" in out  # the other model is still fine


def test_verify_flags_a_half_installed_model(world, capsys):
    run(capsys, "models", "fetch", "--voices", "none")
    capsys.readouterr()
    (world["root"] / "stt" / "small" / "model.bin").unlink()  # type: ignore[operator]
    code, out, _ = run(capsys, "models", "verify")
    assert code == 1 and "FAILED   small: incomplete (model.bin is missing)" in out


# ---------------------------------------------------------------------------------------------------- usage
def test_the_group_needs_a_subcommand_and_has_help(capsys):
    with pytest.raises(SystemExit) as raised:
        cli.main(["models"])
    assert raised.value.code == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as helped:
        cli.main(["models", "--help"])
    assert helped.value.code == 0
    out = capsys.readouterr().out
    assert "list" in out and "fetch" in out and "verify" in out and "never download" in out
    with pytest.raises(SystemExit):
        cli.main(["models", "fetch", "--help"])
    assert "--stt" in capsys.readouterr().out
