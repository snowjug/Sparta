"""The model manifest and its tooling: pins, hash verification, hardened downloads (against a mock server), status."""

import hashlib
import os
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from sparta.config import Settings
from sparta.providers import local_models as lm
from sparta.providers.local_models import (
    STT_MODELS,
    VOICES,
    ModelFetchError,
    ModelFile,
    ModelSpec,
    default_selection,
    fetch_models,
    host_allowed,
    install_spec,
    missing_files,
    model_status,
    resolve_stt,
    resolve_voices,
    sha256_file,
    spec_dir,
    stt_location,
    verify_spec,
    voice_files,
)

CONTENT = {"config.json": b'{"a": 1}', "model.bin": bytes(range(256)) * 40}


def spec_for(files: dict[str, bytes] = CONTENT, *, key: str = "tiny", kind: str = "stt") -> ModelSpec:
    return ModelSpec(
        key=key,
        kind=kind,  # type: ignore[arg-type]
        repo="owner/repo",
        revision="c" * 40,
        files=tuple(ModelFile(name, hashlib.sha256(data).hexdigest(), len(data)) for name, data in files.items()),
        summary="a tiny test model",
        licence="MIT",
        caveat="only for tests",
    )


class Server:
    """A mock Hugging Face: serves ``files`` by path, optionally through a redirect to a CDN host, and logs the requests."""

    def __init__(self, files: dict[str, bytes] = CONTENT, *, redirect_to: str | None = None) -> None:
        self.files = files
        self.redirect_to = redirect_to
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        name = request.url.path.rsplit("/", 1)[-1]
        if self.redirect_to and request.url.host == "huggingface.co":
            return httpx.Response(
                302, headers={"location": f"{self.redirect_to}/blob/{name}?X-Amz-Signature=SECRETSIGNATURE"}
            )
        if name in self.files:
            return httpx.Response(200, content=self.files[name])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=False)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "models"


# ------------------------------------------------------------------------------------------------ the manifest
def test_every_manifest_entry_is_pinned_by_commit_and_by_sha256_and_size():
    assert set(STT_MODELS) == {"small", "large-v3-turbo"} and len(VOICES) == 3
    for spec in (*STT_MODELS.values(), *VOICES.values()):
        assert len(spec.revision) == 40 and set(spec.revision) <= set("0123456789abcdef")
        assert spec.files and spec.licence and spec.caveat and spec.summary
        for file in spec.files:
            assert len(file.sha256) == 64 and set(file.sha256) <= set("0123456789abcdef") and file.size > 0
            url = spec.url(file)
            assert url.startswith(f"https://huggingface.co/{spec.repo}/resolve/{spec.revision}/") and ".." not in url
        names = {f.name for f in spec.files}
        if spec.kind == "stt":
            assert {"config.json", "model.bin", "tokenizer.json"} <= names and any(
                n.startswith("vocabulary.") for n in names
            )
        else:
            assert names == {f"{spec.key}.onnx", f"{spec.key}.onnx.json"} and spec.language and spec.gender


def test_the_pins_are_the_ones_the_research_recorded():
    turbo = {f.name: f for f in STT_MODELS["large-v3-turbo"].files}
    assert STT_MODELS["large-v3-turbo"].revision == "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
    assert turbo["model.bin"].sha256 == "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"
    assert STT_MODELS["small"].repo == "Systran/faster-whisper-small"
    assert STT_MODELS["small"].revision == "536b0662742c02347bc0e980a01041f333bce120"
    expected = {
        "en_US-ljspeech-medium": (
            "rhasspy/piper-voices",
            "04ca88f5685ca5253c701af3687e155b113bd512",
            "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
        ),
        "hi_IN-priyamvada-medium": (
            "rhasspy/piper-voices",
            "04ca88f5685ca5253c701af3687e155b113bd512",
            "aa63bcf2cd493b55a450f280e23cf77f03afc9af7015e6e5acd43b652f166c88",
        ),
        "kn_IN-syspin_male-medium": (
            "micahchoo/piper-kn",
            "c73546cb70012e28f6093a61c71162924398fee1",
            "bff423259625c0c1182e5b417f68560b6a55f3c4d27557a6abf2fbe51e7e00ee",
        ),
    }
    for key, (repo, revision, onnx_sha) in expected.items():
        spec = VOICES[key]
        assert (spec.repo, spec.revision) == (repo, revision)
        assert next(f for f in spec.files if f.name.endswith(".onnx")).sha256 == onnx_sha


