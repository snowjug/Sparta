"""Local speech-to-text with faster-whisper (MIT): free, offline, on this machine. EXPERIMENTAL, and not a safety guarantee.

* **Utterance based, like the Azure REST adapter.** ``start_stream`` returns a stream that buffers PCM16 until ``flush()``
  (VAD end of utterance), recognises it in a bounded thread pool and emits exactly one ``final`` event, never a partial one,
  and then ends. A UI must not show progressive text for it. Caller audio (8 kHz from a telephone line) is resampled to the
  16 kHz Whisper wants entirely in memory: audio is never written to disk.
* **Models are never downloaded at run time.** They are loaded lazily, once, from ``SPARTA_LOCAL_MODEL_DIR`` with
  ``local_files_only=True`` (``python -m sparta models fetch`` puts them there). A missing model is ``ProviderUnavailable``.
  ONNX Runtime, which the engine's voice-activity filter runs on, ships telemetry that is on by default: it is switched
  off before the engine is imported (``local_models.prepare_engine_environment``), because nothing about a call may leave
  the machine.
* **Language.** A ``locale_hint`` forces that Whisper language (en, hi or kn). Without one, the language is detected among the
  ``candidate_locales`` only (unrestricted detection may pick a related language such as Urdu for Hindi speech). The forced
  language's own ``language_probability`` is always 1.0 and is never used as a confidence.
* **Confidence is a cautious heuristic, not a measurement** (:func:`estimate_confidence`). Sparta treats a confidence below
  0.55 as poor audio and asks the caller to repeat, and a missing one as fine, so this provider always reports one and
  caps it per language and model size: it can only make the assistant more careful, never more trusting.

What it is not: Whisper small is weak for Hindi and unusable for Kannada (see ``locale_support``), 8 kHz telephone audio
holds no information above 4 kHz and its accuracy with any of these models is unmeasured here, and Indian-English accuracy is
unmeasured too.
"""

import asyncio
import io
import logging
import math
import re
import threading
import time
import wave
from collections.abc import AsyncIterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from sparta.config import Settings
from sparta.observability.metrics import PROVIDER_LATENCY_MS, Metrics
from sparta.providers.audio_resample import mix_to_mono_pcm16, pcm16_rms, resample_pcm16
from sparta.providers.base import (
    ProviderMeta,
    ProviderRejected,
    ProviderUnavailable,
    SttStream,
    TranscriptEvent,
    TranscriptResult,
    Usage,
)
from sparta.providers.local_models import (
    INSTALL_HINT,
    SttLocation,
    disable_onnxruntime_telemetry,
    missing_files,
    prepare_engine_environment,
    stt_location,
)

log = logging.getLogger("sparta.local_stt")

PROVIDER = "local-faster-whisper"
STAGE = "stt"
WHISPER_RATE = 16_000
MIN_UTTERANCE_MS = 100
MAX_UTTERANCE_SECONDS = 30  # one Whisper window; the audio pipeline cuts utterances at 20 s
SILENCE_RMS = 10.0  # digital silence; anything noisier is left to the voice-activity filter inside the engine
BEAM_SIZE = 5
# A decoder that loops (Whisper does on noise and on languages it cannot read) runs on to its 448-token limit: measured here,
# 34 to 53 seconds of the only worker for a 4-second Kannada utterance. The limit scales with the audio instead: speech needs
# up to about 25 tokens per second (Indic scripts take several tokens per word), so 30 per second plus a margin never
# truncates real speech and ends a loop early. It is per 30-second window, so it is capped well below Whisper's own limit.
MAX_NEW_TOKENS_BASE = 32
MAX_NEW_TOKENS_PER_SECOND = 30
MAX_NEW_TOKENS_CAP = 400
COMPRESSION_LIMIT = 2.4  # Whisper's own "this is a repetition loop" threshold
NO_SPEECH_LIMIT = 0.6  # Whisper's own "this is not speech" threshold
SUSPECT_CEILING = 0.30  # a segment that trips either indicator is reported as poor audio

