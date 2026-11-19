"""Manifest, download and verification of the local speech models (faster-whisper and Piper voices).

Nothing else in Sparta ever downloads a model: the speech providers only read what ``python -m sparta models fetch`` put in
``SPARTA_LOCAL_MODEL_DIR``. Everything the manifest names is pinned twice, so a mirror, a moved branch or a swapped file
cannot change what runs:

* the Hugging Face repository **commit** (a 40-character revision, never a branch name), and
* the **SHA-256** and size of every file (computed from the pinned commit; the large LFS files were also checked against the
  digest Hugging Face publishes, and the small ones against their git blob ids).

Downloads use HTTPS only, from Hugging Face hosts only (``huggingface.co``, ``cdn-lfs*.huggingface.co`` and ``*.hf.co``, which is
where its large files are served from), follow a few redirects within those hosts, write to ``<name>.part`` and move the file
into place only after the size and SHA-256 match (a mismatch deletes it). No credential is sent and no URL (signed download
links carry tokens) is ever printed. Nothing that is downloaded is executed or unpacked: model files are read as data.

Directory layout under the model directory::

    stt/<model>/                 faster-whisper (CTranslate2) files: config.json, model.bin, tokenizer.json, vocabulary.*
    tts/<voice>/<voice>.onnx     Piper voice and its <voice>.onnx.json configuration

Licences differ per entry and are shown by ``models list`` and ``models fetch``: the Hindi and Kannada voices are **not**
unrestricted (see their caveats) and the Piper engine itself is GPL-3.0-or-later.
"""

import contextlib
import hashlib
import logging
import os
import re
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from urllib.parse import quote, urljoin, urlsplit

import httpx

from sparta.config import Settings

log = logging.getLogger("sparta.local_models")

HUB = "https://huggingface.co"
USER_AGENT = "sparta-models/1"
MAX_REDIRECTS = 5
MAX_FILE_BYTES = 2 * 1024**3  # no manifest file may be larger, whatever a typo in an entry says
DISK_MARGIN_BYTES = 128 * 1024**2
BLOCK_BYTES = 1024 * 1024
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
VOICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class ModelFetchError(Exception):
    """A download or verification failure. The message is safe to print (no URL, no secret)."""


@dataclass(frozen=True)
class ModelFile:
    name: str  # file name inside the model's directory
    sha256: str
    size: int
    remote: str | None = None  # path inside the repository when it differs from ``name``

    def __post_init__(self) -> None:
        if Path(self.name).name != self.name or self.name in {"", ".", ".."} or not _SHA256.fullmatch(self.sha256):
            raise ValueError(f"invalid manifest file entry {self.name!r}")
        if not 0 < self.size <= MAX_FILE_BYTES:
            raise ValueError(f"invalid size for {self.name!r}")

    @property
    def remote_path(self) -> str:
        return self.remote or self.name


@dataclass(frozen=True)
class ModelSpec:
    key: str
    kind: Literal["stt", "tts"]
    repo: str  # Hugging Face repository
    revision: str  # its commit
    files: tuple[ModelFile, ...]
    summary: str
    licence: str
    caveat: str
    language: str | None = None  # voices: the language it speaks (en, hi, kn)
    gender: Literal["female", "male", "neutral"] | None = None

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.revision) or not VOICE_ID.fullmatch(self.key) or not self.files:
            raise ValueError(f"invalid manifest entry {self.key!r}")

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def url(self, file: ModelFile) -> str:
        return f"{HUB}/{self.repo}/resolve/{self.revision}/{quote(file.remote_path)}"


def _voice(
    key: str,
    repo: str,
    revision: str,
    folder: str,
    onnx: tuple[str, int],
    config: tuple[str, int],
    *,
    summary: str,
    licence: str,
    caveat: str,
    language: str,
    gender: Literal["female", "male", "neutral"],
) -> ModelSpec:
    prefix = f"{folder}/" if folder else ""
    return ModelSpec(
        key=key,
        kind="tts",
        repo=repo,
        revision=revision,
        files=(
            ModelFile(f"{key}.onnx", onnx[0], onnx[1], f"{prefix}{key}.onnx"),
            ModelFile(f"{key}.onnx.json", config[0], config[1], f"{prefix}{key}.onnx.json"),
        ),
        summary=summary,
        licence=licence,
        caveat=caveat,
        language=language,
        gender=gender,
    )