def test_the_licence_caveats_are_stated_per_entry():
    assert "CC-BY-NC-SA-4.0" in VOICES["hi_IN-priyamvada-medium"].licence
    assert "non-commercial" in VOICES["kn_IN-syspin_male-medium"].licence.lower()
    assert "non-commercial" in VOICES["kn_IN-syspin_male-medium"].caveat.lower()
    assert "US English" in VOICES["en_US-ljspeech-medium"].caveat
    assert "GPL-3.0-or-later" in lm.ENGINE_NOTE and "third-party" in STT_MODELS["large-v3-turbo"].caveat


@pytest.mark.parametrize(
    "make",
    [
        lambda: ModelFile("../model.bin", "a" * 64, 1),
        lambda: ModelFile("sub/model.bin", "a" * 64, 1),
        lambda: ModelFile("..", "a" * 64, 1),
        lambda: ModelFile("model.bin", "A" * 64, 1),  # upper-case hex is not what the manifest holds
        lambda: ModelFile("model.bin", "a" * 63, 1),
        lambda: ModelFile("model.bin", "a" * 64, 0),
        lambda: ModelFile("model.bin", "a" * 64, lm.MAX_FILE_BYTES + 1),
        lambda: ModelSpec(
            "k", "stt", "o/r", "main", (ModelFile("f", "a" * 64, 1),), "", "", ""
        ),  # a branch, not a commit
        lambda: ModelSpec("k", "stt", "o/r", "a" * 40, (), "", "", ""),
    ],
)
def test_a_malformed_manifest_entry_cannot_be_constructed(make):
    with pytest.raises(ValueError):
        make()


@pytest.mark.parametrize("voice", ["../x", "a/b", "a\\b", "", ".hidden", "x" * 65, "a b"])
def test_a_voice_id_can_never_be_a_path(voice, root):
    with pytest.raises(ValueError):
        voice_files(root, voice)


def test_voice_files_live_under_the_tts_folder(root):
    onnx, config = voice_files(root, "hi_IN-priyamvada-medium")
    assert onnx == root / "tts" / "hi_IN-priyamvada-medium" / "hi_IN-priyamvada-medium.onnx"
    assert config.name == "hi_IN-priyamvada-medium.onnx.json"
    assert spec_dir(root, STT_MODELS["small"]) == root / "stt" / "small"


# --------------------------------------------------------------------------------------------- hosts allowed
@pytest.mark.parametrize(
    "host",
    [
        "huggingface.co",
        "HuggingFace.co",
        "hf.co",
        "cas-bridge.xethub.hf.co",
        "cdn-lfs.hf.co",
        "cdn-lfs-us-1.hf.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs-eu-1.huggingface.co",
    ],
)
def test_hugging_face_hosts_are_allowed(host):
    assert host_allowed(host)


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "huggingface.co.evil.example",
        "evilhf.co",
        "nothf.co",
        "cdn-lfs.huggingface.co.evil.example",
        "xhuggingface.co",
        "cdn.huggingface.co",
        "localhost",
        "127.0.0.1",
        "",
    ],
)
def test_other_hosts_are_not(host):
    assert not host_allowed(host)