# Whisper language code -> the locale reported when the caller did not name a regional variant.
SUPPORTED_LANGUAGES: Mapping[str, str] = MappingProxyType({"en": "en-IN", "hi": "hi-IN", "kn": "kn-IN"})

Tier = Literal["small", "medium", "large"]
Support = Literal["supported", "experimental", "unsupported"]

# Model name -> size tier. A name that is not listed is treated as "small", the most cautious tier. A model directory is
# looked up by its folder name (a leading "faster-whisper-" is ignored).
_MODEL_TIERS: Mapping[str, Tier] = MappingProxyType(
    {
        "tiny": "small",
        "tiny.en": "small",
        "base": "small",
        "base.en": "small",
        "small": "small",
        "small.en": "small",
        "medium": "medium",
        "medium.en": "medium",
        "large": "large",
        "large-v1": "large",
        "large-v2": "large",
        "large-v3": "large",
        "large-v3-turbo": "large",
        "turbo": "large",
    }
)

# Ceiling on the reported confidence, by language and model tier (the table behind :func:`estimate_confidence`).
#   en  0.95 - English is Whisper's strongest language, but the heuristic below is not a probability of being right.
#   hi  0.80 - OpenAI's published FLEURS word error rate for Hindi: small 38%, medium 27%, large-v2 22%.
#   kn  0.50 for small and medium, 0.70 for large - the same table for Kannada: small 100%, medium 78%, large-v2 37%.
#       0.50 is below Sparta's 0.55 poor-audio threshold, so Kannada from a model that cannot read it is always treated as
#       poor audio. Medium is held with small because 78% is no better in practice. large-v3-turbo's Kannada error rate is
#       UNVERIFIED and it is treated as large.
CONFIDENCE_CEILING: Mapping[str, Mapping[Tier, float]] = MappingProxyType(
    {
        "en": MappingProxyType({"small": 0.95, "medium": 0.95, "large": 0.95}),
        "hi": MappingProxyType({"small": 0.80, "medium": 0.80, "large": 0.80}),
        "kn": MappingProxyType({"small": 0.50, "medium": 0.50, "large": 0.70}),
    }
)

_LOCALE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}")
_AUTO_LOCALES = frozenset({"", "auto", "und"})
_WAV_MIMES = frozenset({"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"})


# ----------------------------------------------------------------------------------------------- model and locale
def _bare(model: str) -> str:
    return Path(model).name.removeprefix("faster-whisper-") if model else model


def english_only(model: str) -> bool:
    """English-only checkpoints (``*.en``, distil-whisper) cannot recognise Hindi or Kannada."""
    name = _bare(model)
    return name.endswith(".en") or name.startswith("distil-")


def model_tier(model: str) -> Tier:
    return _MODEL_TIERS.get(_bare(model), "small")


def language_of(locale: str) -> str:
    return locale.split("-", maxsplit=1)[0].strip().lower()


def canonical_locale(locale: str) -> str:
    """``hi-in`` -> ``hi-IN``: language lower case, two-letter regions upper case, four-letter scripts title case."""
    head, *rest = locale.strip().split("-")
    return "-".join([head.lower(), *(p.upper() if len(p) == 2 else p.title() if len(p) == 4 else p for p in rest)])


def locale_support(locale: str, model: str = "small") -> Support:
    """How well ``model`` handles ``locale``, for the documentation and ``sparta doctor``.

    English is supported (accent accuracy is unmeasured). Hindi is only ever experimental. Kannada is experimental with a
    large model and unsupported with a smaller one, whatever the confidence heuristic says.
    """
    language = language_of(locale)
    if language not in SUPPORTED_LANGUAGES or (english_only(model) and language != "en"):
        return "unsupported"
    if language == "en":
        return "supported"
    if language == "hi":
        return "experimental"
    return "experimental" if model_tier(model) == "large" else "unsupported"