_PIPER_VOICES_REVISION = "04ca88f5685ca5253c701af3687e155b113bd512"

_STT = (
    ModelSpec(
        key="small",
        kind="stt",
        repo="Systran/faster-whisper-small",
        revision="536b0662742c02347bc0e980a01041f333bce120",
        files=(
            ModelFile("config.json", "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828", 2370),
            ModelFile("model.bin", "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671", 483_546_902),
            ModelFile("tokenizer.json", "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab", 2_203_239),
            ModelFile("vocabulary.txt", "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913", 459_861),
        ),
        summary="Whisper small, CTranslate2 conversion (about 0.5 GB on disk)",
        licence="MIT (OpenAI Whisper weights; CTranslate2 conversion by Systran)",
        caveat=(
            "Fine for English; weak for Hindi and unusable for Kannada (OpenAI's published FLEURS word error rates for "
            "Whisper small: Hindi 38%, Kannada 100%). Sparta treats Kannada recognised by this size as poor audio."
        ),
    ),
    ModelSpec(
        key="large-v3-turbo",
        kind="stt",
        repo="dropbox-dash/faster-whisper-large-v3-turbo",
        revision="0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        files=(
            ModelFile("config.json", "b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e", 2263),
            ModelFile("model.bin", "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da", 1_617_884_929),
            ModelFile(
                "preprocessor_config.json", "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711", 340
            ),
            ModelFile("tokenizer.json", "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd", 2_710_337),
            ModelFile("vocabulary.json", "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1", 1_068_114),
        ),
        summary="Whisper large-v3-turbo, CTranslate2 FP16 conversion (about 1.6 GB on disk)",
        licence="MIT (OpenAI Whisper weights; CTranslate2 conversion by dropbox-dash, a third party)",
        caveat=(
            "Better Hindi and Kannada than small, but its Kannada word error rate is unpublished and was not measured "
            "here, and the conversion comes from a third-party repository (pinned by commit and SHA-256)."
        ),
    ),
)

_TTS = (
    _voice(
        "en_US-ljspeech-medium",
        "rhasspy/piper-voices",
        _PIPER_VOICES_REVISION,
        "en/en_US/ljspeech/medium",
        ("6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22", 63_531_379),
        ("141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860", 4972),
        summary="English, single female voice (22,050 Hz, about 64 MB)",
        licence="LJ Speech dataset (public domain); published in rhasspy/piper-voices",
        caveat="US English accent: there is no Indian-English Piper voice in the official catalogue.",
        language="en",
        gender="female",
    ),
    _voice(
        "hi_IN-priyamvada-medium",
        "rhasspy/piper-voices",
        _PIPER_VOICES_REVISION,
        "hi/hi_IN/priyamvada/medium",
        ("aa63bcf2cd493b55a450f280e23cf77f03afc9af7015e6e5acd43b652f166c88", 63_516_050),
        ("5efc0ccf7529f3528996d46e0fac1f969f681d44a8e55bfa6236ff8841b5d52d", 4973),
        summary="Hindi, single female voice (22,050 Hz, about 64 MB)",
        licence="Dataset licence CC-BY-NC-SA-4.0 (non-commercial, share-alike); the voice weights' own grant is not established",
        caveat=(
            "Experimental quality. Use it for non-commercial purposes only and get a legal review before any other use. "
            "It speaks Hindi in Devanagari; it is not native-level speech."
        ),
        language="hi",
        gender="female",
    ),
    _voice(
        "kn_IN-syspin_male-medium",
        "micahchoo/piper-kn",
        "c73546cb70012e28f6093a61c71162924398fee1",
        "",
        ("bff423259625c0c1182e5b417f68560b6a55f3c4d27557a6abf2fbe51e7e00ee", 63_516_051),
        ("feaf88702f1f045fdf4bd23606267344afb96141291de8a8118cdef125daf302", 5268),
        summary="Kannada, single male voice (22,050 Hz, about 64 MB), a community model",
        licence=(
            "Community voice, free for non-commercial use only: recordings SYSPIN (IISc) CC BY 4.0, but fine-tuned from "
            "the Lessac voice whose Blizzard 2013 research licence may bind derived weights (its author's reading)"
        ),
        caveat=(
            "Experimental quality (its author reports misplaced pauses and some roughness; there is no official Piper "
            "Kannada voice). Non-commercial use only; get a legal review before any other use."
        ),
        language="kn",
        gender="male",
    ),
)

