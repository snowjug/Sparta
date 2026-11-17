"""Azure AI Speech speech-to-text over the Fast Transcription REST API.

Endpoint, api-version, multipart layout and response fields come from
``docs/research/azure-speech-openai-verification.md``. **Nothing here has been run against a live Azure Speech
resource** (no credentials were available): the behaviour is exercised only against mocked HTTP.

* :meth:`AzureSpeechToText.transcribe` posts one clip. Sanity limits (size, and duration for WAV) are enforced before
  anything is sent. For clips close to ``SPARTA_MAX_AUDIO_SECONDS`` the per-attempt timeout
  (``SPARTA_PROVIDER_TIMEOUT_S``) may need raising: it is not scaled with the clip length.
* :meth:`AzureSpeechToText.start_stream` is **utterance based, not live streaming**. The REST API has no partial
  results, so the stream buffers PCM16 until ``flush()`` (VAD end of utterance), wraps it in a WAV header and emits
  exactly one ``final`` event. It never emits ``partial`` events: a UI must not show progressive text for it. An
  utterance with no recognisable speech yields a ``final`` event with empty text.
* ``transcript_hint`` is ignored: a real provider never echoes caller-supplied text as a transcript.
"""

import asyncio
import json
import re
import struct
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from sparta.clock import Clock, SystemClock
from sparta.config import Settings
from sparta.observability.metrics import Metrics
from sparta.providers.azure_common import (
    error_for_status,
    https_origin,
    retry_after_seconds,
    send_bounded,
    valid_region,
)
from sparta.providers.base import (
    ProviderError,
    ProviderMeta,
    ProviderRejected,
    ProviderUnavailable,
    SttStream,
    TranscriptEvent,
    TranscriptResult,
    Usage,
)
from sparta.providers.resilience import ResilientCaller

PROVIDER = "azure-speech"
STAGE = "stt"
API_VERSION = "2025-10-15"
MAX_AUDIO_BYTES = 8_000_000
MAX_CANDIDATE_LOCALES = 10  # the Speech SDK's continuous language-ID limit; the Fast Transcription limit is UNVERIFIED
MIN_UTTERANCE_MS = 100
MAX_QUEUED_EVENTS = 256

_AUTO_LOCALES = frozenset({"", "auto", "und"})
_LOCALE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}")
_MIME = re.compile(r"audio/[a-z0-9.+-]{1,40}")
_WAV_MIMES = frozenset({"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"})
_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
    "audio/webm": ".webm",
    "audio/mp4": ".mp4",
}