def confidence_ceiling(locale: str, model: str) -> float:
    row = CONFIDENCE_CEILING.get(language_of(locale))
    return row[model_tier(model)] if row is not None else min(min(r.values()) for r in CONFIDENCE_CEILING.values())


def estimate_confidence(mean_logprob: float | None, *, locale: str, model: str, suspect: bool = False) -> float:
    """An UNCALIBRATED confidence in [0, 1] for one recognition. Treat it as a caution signal, not a probability.

    ``exp(token-weighted mean avg_logprob)`` (what Whisper itself reports, as a probability per token) clipped to [0, 1],
    then capped by :data:`CONFIDENCE_CEILING` for the language and model, and by ``SUSPECT_CEILING`` when Whisper's own
    failure indicators fired (a repetition loop, or a segment it considers not to be speech): such output is often
    *confident* nonsense. Taking the minimum means the heuristic can lower what Sparta trusts, never raise it. A missing or
    non-finite score is 0.0.
    """
    if mean_logprob is None or not math.isfinite(mean_logprob):
        return 0.0
    value = min(max(math.exp(mean_logprob), 0.0), 1.0)
    if suspect:
        value = min(value, SUSPECT_CEILING)
    return min(value, confidence_ceiling(locale, model))


def max_new_tokens(seconds: float) -> int:
    """The most tokens the decoder may produce for ``seconds`` of audio: see ``MAX_NEW_TOKENS_PER_SECOND``."""
    return min(MAX_NEW_TOKENS_CAP, MAX_NEW_TOKENS_BASE + int(MAX_NEW_TOKENS_PER_SECOND * max(seconds, 0.0)))


@dataclass(frozen=True)
class LanguagePlan:
    forced: str | None  # Whisper language code to force (the hint, or the only candidate)
    candidates: tuple[str, ...]  # codes to choose from when nothing is forced
    locales: Mapping[str, str]  # code -> the locale to report for it


def _valid(raw: str) -> str | None:
    value = raw.strip()
    if value.lower() in _AUTO_LOCALES:
        return None
    if not _LOCALE.fullmatch(value):
        raise ProviderRejected(PROVIDER, STAGE, "invalid locale")
    return canonical_locale(value)


def plan_languages(candidate_locales: Sequence[str], locale_hint: str | None, model: str) -> LanguagePlan:
    """Which Whisper language to force or choose among. Raises ``ProviderRejected`` for what cannot be recognised."""
    allowed = {"en": SUPPORTED_LANGUAGES["en"]} if english_only(model) else dict(SUPPORTED_LANGUAGES)
    hint = _valid(locale_hint or "")
    if hint is not None:
        language = language_of(hint)
        if language not in allowed:
            raise ProviderRejected(PROVIDER, STAGE, f"local recognition with '{_bare(model)}' cannot recognise {hint}")
        return LanguagePlan(forced=language, candidates=(language,), locales={language: hint})
    locales: dict[str, str] = {}
    listed = False
    for raw in candidate_locales:
        locale = _valid(raw)
        if locale is None:
            continue
        listed = True
        language = language_of(locale)
        if language in allowed:
            locales.setdefault(language, locale)
    if listed and not locales:
        raise ProviderRejected(
            PROVIDER,
            STAGE,
            f"none of the candidate languages can be recognised by local '{_bare(model)}' ({', '.join(allowed)})",
        )
    if not locales:
        locales = dict(allowed)
    codes = tuple(locales)
    return LanguagePlan(forced=codes[0] if len(codes) == 1 else None, candidates=codes, locales=locales)