STT_MODELS: Mapping[str, ModelSpec] = MappingProxyType({spec.key: spec for spec in _STT})
VOICES: Mapping[str, ModelSpec] = MappingProxyType({spec.key: spec for spec in _TTS})
ENGINE_NOTE = "The Piper engine (piper-tts) is GPL-3.0-or-later; faster-whisper is MIT."
INSTALL_HINT = "run `python -m sparta models fetch`"


# ------------------------------------------------------------------------------------------- engine environment
def prepare_engine_environment() -> None:
    """Keep the speech engines offline and silent. Call it before importing one: both settings are read at import time.

    * ``HF_HUB_OFFLINE``: faster-whisper's hub client would download a model it cannot find. Nothing downloads at run time.
    * ``ORT_DISABLE_TELEMETRY``: ONNX Runtime (faster-whisper's voice-activity filter and Piper both run on it) ships
      Microsoft 1DS telemetry that is on by default (version 1.32 logs "telemetry_1ds.cc: Failed to persist telemetry
      device ID" at import). Opting out means no uploader, events or persistent device identifier. This is a call-screening
      product: nothing about a call may leave the machine, so it is off unless an operator sets the variable themselves.
    """
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")


def disable_onnxruntime_telemetry() -> None:
    """The API opt-out as well, once ONNX Runtime is importable (covers builds that only honour the call)."""
    try:
        import onnxruntime

        disable = getattr(onnxruntime, "disable_telemetry_events", None)
        if callable(disable):
            disable()
    except Exception:  # an opt-out must never stop the engine from starting
        log.debug("could not call onnxruntime.disable_telemetry_events", exc_info=True)


# ------------------------------------------------------------------------------------------------ locations
def model_root(settings: Settings, override: str | Path | None = None) -> Path:
    return Path(override or settings.local_model_dir).expanduser()


def spec_dir(root: Path, spec: ModelSpec) -> Path:
    return root / spec.kind / spec.key


def voice_files(root: Path, voice_id: str) -> tuple[Path, Path]:
    """The ``.onnx`` model and its ``.onnx.json`` configuration of a voice. ``voice_id`` must be a plain identifier."""
    if not VOICE_ID.fullmatch(voice_id):
        raise ValueError("invalid voice id")
    folder = root / "tts" / voice_id
    return folder / f"{voice_id}.onnx", folder / f"{voice_id}.onnx.json"


@dataclass(frozen=True)
class SttLocation:
    name: str  # what the provider reports as its model: the manifest name, or the directory's name
    path: Path
    spec: ModelSpec | None  # ``None`` for a directory the operator supplied
    known: bool  # False when the setting is neither a manifest name nor an existing directory


def stt_location(settings: Settings, root: Path | None = None) -> SttLocation:
    """Where the configured faster-whisper model lives: a manifest name under the model directory, or a directory."""
    value = settings.local_stt_model.strip()
    base = root or model_root(settings)
    spec = STT_MODELS.get(value)
    if spec is not None:
        return SttLocation(spec.key, spec_dir(base, spec), spec, True)
    candidate = Path(value).expanduser()
    if value and candidate.is_dir():
        return SttLocation(candidate.name or value, candidate, None, True)
    return SttLocation(value, base / "stt" / "unknown", None, False)


