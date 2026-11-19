"""Local text-to-speech with Piper: free, offline, on this machine's CPU. EXPERIMENTAL.

* **Piper's engine (``piper-tts``) is GPL-3.0-or-later** and an optional extra (``pip install 'sparta-api[local-speech]'``); it
  is imported lazily and never part of the default install or image. The voices have their own terms, shown by
  ``python -m sparta models list``: the Hindi voice's dataset is CC-BY-NC-SA-4.0 and the Kannada voice is a community model
  that is free for non-commercial use only. The English voice has a US accent.
* **Models are never downloaded at run time** (``python -m sparta models fetch`` puts them in ``SPARTA_LOCAL_MODEL_DIR``).
  A voice is loaded lazily, once; ``warmup()`` loads every configured voice that is installed so no caller pays for it.
  ONNX Runtime, which Piper runs on, ships telemetry that is on by default: it is switched off before Piper is imported
  (``local_models.prepare_engine_environment``), because nothing about a call may leave the machine.
* **No silent language switching.** The voice comes from the request's locale (``SPARTA_LOCAL_TTS_VOICES``); a ``voice_id``
  is honoured only when it is a known local voice for that language (the planner sends Azure voice names, which are not).
  A locale with no installed voice is ``ProviderRejected``: it is never spoken in another language. A request carries
  no English rendering today (``SynthesisRequest`` has ``text`` in the locale's script only), so there is nothing honest to
  fall back to; ``SPARTA_LOCAL_TTS_FALLBACK_LOCALE`` is reserved for that.
* **Streaming.** Piper makes one sentence at a time at the voice's native 22,050 Hz. A producer synthesises the sentence after
  the one being played (and resamples it, see ``audio_resample``) in a worker thread, so the event loop that paces 20 ms
  frames is never blocked and there is no gap between sentences. Audio is handed out in 40 ms chunks (whole 20 ms frames).
  Each sentence is resampled on its own: a few samples of filter ringing at sentence joins are inaudible, as sentences
  start and end in near silence.
* **Stopping.** ``stop_playback(id)`` (the request's ``trace_id``) stops handing out audio at once. A sentence already
  being synthesised cannot be interrupted: its worker finishes it (a fraction of a second) and the result is dropped.
  The speaking style is ignored: Piper voices have none.
"""

import asyncio
import logging
import math
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

from sparta.config import Settings
from sparta.domain.models import VoiceOption
from sparta.observability.metrics import AUDIO_SECONDS, PROVIDER_LATENCY_MS, Metrics
from sparta.providers.audio_resample import resample_pcm16
from sparta.providers.base import (
    AudioChunk,
    ProviderError,
    ProviderMeta,
    ProviderRejected,
    ProviderUnavailable,
    SynthesisRequest,
)
from sparta.providers.local_models import (
    VOICES,
    disable_onnxruntime_telemetry,
    missing_files,
    model_root,
    prepare_engine_environment,
    spec_dir,
    voice_files,
)
from sparta.providers.stt.local import canonical_locale, language_of

log = logging.getLogger("sparta.local_tts")

PROVIDER = "local-piper"
STAGE = "tts"
FRAME_MS = 20
CHUNK_MS = 40
MAX_TEXT_CHARS = 2000
MIN_SPEED, MAX_SPEED = 0.5, 2.0
VOLUME = 0.9  # headroom: Piper normalises each sentence to full scale, and resampling can overshoot slightly
AHEAD = 1  # sentences synthesised ahead of the one being played

_RATES = {"pcm16_8k": 8000, "pcm16_16k": 16000, "pcm16_24k": 24000}
_CONTROL = dict.fromkeys([*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F])
_WARM_TEXT = {
    "en": "Hello.",
    "hi": "\u0928\u092e\u0938\u094d\u0924\u0947\u0964",
    "kn": "\u0ca8\u0cae\u0cb8\u0ccd\u0c95\u0cbe\u0cb0.",
}


class _End:
    """Marks the end of a job's sentences (or a stop)."""


_END = _End()
_Item = bytes | Exception | _End