def pick_language(all_language_probs: Sequence[tuple[str, float]], candidates: Sequence[str]) -> tuple[str, float]:
    """The most probable of ``candidates`` and its probability renormalised among them (ties go to the earlier candidate)."""
    probs = {code: max(float(p), 0.0) for code, p in all_language_probs if code in candidates}
    total = sum(probs.values())
    if total <= 0.0:
        return candidates[0], 0.0
    best = max(candidates, key=lambda code: probs.get(code, 0.0))
    return best, probs.get(best, 0.0) / total


# ----------------------------------------------------------------------------------------------------- engine
@dataclass(frozen=True)
class Recognition:
    text: str
    language: str | None  # Whisper code the text was recognised in
    mean_logprob: float | None  # token-weighted mean of the segments' avg_logprob
    suspect: bool = False  # a segment tripped one of Whisper's own failure indicators


class SpeechEngine(Protocol):
    """What the provider needs from a recogniser: the faster-whisper engine below, or a fake in tests."""

    def unavailable(self) -> str | None:
        """Why recognition cannot work right now (a missing model), or ``None``. Cheap: no model is loaded."""
        ...

    def load(self) -> None: ...

    def warm(self) -> None: ...

    def recognise(self, pcm16_16k: bytes, forced: str | None, candidates: Sequence[str]) -> Recognition: ...

    def close(self) -> None: ...