# ----------------------------------------------------------------------------------------------- downloads
def test_a_download_lands_complete_and_verified_with_no_temporary_file_left(root):
    server = Server()
    spec = spec_for()
    seen: list[tuple[str, int, int]] = []
    result = install_spec(
        spec, root, client=server.client(), progress=lambda label, done, total: seen.append((label, done, total))
    )
    assert result == [("config.json", "downloaded"), ("model.bin", "downloaded")]
    folder = spec_dir(root, spec)
    assert sorted(p.name for p in folder.iterdir()) == ["config.json", "model.bin"]
    assert (folder / "model.bin").read_bytes() == CONTENT["model.bin"] and verify_spec(spec, folder) == []
    assert seen[-1] == ("tiny/model.bin", len(CONTENT["model.bin"]), len(CONTENT["model.bin"]))
    first = server.requests[0]
    assert first.url.host == "huggingface.co" and first.url.path == f"/owner/repo/resolve/{'c' * 40}/config.json"
    assert "authorization" not in first.headers and "cookie" not in first.headers
    assert first.headers["accept-encoding"] == "identity"


def test_redirects_to_the_cdn_are_followed_hop_by_hop_and_never_leak_their_signature(root, capsys):
    server = Server(redirect_to="https://cdn-lfs.huggingface.co")
    install_spec(spec_for(), root, client=server.client())
    assert [r.url.host for r in server.requests] == ["huggingface.co", "cdn-lfs.huggingface.co"] * 2
    assert all(b"SECRETSIGNATURE" not in r.url.raw_path for r in server.requests[::2])
    bad = Server(
        {"config.json": b"tampered!", "model.bin": CONTENT["model.bin"]}, redirect_to="https://cas-bridge.xethub.hf.co"
    )
    with pytest.raises(ModelFetchError) as raised:
        install_spec(spec_for(), root / "other", client=bad.client())
    assert "SECRETSIGNATURE" not in str(raised.value) and "X-Amz" not in str(raised.value)


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/model.bin",
        "http://huggingface.co/owner/repo/resolve/x/model.bin",  # plain http
        "https://user:pw@huggingface.co/model.bin",  # credentials in the URL
        "https://huggingface.co:8443/model.bin",  # another port
        "https://huggingface.co.evil.example/model.bin",
        "ftp://huggingface.co/model.bin",
    ],
)
def test_a_redirect_anywhere_else_is_refused_and_never_requested(root, location):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": location})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(ModelFetchError, match="refusing"):
        install_spec(spec_for(), root, client=client)
    assert len(requests) == 1  # only the first hop was ever requested
    assert (
        not any(spec_dir(root, spec_for()).glob("*.part")) and not (spec_dir(root, spec_for()) / "config.json").exists()
    )


def test_redirect_loops_and_destinationless_redirects_end_in_an_error(root):
    loop = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "https://huggingface.co/again"})
        ),
        follow_redirects=False,
    )
    with pytest.raises(ModelFetchError, match="too many redirects"):
        install_spec(spec_for(), root, client=loop)
    nowhere = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(302)), follow_redirects=False)
    with pytest.raises(ModelFetchError, match="no destination"):
        install_spec(spec_for(), root, client=nowhere)


def test_a_file_with_the_wrong_hash_is_deleted_and_never_installed(root):
    server = Server({"config.json": CONTENT["config.json"], "model.bin": b"x" * len(CONTENT["model.bin"])})
    spec = spec_for()
    with pytest.raises(ModelFetchError, match="SHA-256 mismatch"):
        install_spec(spec, root, client=server.client())
    folder = spec_dir(root, spec)
    assert sorted(p.name for p in folder.iterdir()) == [
        "config.json"
    ]  # the good file stays, the bad one is gone, no .part


@pytest.mark.parametrize(
    ("body", "message"),
    [(CONTENT["model.bin"][:-1], "announced"), (CONTENT["model.bin"] + b"!", "announced")],
    ids=["short", "long"],
)
def test_a_body_that_is_not_the_pinned_size_is_refused_from_its_announced_length(root, body, message):
    server = Server({"config.json": CONTENT["config.json"], "model.bin": body})
    with pytest.raises(ModelFetchError, match=message):
        install_spec(spec_for(), root, client=server.client())
    assert not list(spec_dir(root, spec_for()).glob("*.part"))