class VoiceHandle(Protocol):
    """A loaded voice: its native sample rate and a sentence-at-a-time generator of PCM16 at that rate."""

    sample_rate: int

    def sentences(self, text: str, speed: float) -> Iterator[bytes]: ...


VoiceLoader = Callable[[Path, Path], VoiceHandle]


class _PiperHandle:
    def __init__(self, voice: Any, config_type: Any) -> None:
        self._voice = voice
        self._config_type = config_type
        self.sample_rate = int(voice.config.sample_rate)

    def sentences(self, text: str, speed: float) -> Iterator[bytes]:
        config = self._config_type(length_scale=float(self._voice.config.length_scale) / speed, volume=VOLUME)
        for chunk in self._voice.synthesize(text, config):
            if data := chunk.audio_int16_bytes:
                yield data


def load_piper_voice(onnx: Path, config: Path) -> VoiceHandle:
    """Load a Piper voice from local files (never downloads). Needs ``piper-tts``; blocking, call it from a worker."""
    prepare_engine_environment()  # no telemetry from ONNX Runtime: before the engine's libraries are imported
    try:
        from piper import PiperVoice, SynthesisConfig
    except ImportError:
        raise ProviderUnavailable(
            PROVIDER, STAGE, "the piper-tts package is not installed: pip install 'sparta-api[local-speech]'"
        ) from None
    disable_onnxruntime_telemetry()
    return _PiperHandle(PiperVoice.load(onnx, config_path=config), SynthesisConfig)


def _version() -> str | None:
    try:
        return metadata.version("piper-tts")
    except metadata.PackageNotFoundError:
        return None


def _display_name(voice_id: str) -> str:
    """``hi_IN-priyamvada-medium`` -> ``Priyamvada``; ``kn_IN-syspin_male-medium`` -> ``Syspin Male``."""
    parts = voice_id.split("-")
    return (parts[1] if len(parts) > 1 else voice_id).replace("_", " ").title()


@dataclass(eq=False)
class _Job:
    """One synthesis in flight: its sentences, and the credit that keeps the producer one sentence ahead."""

    queue: "asyncio.Queue[_Item]" = field(default_factory=asyncio.Queue)
    credit: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(AHEAD))
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True
        self.queue.put_nowait(_END)  # wakes a consumer that is waiting for the next sentence


def _next_sentence(sentences: Iterator[bytes], src_rate: int, dst_rate: int) -> bytes | None:
    """The next sentence resampled to ``dst_rate`` (worker thread), or ``None`` when the text is finished."""
    try:
        pcm = next(sentences)
    except StopIteration:
        return None
    return resample_pcm16(pcm, src_rate, dst_rate)