class FasterWhisperEngine:
    """Runs a faster-whisper ``WhisperModel`` loaded from local files. Methods are blocking: call them from a worker thread."""

    def __init__(self, settings: Settings, location: SttLocation) -> None:
        self._settings = settings
        self._location = location
        self._model: Any = None
        self._lock = threading.Lock()

    def unavailable(self) -> str | None:
        name, path = self._location.name, self._location.path
        if not self._location.known:
            return f"unknown model '{name[:60]}': SPARTA_LOCAL_STT_MODEL is a name from `python -m sparta models list` or a directory"
        if self._location.spec is not None:
            return (
                f"model '{name}' is not installed: {INSTALL_HINT}" if missing_files(self._location.spec, path) else None
            )
        needed = ("config.json", "model.bin")
        return (
            None
            if all((path / f).is_file() for f in needed)
            else f"model directory '{path.name}' lacks config.json or model.bin"
        )

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is None:
                self._model = self._load()

    def _load(self) -> Any:
        problem = self.unavailable()
        if problem is not None:
            raise ProviderUnavailable(PROVIDER, STAGE, problem)
        prepare_engine_environment()  # offline, and no telemetry: before the engine's libraries are imported
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ProviderUnavailable(
                PROVIDER, STAGE, "the faster-whisper package is not installed: pip install 'sparta-api[local-speech]'"
            ) from None
        disable_onnxruntime_telemetry()
        settings = self._settings
        started = time.perf_counter()
        try:
            model = WhisperModel(
                str(self._location.path),
                device=settings.local_stt_device,
                compute_type=settings.local_stt_compute_type,
                cpu_threads=settings.local_stt_cpu_threads,
                num_workers=settings.local_max_concurrent_inference,
                local_files_only=True,
            )
        except Exception as exc:
            # a bad model or compute type surfaces as ValueError, RuntimeError or OSError: all mean "cannot be loaded"
            log.error("local speech model could not be loaded", extra={"model": self._location.name}, exc_info=True)
            raise ProviderUnavailable(
                PROVIDER, STAGE, f"model '{self._location.name}' could not be loaded ({type(exc).__name__})"
            ) from None
        log.info(
            "local speech model loaded",
            extra={"model": self._location.name, "seconds": round(time.perf_counter() - started, 2)},
        )
        return model

    def warm(self) -> None:
        """One tiny recognition with and without the voice-activity filter, so the first caller pays for neither."""
        import numpy as np

        self.load()
        noise = (np.random.default_rng(0).standard_normal(WHISPER_RATE) * 0.01).astype(np.float32)
        for vad in (False, True):
            segments, _ = self._model.transcribe(
                noise, language="en", beam_size=1, vad_filter=vad, without_timestamps=True, max_new_tokens=4
            )
            for _segment in segments:
                pass

    def recognise(self, pcm16_16k: bytes, forced: str | None, candidates: Sequence[str]) -> Recognition:
        import numpy as np

        self.load()
        audio = np.frombuffer(pcm16_16k[: len(pcm16_16k) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        language = forced
        if language is None:
            _, _, all_probs = self._model.detect_language(audio)
            language, _ = pick_language(all_probs, candidates)
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=BEAM_SIZE,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
            max_new_tokens=max_new_tokens(len(audio) / WHISPER_RATE),
        )
        parts: list[str] = []
        weighted = 0.0
        tokens = 0
        suspect = False
        for segment in segments:  # inference happens while the generator is consumed
            text = segment.text.strip()
            if not text:
                continue
            parts.append(text)
            weight = max(len(segment.tokens or ()), 1)
            weighted += float(segment.avg_logprob) * weight
            tokens += weight
            suspect = (
                suspect or segment.compression_ratio > COMPRESSION_LIMIT or segment.no_speech_prob > NO_SPEECH_LIMIT
            )
        return Recognition(
            text=" ".join(parts),
            language=language,
            mean_logprob=weighted / tokens if tokens else None,
            suspect=suspect,
        )

    def close(self) -> None:
        self._model = None


# --------------------------------------------------------------------------------------------------- provider
@dataclass(frozen=True)
class _Outcome:
    text: str
    locale: str | None
    confidence: float


_SILENT = _Outcome("", None, 0.0)


def _version() -> str | None:
    try:
        return metadata.version("faster-whisper")
    except metadata.PackageNotFoundError:
        return None


class _LocalSttStream:
    """One utterance: buffers audio, answers on ``flush()`` with a single ``final`` event, then ends."""

    def __init__(self, stt: "LocalSpeechToText", *, plan: LanguagePlan, sample_rate: int) -> None:
        self._stt = stt
        self._plan = plan
        self._rate = sample_rate
        self._max_bytes = sample_rate * 2 * MAX_UTTERANCE_SECONDS
        self._pcm = bytearray()
        self._events: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._stopped = False
        self._flushed = False

    async def push_audio(self, chunk: bytes) -> None:
        if self._stopped or self._flushed or not chunk:
            return
        if len(self._pcm) + len(chunk) > self._max_bytes:
            self._pcm.clear()
            raise ProviderRejected(PROVIDER, STAGE, "utterance exceeds the maximum buffered audio; flush sooner")
        self._pcm += chunk

    async def flush(self) -> None:
        if self._stopped or self._flushed:
            return
        self._flushed = True
        pcm = bytes(self._pcm[: len(self._pcm) // 2 * 2])
        self._pcm = bytearray()
        duration_ms = len(pcm) * 1000 // (self._rate * 2)
        try:
            outcome = (
                _SILENT if duration_ms < MIN_UTTERANCE_MS else await self._stt.recognise(pcm, self._rate, self._plan)
            )
            if not self._stopped:
                self._events.put_nowait(
                    TranscriptEvent(
                        kind="final",
                        text=outcome.text,
                        language=outcome.locale,
                        confidence=outcome.confidence,
                        offset_ms=0,
                        duration_ms=duration_ms,
                    )
                )
        finally:
            self._events.put_nowait(None)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                self._events.put_nowait(None)  # later iterators must terminate too
                return
            yield event

    async def stop_stream(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._pcm = bytearray()
        self._events.put_nowait(None)


class LocalSpeechToText:
    consumes_audio = True  # it reads the samples, unlike the simulator

    def __init__(
        self, settings: Settings, *, metrics: Metrics | None = None, engine: SpeechEngine | None = None
    ) -> None:
        self._location = stt_location(settings)
        self.model_name = self._location.name
        self.meta = ProviderMeta(provider=PROVIDER, simulated=False, model=self.model_name, version=_version())
        self._metrics = metrics
        self._max_audio_bytes = settings.max_audio_bytes
        self._max_audio_seconds = settings.max_audio_seconds
        self._engine: SpeechEngine = engine or FasterWhisperEngine(settings, self._location)
        self._executor = ThreadPoolExecutor(
            max_workers=settings.local_max_concurrent_inference, thread_name_prefix="sparta-stt"
        )
        self._closed = False
        if (problem := self._engine.unavailable()) is not None:
            log.warning("local speech recognition is not ready: %s", problem)

    def locale_support(self, locale: str) -> Support:
        """How well the configured model handles ``locale`` (see :func:`locale_support`)."""
        return locale_support(locale, self.model_name)

    def ready(self) -> str | None:
        """``None`` when a recognition can start, else why not (the model is missing)."""
        return self._engine.unavailable()

    async def warmup(self) -> float:
        """Load the model and run one tiny recognition; returns the seconds it took. Call it at startup."""
        started = time.perf_counter()
        await self._in_pool(self._warm_sync)
        return time.perf_counter() - started

    def _warm_sync(self) -> None:
        self._engine.load()
        self._engine.warm()

    async def aclose(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._engine.close()

    async def _in_pool(self, fn: Any, *args: Any) -> Any:
        try:
            return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)
        except RuntimeError:
            if self._closed:
                raise ProviderUnavailable(PROVIDER, STAGE, "the recogniser is closed") from None
            raise

    async def start_stream(
        self, *, candidate_locales: Sequence[str], locale_hint: str | None, trace_id: str, sample_rate: int = 16000
    ) -> SttStream:
        if self._closed:
            raise ProviderUnavailable(PROVIDER, STAGE, "the recogniser is closed")
        if not 8000 <= sample_rate <= 48000:
            raise ProviderRejected(PROVIDER, STAGE, "unsupported sample rate")
        plan = plan_languages(candidate_locales, locale_hint, self.model_name)
        if (problem := self._engine.unavailable()) is not None:
            raise ProviderUnavailable(PROVIDER, STAGE, problem)
        return _LocalSttStream(self, plan=plan, sample_rate=sample_rate)

    async def recognise(self, pcm: bytes, sample_rate: int, plan: LanguagePlan) -> _Outcome:
        """Recognise one utterance of PCM16 mono in the bounded worker pool."""
        outcome: _Outcome = await self._in_pool(self._recognise_sync, pcm, sample_rate, plan)
        return outcome

    def _recognise_sync(self, pcm: bytes, sample_rate: int, plan: LanguagePlan) -> _Outcome:
        audio = pcm if sample_rate == WHISPER_RATE else resample_pcm16(pcm, sample_rate, WHISPER_RATE)
        if pcm16_rms(audio) < SILENCE_RMS:
            return _SILENT
        started = time.perf_counter()
        found = self._engine.recognise(audio, plan.forced, plan.candidates)
        if self._metrics is not None:
            self._metrics.observe(
                PROVIDER_LATENCY_MS, (time.perf_counter() - started) * 1000.0, provider=PROVIDER, stage="stt_inference"
            )
        text = found.text.strip()
        if not text:
            return _SILENT
        code = found.language or plan.candidates[0]
        locale = plan.locales.get(code) or SUPPORTED_LANGUAGES.get(code) or code
        confidence = estimate_confidence(
            found.mean_logprob, locale=locale, model=self.model_name, suspect=found.suspect
        )
        return _Outcome(text, locale, confidence)

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        candidate_locales: Sequence[str],
        locale_hint: str | None,
        trace_id: str,
        transcript_hint: str | None = None,
    ) -> TranscriptResult:
        """One-shot recognition of an uploaded clip (16-bit PCM WAV, or ``audio/L16``). ``transcript_hint`` is ignored:
        a real recogniser never echoes caller-supplied text."""
        pcm, rate = self._decode_upload(audio, content_type)
        plan = plan_languages(candidate_locales, locale_hint, self.model_name)
        if (problem := self._engine.unavailable()) is not None:
            raise ProviderUnavailable(PROVIDER, STAGE, problem)
        seconds = len(pcm) / (rate * 2)
        outcome = _SILENT if seconds * 1000 < MIN_UTTERANCE_MS else await self.recognise(pcm, rate, plan)
        segments = (
            [
                TranscriptEvent(
                    kind="final",
                    text=outcome.text,
                    language=outcome.locale,
                    confidence=outcome.confidence,
                    duration_ms=int(seconds * 1000),
                )
            ]
            if outcome.text
            else []
        )
        return TranscriptResult(
            text=outcome.text,
            language=outcome.locale,
            confidence=outcome.confidence,
            segments=segments,
            audio_seconds=seconds,
            usage=Usage(audio_seconds=seconds, requests=1),
            simulated=False,
        )

    def _decode_upload(self, audio: bytes, content_type: str) -> tuple[bytes, int]:
        """PCM16 mono and its sample rate from an uploaded clip, in memory. Raises ``ProviderRejected`` for anything else."""
        mime, *params = (part.strip() for part in content_type.split(";"))
        mime = mime.lower()
        if not audio:
            raise ProviderRejected(PROVIDER, STAGE, "empty audio")
        if len(audio) > self._max_audio_bytes:
            raise ProviderRejected(PROVIDER, STAGE, "audio is too large")
        if mime in _WAV_MIMES:
            pcm, rate = _decode_wav(audio)
        elif mime == "audio/l16":
            pcm, rate = _decode_l16(audio, params)
        else:
            raise ProviderRejected(
                PROVIDER, STAGE, "unsupported audio content type: local recognition reads 16-bit PCM WAV and audio/L16"
            )
        if len(pcm) / (rate * 2) > self._max_audio_seconds:
            raise ProviderRejected(PROVIDER, STAGE, "audio is too long")
        return pcm, rate


def _checked_rate(rate: int) -> int:
    if not 8000 <= rate <= 48000:
        raise ProviderRejected(PROVIDER, STAGE, "unsupported sample rate")
    return rate


def _decode_wav(audio: bytes) -> tuple[bytes, int]:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            if width != 2 or not 1 <= channels <= 8:
                raise ProviderRejected(PROVIDER, STAGE, "unsupported WAV format: use 16-bit PCM")
            _checked_rate(rate)
            raw = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError):
        raise ProviderRejected(PROVIDER, STAGE, "the WAV file could not be read: use 16-bit PCM") from None
    return mix_to_mono_pcm16(raw, channels), rate


def _decode_l16(audio: bytes, params: Sequence[str]) -> tuple[bytes, int]:
    """``audio/L16`` is big-endian (RFC 3551) and needs ``rate=``; ``channels`` may only be 1."""
    values = dict(p.lower().split("=", 1) for p in params if "=" in p)
    try:
        rate = _checked_rate(int(values["rate"]))
        channels = int(values.get("channels", "1"))
    except (KeyError, ValueError):
        raise ProviderRejected(PROVIDER, STAGE, "audio/L16 needs a numeric rate parameter") from None
    if channels != 1:
        raise ProviderRejected(PROVIDER, STAGE, "audio/L16 must be mono")
    usable = audio[: len(audio) // 2 * 2]
    swapped = bytearray(usable)
    swapped[0::2], swapped[1::2] = usable[1::2], usable[0::2]  # big-endian on the wire, little-endian inside Sparta
    return bytes(swapped), rate


__all__ = [
    "CONFIDENCE_CEILING",
    "FasterWhisperEngine",
    "LanguagePlan",
    "LocalSpeechToText",
    "Recognition",
    "SpeechEngine",
    "canonical_locale",
    "confidence_ceiling",
    "english_only",
    "estimate_confidence",
    "locale_support",
    "max_new_tokens",
    "model_tier",
    "pick_language",
    "plan_languages",
]