def test_a_stream_without_a_length_is_cut_off_when_it_exceeds_the_pinned_size_or_stops_short(root):
    def chunked(total: int) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            def body() -> Iterator[bytes]:
                for _ in range(total // 100):
                    yield b"z" * 100

            return httpx.Response(200, content=body())

        return handler

    spec = spec_for({"model.bin": b"z" * 1000})
    for sent, message in [(5000, "more data than"), (500, "received 500 bytes")]:
        client = httpx.Client(transport=httpx.MockTransport(chunked(sent)), follow_redirects=False)
        with pytest.raises(ModelFetchError, match=message):
            install_spec(spec, root, client=client)
        assert list(spec_dir(root, spec).iterdir()) == []


def test_server_and_network_errors_are_reported_without_a_url(root):
    with pytest.raises(ModelFetchError, match="HTTP 404"):
        install_spec(spec_for({"missing.bin": b"x"}), root, client=Server({}).client())

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure for huggingface.co", request=request)

    with pytest.raises(ModelFetchError, match=r"network error while downloading \(ConnectError\)") as raised:
        install_spec(spec_for(), root, client=httpx.Client(transport=httpx.MockTransport(broken)))
    assert "huggingface" not in str(raised.value)


def test_a_complete_file_is_not_downloaded_again_but_a_corrupt_one_is_replaced(root):
    spec = spec_for()
    folder = spec_dir(root, spec)
    folder.mkdir(parents=True)
    (folder / "config.json").write_bytes(CONTENT["config.json"])
    (folder / "model.bin").write_bytes(b"\xff" * len(CONTENT["model.bin"]))  # the right size, the wrong bytes
    (folder / "model.bin.part").write_bytes(b"left over from an interrupted download")
    server = Server()
    result = install_spec(spec, root, client=server.client())
    assert result == [("config.json", "present"), ("model.bin", "downloaded")]
    assert [r.url.path.rsplit("/", 1)[-1] for r in server.requests] == ["model.bin"]
    assert verify_spec(spec, folder) == [] and not list(folder.glob("*.part"))


def test_fetching_checks_the_disk_space_first_and_installs_every_spec(root, monkeypatch):
    server = Server()
    spec = spec_for()
    monkeypatch.setattr(lm, "free_bytes", lambda path: 100)
    with pytest.raises(ModelFetchError, match="not enough free disk space"):
        fetch_models([spec], root, client=server.client())
    assert server.requests == []
    monkeypatch.setattr(lm, "free_bytes", lambda path: 10**12)
    assert fetch_models([spec], root, client=server.client()) == {
        "tiny": [("config.json", "downloaded"), ("model.bin", "downloaded")]
    }
    assert fetch_models([spec], root, client=Server({}).client()) == {
        "tiny": [("config.json", "present"), ("model.bin", "present")]
    }


def test_pending_bytes_counts_only_what_is_missing(root):
    spec = spec_for()
    assert lm.pending_bytes(spec, root) == spec.total_bytes
    folder = spec_dir(root, spec)
    folder.mkdir(parents=True)
    (folder / "config.json").write_bytes(CONTENT["config.json"])
    assert lm.pending_bytes(spec, root) == len(CONTENT["model.bin"])


# ------------------------------------------------------------------------------------------- verification
def test_verification_finds_missing_short_and_altered_files(root):
    spec = spec_for()
    folder = spec_dir(root, spec)
    folder.mkdir(parents=True)
    assert missing_files(spec, folder) == ["config.json is missing", "model.bin is missing"]
    (folder / "config.json").write_bytes(CONTENT["config.json"])
    (folder / "model.bin").write_bytes(b"short")
    assert missing_files(spec, folder) == [f"model.bin has 5 bytes, expected {len(CONTENT['model.bin'])}"]
    (folder / "model.bin").write_bytes(b"\x00" * len(CONTENT["model.bin"]))
    assert missing_files(spec, folder) == [] and verify_spec(spec, folder) == [
        "model.bin does not match the pinned SHA-256"
    ]
    (folder / "model.bin").write_bytes(CONTENT["model.bin"])
    assert verify_spec(spec, folder) == []
    assert sha256_file(folder / "model.bin") == hashlib.sha256(CONTENT["model.bin"]).hexdigest()


# ------------------------------------------------------------------------------------------------ settings
def test_the_engine_environment_is_offline_and_without_telemetry_unless_the_operator_says_otherwise(monkeypatch):
    for name in ("HF_HUB_OFFLINE", "ORT_DISABLE_TELEMETRY"):
        monkeypatch.delenv(name, raising=False)
    lm.prepare_engine_environment()
    assert (os.environ["HF_HUB_OFFLINE"], os.environ["ORT_DISABLE_TELEMETRY"]) == ("1", "1")
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    lm.prepare_engine_environment()
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "0"  # an explicit choice is never overridden


def test_the_telemetry_api_opt_out_is_best_effort(monkeypatch):
    calls: list[str] = []
    ort = types.ModuleType("onnxruntime")
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    lm.disable_onnxruntime_telemetry()  # a build without the call: nothing happens
    ort.disable_telemetry_events = lambda: calls.append("called")  # type: ignore[attr-defined]
    lm.disable_onnxruntime_telemetry()
    assert calls == ["called"]

    def explode() -> None:
        raise RuntimeError("telemetry library is unhappy")

    ort.disable_telemetry_events = explode  # type: ignore[attr-defined]
    lm.disable_onnxruntime_telemetry()  # an opt-out must never stop the engine from starting
    monkeypatch.setitem(sys.modules, "onnxruntime", None)  # not installed at all
    lm.disable_onnxruntime_telemetry()


def settings_for(root: Path, **overrides: object) -> Settings:
    return Settings(_env_file=None, local_model_dir=str(root), **overrides)


def test_the_stt_model_setting_is_a_manifest_name_or_a_directory(root, tmp_path):
    small = stt_location(settings_for(root))
    assert (small.name, small.path, small.known) == (
        "small",
        root / "stt" / "small",
        True,
    ) and small.spec is STT_MODELS["small"]
    folder = tmp_path / "my-model"
    folder.mkdir()
    custom = stt_location(settings_for(root, local_stt_model=str(folder)))
    assert (custom.name, custom.path, custom.spec, custom.known) == ("my-model", folder, None, True)
    for typo in ("smal", "", "   "):
        unknown = stt_location(settings_for(root, local_stt_model=typo))
        assert unknown.known is False and unknown.spec is None


def test_the_default_selection_is_what_the_settings_use(root):
    stt, voices = default_selection(settings_for(root))
    assert [s.key for s in stt] == ["small"]
    assert [v.key for v in voices] == ["en_US-ljspeech-medium", "hi_IN-priyamvada-medium", "kn_IN-syspin_male-medium"]
    stt, voices = default_selection(
        settings_for(root, local_stt_model="/somewhere/else", local_tts_voices="en-IN=mine")
    )
    assert stt == [] and voices == []  # custom models are the operator's to provide


def test_the_selection_by_name(root):
    assert [s.key for s in resolve_stt(["small", "large-v3-turbo", "small", "none"])] == ["small", "large-v3-turbo"]
    assert resolve_stt(["none"]) == [] and resolve_stt([""]) == []
    with pytest.raises(ModelFetchError, match="unknown speech-to-text model 'tiny'"):
        resolve_stt(["tiny"])
    assert [v.key for v in resolve_voices(["en", "hi-IN"])] == ["en_US-ljspeech-medium", "hi_IN-priyamvada-medium"]
    assert len(resolve_voices(["all"])) == 3 and resolve_voices(["none"]) == []
    assert [v.key for v in resolve_voices(["kn_IN-syspin_male-medium", "kn"])] == ["kn_IN-syspin_male-medium"]
    with pytest.raises(ModelFetchError, match="unknown voice 'fr'"):
        resolve_voices(["fr"])


# --------------------------------------------------------------------------------------------------- status
def test_status_reports_not_installed_incomplete_installed_and_corrupt(root, monkeypatch):
    spec = spec_for(key="small")
    monkeypatch.setattr(lm, "STT_MODELS", {"small": spec})
    settings = settings_for(root)
    by_name = lambda statuses: {s.name: s for s in statuses}  # noqa: E731
    status = by_name(model_status(settings))["small"]
    assert (status.installed, status.verified, status.selected) == (
        False,
        None,
        True,
    ) and "models fetch" in status.detail
    folder = spec_dir(root, spec)
    folder.mkdir(parents=True)
    (folder / "config.json").write_bytes(CONTENT["config.json"])
    status = by_name(model_status(settings))["small"]
    assert status.installed is False and "model.bin is missing" in status.detail
    (folder / "model.bin").write_bytes(CONTENT["model.bin"])
    status = by_name(model_status(settings))["small"]
    assert (status.installed, status.verified) == (True, None) and "not checked" in status.detail
    status = by_name(model_status(settings, verify=True))["small"]
    assert (status.installed, status.verified, status.detail) == (True, True, "installed, SHA-256 verified")
    (folder / "model.bin").write_bytes(b"\x00" * len(CONTENT["model.bin"]))
    status = by_name(model_status(settings, verify=True))["small"]
    assert (status.installed, status.verified) == (True, False) and "CORRUPT" in status.detail


def test_status_lists_the_manifest_voices_with_their_configured_locale_and_note(root):
    statuses = {(s.kind, s.name): s for s in model_status(settings_for(root))}
    assert {k for k in statuses if k[0] == "tts"} == {("tts", key) for key in VOICES}
    hindi = statuses[("tts", "hi_IN-priyamvada-medium")]
    assert (hindi.locale, hindi.selected, hindi.installed, hindi.size_bytes) == (
        "hi-IN",
        True,
        False,
        VOICES["hi_IN-priyamvada-medium"].total_bytes,
    )
    assert "non-commercial" in hindi.note.lower()
    assert statuses[("stt", "large-v3-turbo")].selected is False and statuses[("stt", "small")].selected is True


def test_status_covers_custom_models_and_voices_and_a_mistyped_name(root, tmp_path):
    folder = tmp_path / "my-model"
    folder.mkdir()
    settings = settings_for(
        root, local_stt_model=str(folder), local_tts_voices="en-IN=mine,hi-IN=hi_IN-priyamvada-medium"
    )
    statuses = {(s.kind, s.name): s for s in model_status(settings)}
    custom = statuses[("stt", "my-model")]
    assert custom.installed is False and "config.json, model.bin" in custom.detail
    (folder / "config.json").write_text("{}", encoding="utf-8")
    (folder / "model.bin").write_bytes(b"\x00")
    assert {(s.kind, s.name): s for s in model_status(settings)}[("stt", "my-model")].installed is True
    mine = statuses[("tts", "mine")]
    assert (mine.installed, mine.locale, mine.selected) == (False, "en-IN", True) and "mine.onnx" in mine.detail
    onnx, config = voice_files(root, "mine")
    onnx.parent.mkdir(parents=True)
    onnx.write_bytes(b"x")
    config.write_text("{}", encoding="utf-8")
    assert {(s.kind, s.name): s for s in model_status(settings)}[("tts", "mine")].installed is True
    typo = {(s.kind, s.name): s for s in model_status(settings_for(root, local_stt_model="smal"))}[("stt", "smal")]
    assert typo.installed is False and "must be one of small, large-v3-turbo" in typo.detail