class _Phrase(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    locale: str | None = None
    confidence: float | None = None
    offset_ms: float = Field(default=0.0, alias="offsetMilliseconds")
    duration_ms: float = Field(default=0.0, alias="durationMilliseconds")
    text: str = ""


class _Combined(BaseModel):
    model_config = ConfigDict(extra="ignore")

    channel: int = 0
    text: str = ""


class _FastResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    duration_ms: float = Field(default=0.0, alias="durationMilliseconds")
    combined: list[_Combined] = Field(default_factory=list, alias="combinedPhrases")
    phrases: list[_Phrase] = Field(default_factory=list)


@dataclass(frozen=True)
class _Ready:
    url: str
    key: SecretStr


_WAV_HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap mono PCM16 in a canonical 44-byte RIFF/WAVE header."""
    header = _WAV_HEADER.pack(
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16, b"data", len(pcm)
    )
    return header + pcm


def wav_duration_s(audio: bytes) -> float | None:
    """Upper bound on the seconds of audio in a RIFF/WAVE container, or ``None`` when it cannot be read cheaply.

    The declared ``data`` size is ignored (streamed WAVs declare 0 or 0xFFFFFFFF, and a lying header must not slip
    past the duration limit): everything after the ``data`` chunk header counts.
    """
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return None
    byte_rate = 0
    pos = 12
    while pos + 8 <= len(audio):
        chunk_id = audio[pos : pos + 4]
        size = int.from_bytes(audio[pos + 4 : pos + 8], "little")
        body = pos + 8
        if chunk_id == b"fmt " and size >= 16 and body + 12 <= len(audio):
            byte_rate = int.from_bytes(audio[body + 8 : body + 12], "little")
        elif chunk_id == b"data":
            return (len(audio) - body) / byte_rate if byte_rate else None
        pos = body + size + (size & 1)
    return None


def _audio_mime(content_type: str) -> str:
    mime = content_type.split(";", maxsplit=1)[0].strip().lower()
    if not _MIME.fullmatch(mime):
        raise ProviderRejected(PROVIDER, STAGE, "unsupported audio content type")
    return mime


def _locales(candidates: Sequence[str], hint: str | None) -> list[str]:
    """Locales for the request: the hint first, then the candidates. Empty means automatic language identification."""
    ordered: list[str] = []
    for raw in [hint or "", *candidates]:
        value = raw.strip()
        if value.lower() in _AUTO_LOCALES:
            continue
        if not _LOCALE.fullmatch(value):
            raise ProviderRejected(PROVIDER, STAGE, "invalid locale")
        if value.lower() not in {existing.lower() for existing in ordered}:
            ordered.append(value)
    return ordered[:MAX_CANDIDATE_LOCALES]


def _score(value: float | None) -> float | None:
    return None if value is None else min(max(value, 0.0), 1.0)


def _to_result(parsed: _FastResult) -> TranscriptResult:
    segments = [
        TranscriptEvent(
            kind="final",
            text=phrase.text.strip(),
            language=phrase.locale if phrase.locale and _LOCALE.fullmatch(phrase.locale) else None,
            confidence=_score(phrase.confidence),
            offset_ms=max(int(phrase.offset_ms), 0),
            duration_ms=max(int(phrase.duration_ms), 0),
        )
        for phrase in parsed.phrases
        if phrase.text.strip()
    ]
    combined = " ".join(c.text.strip() for c in sorted(parsed.combined, key=lambda c: c.channel) if c.text.strip())
    text = combined or " ".join(s.text for s in segments)
    locales = Counter(s.language for s in segments if s.language)
    scores = [s.confidence for s in segments if s.confidence is not None]
    duration_ms = parsed.duration_ms or max((s.offset_ms + s.duration_ms for s in segments), default=0)
    seconds = max(duration_ms, 0) / 1000.0
    return TranscriptResult(
        text=text,
        language=locales.most_common(1)[0][0] if locales else None,
        confidence=sum(scores) / len(scores) if scores else None,
        segments=segments,
        audio_seconds=seconds,
        usage=Usage(audio_seconds=seconds, requests=1),
        simulated=False,
    )


class AzureSttStream:
    """One utterance-based recognition session (see the module docstring: no partial results)."""

    def __init__(
        self,
        stt: "AzureSpeechToText",
        *,
        candidate_locales: Sequence[str],
        locale_hint: str | None,
        trace_id: str,
        sample_rate: int,
    ) -> None:
        self._stt = stt
        self._candidates = list(candidate_locales)
        self._hint = locale_hint
        self._trace_id = trace_id
        self._sample_rate = sample_rate
        self._max_bytes = min(MAX_AUDIO_BYTES - 44, sample_rate * 2 * stt.max_audio_seconds)
        self._pcm = bytearray()
        self._events: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._stopped = False
        self._flushed_ms = 0

    async def push_audio(self, chunk: bytes) -> None:
        if self._stopped or not chunk:
            return
        if len(self._pcm) + len(chunk) > self._max_bytes:
            self._pcm.clear()
            raise ProviderRejected(PROVIDER, STAGE, "utterance exceeds the maximum buffered audio; flush sooner")
        self._pcm += chunk

    async def flush(self) -> None:
        if self._stopped or not self._pcm:
            return
        pcm = bytes(self._pcm[: len(self._pcm) // 2 * 2])
        self._pcm = bytearray()
        duration_ms = len(pcm) * 1000 // (self._sample_rate * 2)
        offset_ms = self._flushed_ms
        self._flushed_ms += duration_ms
        async with self._lock:  # finals are emitted in the order the utterances were flushed
            if self._stopped:
                return
            if duration_ms < MIN_UTTERANCE_MS:
                self._emit(TranscriptEvent(kind="final", text="", offset_ms=offset_ms, duration_ms=duration_ms))
                return
            result = await self._stt.transcribe(
                pcm16_to_wav(pcm, self._sample_rate),
                content_type="audio/wav",
                candidate_locales=self._candidates,
                locale_hint=self._hint,
                trace_id=self._trace_id,
            )
            if self._stopped:
                return
            self._emit(
                TranscriptEvent(
                    kind="final",
                    text=result.text,
                    language=result.language,
                    confidence=result.confidence,
                    offset_ms=offset_ms,
                    duration_ms=duration_ms,
                )
            )

    def _emit(self, event: TranscriptEvent) -> None:
        if self._events.qsize() >= MAX_QUEUED_EVENTS:
            self._events.get_nowait()
        self._events.put_nowait(event)

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


class AzureSpeechToText:
    meta = ProviderMeta(provider=PROVIDER, simulated=False, model="fast-transcription", version=API_VERSION)

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._timeout_s = settings.provider_timeout_s
        self._max_audio_bytes = min(settings.max_audio_bytes, MAX_AUDIO_BYTES)
        self.max_audio_seconds = settings.max_audio_seconds
        self._key = settings.azure_speech_key
        self._url, self._problem = self._resolve_url(settings)
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_s), follow_redirects=False)
        self._caller = ResilientCaller(
            PROVIDER,
            STAGE,
            timeout_s=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
            clock=self._clock,
            metrics=metrics,
        )

    @staticmethod
    def _resolve_url(settings: Settings) -> tuple[str | None, str | None]:
        if settings.azure_speech_endpoint:
            base = https_origin(settings.azure_speech_endpoint)
            if base is None:
                return None, "SPARTA_AZURE_SPEECH_ENDPOINT must be an https URL"
        elif region := valid_region(settings.azure_speech_region):
            base = f"https://{region}.api.cognitive.microsoft.com"
        else:
            return None, "Azure Speech region or endpoint is not configured"
        return f"{base}/speechtotext/transcriptions:transcribe", None

    def _require_ready(self) -> _Ready:
        if self._problem or self._url is None:
            raise ProviderUnavailable(PROVIDER, STAGE, self._problem or "not configured")
        if not self._key:
            raise ProviderUnavailable(PROVIDER, STAGE, "Azure Speech key is not configured")
        return _Ready(self._url, self._key)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def start_stream(
        self, *, candidate_locales: Sequence[str], locale_hint: str | None, trace_id: str, sample_rate: int = 16000
    ) -> SttStream:
        self._require_ready()
        if not 8000 <= sample_rate <= 48000:
            raise ProviderRejected(PROVIDER, STAGE, "unsupported sample rate")
        _locales(candidate_locales, locale_hint)  # fail on bad input now, not at the first flush
        return AzureSttStream(
            self,
            candidate_locales=candidate_locales,
            locale_hint=locale_hint,
            trace_id=trace_id,
            sample_rate=sample_rate,
        )

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
        ready = self._require_ready()
        mime = _audio_mime(content_type)
        if not audio:
            raise ProviderRejected(PROVIDER, STAGE, "empty audio")
        if len(audio) > self._max_audio_bytes:
            raise ProviderRejected(PROVIDER, STAGE, "audio is too large")
        if mime in _WAV_MIMES and (seconds := wav_duration_s(audio)) is not None and seconds > self.max_audio_seconds:
            raise ProviderRejected(PROVIDER, STAGE, "audio is too long")
        locales = _locales(candidate_locales, locale_hint)
        parsed = await self._caller.call(lambda: self._post(ready, audio, mime, locales), trace_id=trace_id)
        return _to_result(parsed)

    async def _post(self, ready: _Ready, audio: bytes, mime: str, locales: list[str]) -> _FastResult:
        definition: dict[str, object] = {}
        if locales:
            definition["locales"] = locales
        definition["profanityFilterMode"] = "None"
        request = self._http.build_request(
            "POST",
            ready.url,
            params={"api-version": API_VERSION},
            headers={"Ocp-Apim-Subscription-Key": ready.key.get_secret_value(), "Accept": "application/json"},
            data={"definition": json.dumps(definition, separators=(",", ":"))},
            files={"audio": (f"audio{_EXTENSIONS.get(mime, '.wav' if mime in _WAV_MIMES else '')}", audio, mime)},
            timeout=self._timeout_s,
        )
        response, body = await send_bounded(
            self._http, request, provider=PROVIDER, stage=STAGE, timeout_s=self._timeout_s
        )
        error = error_for_status(
            PROVIDER, STAGE, response.status_code, retry_after_seconds(response, self._clock.now())
        )
        if error is not None:
            raise error
        try:
            return _FastResult.model_validate_json(body)
        except ValidationError:
            raise ProviderError(PROVIDER, STAGE, "unexpected response format") from None