# ------------------------------------------------------------------------------------------------ hashing
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()


def missing_files(spec: ModelSpec, directory: Path) -> list[str]:
    """Files of ``spec`` that are absent or whose size differs from the manifest (a cheap check: nothing is hashed)."""
    problems: list[str] = []
    for file in spec.files:
        path = directory / file.name
        try:
            size = path.stat().st_size if path.is_file() else None
        except OSError:
            size = None
        if size is None:
            problems.append(f"{file.name} is missing")
        elif size != file.size:
            problems.append(f"{file.name} has {size} bytes, expected {file.size}")
    return problems


def verify_spec(spec: ModelSpec, directory: Path) -> list[str]:
    """Hash every file of ``spec``: the problems found (empty when every file matches the pinned SHA-256)."""
    problems = missing_files(spec, directory)
    if problems:
        return problems
    for file in spec.files:
        if sha256_file(directory / file.name) != file.sha256:
            problems.append(f"{file.name} does not match the pinned SHA-256")
    return problems


# ------------------------------------------------------------------------------------------------ status
@dataclass(frozen=True)
class ModelStatus:
    name: str
    kind: Literal["stt", "tts"]
    installed: bool
    verified: bool | None  # True: SHA-256 matches the pinned value. False: it does not. None: not hashed
    path: str
    detail: str
    locale: str | None = None  # voices: the locale they are configured for
    selected: bool = False  # used by the current settings
    size_bytes: int = 0
    note: str = ""


def _spec_status(spec: ModelSpec, root: Path, *, verify: bool, selected: bool, locale: str | None) -> ModelStatus:
    directory = spec_dir(root, spec)
    installed: bool
    verified: bool | None = None
    if not any((directory / f.name).is_file() for f in spec.files):
        installed, detail = False, f"not installed: {INSTALL_HINT}"
    elif problems := missing_files(spec, directory):
        installed, detail = False, f"incomplete ({'; '.join(problems)}): {INSTALL_HINT}"
    elif not verify:
        installed, detail = True, "installed (sizes match; SHA-256 not checked)"
    elif problems := verify_spec(spec, directory):
        installed, verified, detail = True, False, f"CORRUPT ({'; '.join(problems)}): re-run `models fetch`"
    else:
        installed, verified, detail = True, True, "installed, SHA-256 verified"
    return ModelStatus(
        name=spec.key,
        kind=spec.kind,
        installed=installed,
        verified=verified,
        path=str(directory),
        detail=detail,
        locale=locale,
        selected=selected,
        size_bytes=spec.total_bytes,
        note=spec.caveat,
    )


def model_status(settings: Settings, *, verify: bool = False, root: Path | None = None) -> list[ModelStatus]:
    """Every manifest model and voice, plus a custom STT directory or voice that the settings point at.

    ``verify=True`` hashes the installed files (a second or two for ``small``, a few for ``large-v3-turbo``); without it
    ``verified`` is ``None``. ``selected`` marks what the current settings would load.
    """
    base = root or model_root(settings)
    location = stt_location(settings, base)
    voices = settings.local_tts_voice_map
    configured = {voice: locale for locale, voice in voices.items()}
    out = [
        _spec_status(spec, base, verify=verify, selected=location.spec is spec, locale=None)
        for spec in STT_MODELS.values()
    ]
    if location.spec is None:
        if location.known:
            problems = [f for f in ("config.json", "model.bin") if not (location.path / f).is_file()]
            out.append(
                ModelStatus(
                    name=location.name,
                    kind="stt",
                    installed=not problems,
                    verified=None,
                    path=str(location.path),
                    detail="custom directory (not in the manifest, so not hash-checked)"
                    if not problems
                    else f"custom directory is missing {', '.join(problems)}",
                    selected=True,
                )
            )
        else:
            out.append(
                ModelStatus(
                    name=location.name or "(empty)",
                    kind="stt",
                    installed=False,
                    verified=None,
                    path="",
                    detail=f"SPARTA_LOCAL_STT_MODEL must be one of {', '.join(STT_MODELS)} or an existing directory",
                    selected=True,
                )
            )
    for spec in VOICES.values():
        out.append(
            _spec_status(spec, base, verify=verify, selected=spec.key in configured, locale=configured.get(spec.key))
        )
    for locale, voice in voices.items():
        if voice not in VOICES:
            onnx, config = voice_files(base, voice)
            ready = onnx.is_file() and config.is_file()
            out.append(
                ModelStatus(
                    name=voice,
                    kind="tts",
                    installed=ready,
                    verified=None,
                    path=str(onnx.parent),
                    detail="custom voice (not in the manifest, so not hash-checked)"
                    if ready
                    else f"custom voice files are missing: put {onnx.name} and {config.name} in that folder",
                    locale=locale,
                    selected=True,
                )
            )
    return out