class LocalTextToSpeech:
    produces_audio = True  # unlike the simulator, which only reports how long speaking would take

    def __init__(
        self, settings: Settings, *, metrics: Metrics | None = None, loader: VoiceLoader = load_piper_voice
    ) -> None:
        self._root = model_root(settings)
        self._voices: Mapping[str, str] = settings.local_tts_voice_map  # locale -> voice id
        self.fallback_locale = settings.local_tts_fallback_locale
        self._loader = loader
        self._metrics = metrics
        ids = ",".join(dict.fromkeys(self._voices.values()))
        self.meta = ProviderMeta(provider=PROVIDER, simulated=False, model=ids or None, version=_version())
        self._language_of_voice = {voice: language_of(locale) for locale, voice in self._voices.items()}
        self._language_of_voice.update({key: spec.language for key, spec in VOICES.items() if spec.language})
        self._executor = ThreadPoolExecutor(
            max_workers=settings.local_max_concurrent_inference, thread_name_prefix="sparta-tts"
        )
        self._handles: dict[str, VoiceHandle] = {}
        self._load_lock = threading.Lock()
        self._jobs: dict[str, set[_Job]] = {}
        self._closed = False
        for locale, voice in self._voices.items():
            if not self._installed(voice):
                log.warning(
                    "local voice for %s is not installed: run `python -m sparta models fetch`",
                    locale,
                    extra={"voice": voice},
                )

    # ----------------------------------------------------------------------------------------------- voices
    def _installed(self, voice_id: str) -> bool:
        spec = VOICES.get(voice_id)
        if spec is not None:
            return not missing_files(spec, spec_dir(self._root, spec))
        try:
            onnx, config = voice_files(self._root, voice_id)
        except ValueError:
            return False
        return onnx.is_file() and config.is_file()

    def _voice_for(self, request: SynthesisRequest) -> str:
        """The voice to speak ``request`` with. Raises ``ProviderRejected`` when its locale has no installed voice."""
        locale = canonical_locale(request.locale) if request.locale.strip() else ""
        language = language_of(locale)
        wanted = request.voice_id
        if wanted and self._language_of_voice.get(wanted) == language and self._installed(wanted):
            return wanted  # a known local voice for this language (Azure voice names are not)
        voice = self._voices.get(locale) or next(
            (v for k, v in self._voices.items() if language_of(k) == language), None
        )
        if voice is None or not self._installed(voice):
            raise ProviderRejected(PROVIDER, STAGE, f"no local voice installed for {request.locale[:20]}")
        return voice

    async def list_voices(self, locale: str | None = None) -> list[VoiceOption]:
        """The installed local voices. Never ``verified``: that flag is for names confirmed in a provider's documentation."""
        wanted = canonical_locale(locale) if locale else None
        out: list[VoiceOption] = []
        for configured, voice in self._voices.items():
            if (wanted is not None and configured != wanted) or not self._installed(voice):
                continue
            spec = VOICES.get(voice)
            out.append(
                VoiceOption(
                    id=voice,
                    locale=configured,
                    display_name=_display_name(voice),
                    gender=spec.gender if spec and spec.gender else "neutral",
                    provider=PROVIDER,
                    verified=False,
                    note=f"Licence: {spec.licence}. {spec.caveat}"
                    if spec
                    else "Custom local voice: not in the manifest, so its licence is unknown.",
                )
            )
        return out

    # ------------------------------------------------------------------------------------------ lifecycle
    async def _in_pool(self, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)
        except RuntimeError:
            if self._closed:
                raise ProviderUnavailable(PROVIDER, STAGE, "the synthesiser is closed") from None
            raise

    def _load_sync(self, voice_id: str) -> VoiceHandle:
        with self._load_lock:
            handle = self._handles.get(voice_id)
            if handle is None:
                onnx, config = voice_files(self._root, voice_id)
                started = time.perf_counter()
                try:
                    handle = self._loader(onnx, config)
                except ProviderError:
                    raise
                except Exception as exc:  # onnxruntime and json raise a variety of errors for a bad voice file
                    log.error("local voice could not be loaded", extra={"voice": voice_id}, exc_info=True)
                    raise ProviderUnavailable(
                        PROVIDER, STAGE, f"voice '{voice_id}' could not be loaded ({type(exc).__name__})"
                    ) from None
                self._handles[voice_id] = handle
                log.info(
                    "local voice loaded", extra={"voice": voice_id, "seconds": round(time.perf_counter() - started, 2)}
                )
            return handle

    async def warmup(self) -> float:
        """Load every configured voice that is installed and speak one short word with each; returns the seconds taken."""
        started = time.perf_counter()
        for voice in dict.fromkeys(self._voices.values()):
            if not self._installed(voice):
                continue
            handle: VoiceHandle = await self._in_pool(self._load_sync, voice)
            text = _WARM_TEXT.get(self._language_of_voice.get(voice, ""))
            if text:
                await self._in_pool(_next_sentence, handle.sentences(text, 1.0), handle.sample_rate, 8000)
        return time.perf_counter() - started

    async def aclose(self) -> None:
        self._closed = True
        for jobs in list(self._jobs.values()):
            for job in list(jobs):
                job.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._handles.clear()

    async def stop_playback(self, playback_id: str) -> None:
        """Stop every synthesis registered under ``playback_id`` (its request ``trace_id``) from handing out more audio."""
        for job in list(self._jobs.get(playback_id, ())):
            job.cancel()

    # ------------------------------------------------------------------------------------------ synthesis
    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        """Yield 40 ms chunks of PCM16; the last has ``final=True``. Errors surface on the first iteration."""
        rate = _RATES.get(request.output_format)
        if rate is None:
            raise ProviderRejected(PROVIDER, STAGE, "the local synthesiser only produces 16-bit PCM")
        text = request.text.translate(_CONTROL).strip()
        if not text:
            raise ProviderRejected(PROVIDER, STAGE, "nothing to synthesise")
        if len(text) > MAX_TEXT_CHARS:
            raise ProviderRejected(PROVIDER, STAGE, "text is too long")
        if not math.isfinite(request.rate):
            raise ProviderRejected(PROVIDER, STAGE, "invalid speaking rate")
        voice_id = self._voice_for(request)
        speed = min(max(request.rate, MIN_SPEED), MAX_SPEED)
        job = _Job()
        if request.trace_id:
            self._jobs.setdefault(request.trace_id, set()).add(job)
        producer: asyncio.Future[None] | None = None
        emitted = 0
        started = time.perf_counter()
        try:
            handle: VoiceHandle = await self._in_pool(self._load_sync, voice_id)
            producer = asyncio.ensure_future(self._produce(job, handle, text, speed, rate))
            chunk_bytes = rate * CHUNK_MS // 1000 * 2
            frame_bytes = rate * FRAME_MS // 1000 * 2
            carry = bytearray()
            held: bytes | None = None  # the newest chunk is held back until we know whether it is the last
            seq = 0
            first = True
            while True:
                item = await job.queue.get()
                if job.cancelled or isinstance(item, _End):
                    break
                if isinstance(item, Exception):
                    raise item
                job.credit.release()  # this sentence is being played: let the producer start the next one
                if first:
                    first = False
                    self._observe(
                        PROVIDER_LATENCY_MS, (time.perf_counter() - started) * 1000.0, stage="tts_first_sentence"
                    )
                carry += item
                while len(carry) >= chunk_bytes:
                    data = bytes(carry[:chunk_bytes])
                    del carry[:chunk_bytes]
                    if held is not None:
                        if job.cancelled:  # barge-in: never hand out audio that was already buffered
                            return
                        emitted += len(held)
                        yield AudioChunk(data=held, sample_rate=rate, encoding="pcm16", seq=seq)
                        seq += 1
                    held = data
            if job.cancelled:
                return
            if carry:
                held_tail = bytes(carry) + bytes(-len(carry) % frame_bytes)
                if held is not None:
                    emitted += len(held)
                    yield AudioChunk(data=held, sample_rate=rate, encoding="pcm16", seq=seq)
                    seq += 1
                held = held_tail
            if held is None:
                raise ProviderError(PROVIDER, STAGE, "no audio returned")
            emitted += len(held)
            yield AudioChunk(data=held, sample_rate=rate, encoding="pcm16", seq=seq, final=True)
        finally:
            job.cancelled = True
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            if request.trace_id:
                peers = self._jobs.get(request.trace_id, set())
                peers.discard(job)
                if not peers:
                    self._jobs.pop(request.trace_id, None)
            if emitted and self._metrics is not None:
                self._metrics.inc(AUDIO_SECONDS, emitted / (rate * 2), provider=PROVIDER, direction="tts")

    async def _produce(self, job: _Job, handle: VoiceHandle, text: str, speed: float, rate: int) -> None:
        """Synthesise sentence after sentence into ``job.queue``, never more than ``AHEAD`` sentences ahead of playback."""
        try:
            sentences = handle.sentences(text, speed)
            while not job.cancelled:
                await job.credit.acquire()
                if job.cancelled:
                    break
                pcm: bytes | None = await self._in_pool(_next_sentence, sentences, handle.sample_rate, rate)
                if pcm is None or job.cancelled:
                    break
                job.queue.put_nowait(pcm)
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            job.queue.put_nowait(exc)
        except Exception as exc:
            log.error("local speech synthesis failed", extra={"error_type": type(exc).__name__}, exc_info=True)
            job.queue.put_nowait(ProviderError(PROVIDER, STAGE, "speech synthesis failed"))
        finally:
            job.queue.put_nowait(_END)

    def _observe(self, name: str, value: float, **labels: str) -> None:
        if self._metrics is not None:
            self._metrics.observe(name, value, provider=PROVIDER, **labels)


__all__ = ["LocalTextToSpeech", "VoiceHandle", "load_piper_voice"]