# ------------------------------------------------------------------------------------------------ download
Progress = Callable[[str, int, int], None]  # (label, bytes so far, bytes in total)


def host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host in {"huggingface.co", "hf.co"} or host.endswith(".hf.co"):
        return True
    return host.startswith("cdn-lfs") and host.endswith(".huggingface.co")


def _require_allowed(url: str) -> None:
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ModelFetchError("refusing a malformed download address") from None
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        raise ModelFetchError("refusing a download that is not plain https")
    if not host or not host_allowed(host):
        raise ModelFetchError(f"refusing to download from '{host or '?'}': only Hugging Face hosts are allowed")


@contextlib.contextmanager
def _open_checked(client: httpx.Client, url: str) -> Iterator[httpx.Response]:
    """A streaming 200 response, following at most ``MAX_REDIRECTS`` redirects and checking every hop's host."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _require_allowed(current)
        request = client.build_request(
            "GET", current, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        )
        try:
            response = client.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ModelFetchError(f"network error while downloading ({type(exc).__name__})") from None
        if response.status_code in _REDIRECTS:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise ModelFetchError("a redirect carried no destination")
            current = urljoin(current, location)
            continue
        try:
            if response.status_code != 200:
                raise ModelFetchError(f"the server answered HTTP {response.status_code}")
            yield response
        finally:
            response.close()
        return
    raise ModelFetchError("too many redirects")


def _download(
    client: httpx.Client, spec: ModelSpec, file: ModelFile, directory: Path, progress: Progress | None
) -> str:
    final = directory / file.name
    label = f"{spec.key}/{file.name}"
    if final.is_file() and final.stat().st_size == file.size and sha256_file(final) == file.sha256:
        return "present"
    part = directory / f"{file.name}.part"
    digest = hashlib.sha256()
    received = 0
    try:
        with _open_checked(client, spec.url(file)) as response:
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) != file.size:
                raise ModelFetchError(f"{file.name}: the server announced {declared} bytes, expected {file.size}")
            with part.open("wb") as handle:
                try:
                    for block in response.iter_bytes(BLOCK_BYTES):
                        received += len(block)
                        if received > file.size:
                            raise ModelFetchError(
                                f"{file.name}: more data than the {file.size} bytes the manifest pins"
                            )
                        digest.update(block)
                        handle.write(block)
                        if progress is not None:
                            progress(label, received, file.size)
                except httpx.HTTPError as exc:
                    raise ModelFetchError(f"{file.name}: the download was interrupted ({type(exc).__name__})") from None
        if received != file.size:
            raise ModelFetchError(f"{file.name}: received {received} bytes, expected {file.size}")
        if digest.hexdigest() != file.sha256:
            raise ModelFetchError(f"{file.name}: SHA-256 mismatch, the file was discarded")
        os.replace(part, final)
    finally:
        part.unlink(missing_ok=True)
    return "downloaded"


def new_client() -> httpx.Client:
    """The HTTP client for downloads: redirects are followed by hand (every hop is checked), nothing is sent but a user agent."""
    return httpx.Client(
        timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=False, headers={"User-Agent": USER_AGENT}
    )


def install_spec(
    spec: ModelSpec, root: Path, *, client: httpx.Client | None = None, progress: Progress | None = None
) -> list[tuple[str, str]]:
    """Download what ``spec`` is missing into ``root``. Returns ``(file, "present" | "downloaded")`` per file."""
    directory = spec_dir(root, spec)
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.part"):
        stale.unlink(missing_ok=True)
    owned = client is None
    http = client or new_client()
    try:
        return [(file.name, _download(http, spec, file, directory, progress)) for file in spec.files]
    finally:
        if owned:
            http.close()


def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def pending_bytes(spec: ModelSpec, root: Path) -> int:
    """Bytes still to download for ``spec`` (files that are already complete are not counted)."""
    directory = spec_dir(root, spec)
    need = 0
    for file in spec.files:
        path = directory / file.name
        if not (path.is_file() and path.stat().st_size == file.size):
            need += file.size
    return need


# ------------------------------------------------------------------------------------------------ selection
def resolve_stt(names: Sequence[str]) -> list[ModelSpec]:
    out: list[ModelSpec] = []
    for raw in names:
        name = raw.strip()
        if not name or name.lower() == "none":
            continue
        spec = STT_MODELS.get(name)
        if spec is None:
            raise ModelFetchError(f"unknown speech-to-text model '{name}': choose from {', '.join(STT_MODELS)}")
        if spec not in out:
            out.append(spec)
    return out


def resolve_voices(names: Sequence[str]) -> list[ModelSpec]:
    """Voices by language (``en``, ``hi``, ``kn`` or ``hi-IN``), by voice id, or ``all``; ``none`` selects nothing."""
    out: list[ModelSpec] = []
    for raw in names:
        name = raw.strip()
        if not name or name.lower() == "none":
            continue
        chosen: list[ModelSpec]
        if name.lower() == "all":
            chosen = list(VOICES.values())
        elif name in VOICES:
            chosen = [VOICES[name]]
        else:
            language = name.split("-", 1)[0].lower()
            chosen = [spec for spec in VOICES.values() if spec.language == language]
            if not chosen:
                raise ModelFetchError(f"unknown voice '{name}': use en, hi, kn, all, or one of {', '.join(VOICES)}")
        out.extend(spec for spec in chosen if spec not in out)
    return out


def default_selection(settings: Settings) -> tuple[list[ModelSpec], list[ModelSpec]]:
    """What the current settings need that the manifest can supply: the configured STT model and voices."""
    stt = [STT_MODELS[settings.local_stt_model.strip()]] if settings.local_stt_model.strip() in STT_MODELS else []
    voices = [VOICES[v] for v in dict.fromkeys(settings.local_tts_voice_map.values()) if v in VOICES]
    return stt, voices


def fetch_models(
    specs: Sequence[ModelSpec], root: Path, *, client: httpx.Client | None = None, progress: Progress | None = None
) -> dict[str, list[tuple[str, str]]]:
    """Install ``specs`` into ``root`` after checking the free disk space. Raises :class:`ModelFetchError`."""
    need = sum(pending_bytes(spec, root) for spec in specs)
    root.mkdir(parents=True, exist_ok=True)
    if need and free_bytes(root) < need + DISK_MARGIN_BYTES:
        raise ModelFetchError(
            f"not enough free disk space in {root}: {need / 1024**2:.0f} MB to download, "
            f"{free_bytes(root) / 1024**2:.0f} MB free"
        )
    return {spec.key: install_spec(spec, root, client=client, progress=progress) for spec in specs}


__all__ = [
    "ENGINE_NOTE",
    "INSTALL_HINT",
    "STT_MODELS",
    "VOICES",
    "ModelFetchError",
    "ModelFile",
    "ModelSpec",
    "ModelStatus",
    "SttLocation",
    "default_selection",
    "disable_onnxruntime_telemetry",
    "fetch_models",
    "host_allowed",
    "install_spec",
    "model_root",
    "model_status",
    "prepare_engine_environment",
    "resolve_stt",
    "resolve_voices",
    "sha256_file",
    "spec_dir",
    "stt_location",
    "verify_spec",
    "voice_files",
]
