"""Azure AI Speech text-to-speech over the REST API.

Endpoint, headers and output formats come from ``docs/research/azure-speech-openai-verification.md``. **Nothing here has
been run against a live Azure Speech resource**; the behaviour is exercised only against mocked HTTP.

* The body is read progressively with ``aiter_bytes`` and re-chunked into whole 20 ms frames, so the code works whether
  the service sends the audio incrementally or all at once. Whether Azure really streams the response with chunked
  transfer encoding is **UNVERIFIED** in the research notes.
* Only requests the service can reasonably honour are sent: the locale and voice must be in the verified catalogue, the
  text is bounded and stripped of characters that are illegal in XML, and the SSML is built (and escaped) by
  :func:`sparta.providers.tts.ssml.build_ssml`.
* The speaking ``style`` is passed through only when the request has one. Azure's behaviour for a style the chosen voice
  does not support is **UNVERIFIED** (the research notes only confirm cheerful/empathetic/newscast for Neerja and Swara).
* ``stop_playback`` handles are the request's ``trace_id``: every in-flight synthesis registered under that id is
  cancelled. A request with an empty ``trace_id`` cannot be stopped individually. The telephony adapter uses its
  playback id as the ``trace_id``.
"""

import asyncio
import contextlib
import math
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from sparta.clock import Clock, SystemClock
from sparta.config import Settings
from sparta.domain.models import VoiceOption
from sparta.observability.metrics import AUDIO_SECONDS, PROVIDER_ERRORS, Metrics
from sparta.providers.azure_common import (
    error_for_status,
    error_for_transport,
    https_origin,
    retry_after_seconds,
    valid_region,
)
from sparta.providers.base import (
    AudioChunk,
    ProviderError,
    ProviderMeta,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
    SynthesisRequest,
)
from sparta.providers.resilience import ResilientCaller
from sparta.providers.tts.catalog import DEFAULT_VOICES, is_known_voice, voices_for
from sparta.providers.tts.ssml import build_ssml

PROVIDER = "azure-speech"
STAGE = "tts"
USER_AGENT = "sparta"
FRAME_MS = 20
FRAMES_PER_CHUNK = 5
MAX_TEXT_CHARS = 2000

# XML 1.0 forbids the control characters other than tab, line feed and carriage return, and U+FFFE and U+FFFF.
_XML_ILLEGAL = dict.fromkeys([*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0xFFFE, 0xFFFF])
_STYLE = re.compile(r"[a-z][a-z0-9-]{0,31}")


@dataclass(frozen=True)
class OutputFormat:
    header: str  # X-Microsoft-OutputFormat value
    sample_rate: int
    encoding: str
    sample_bytes: int
    silence: int  # the byte value that encodes silence, used to pad the final frame

    @property
    def frame_bytes(self) -> int:
        return self.sample_rate * FRAME_MS // 1000 * self.sample_bytes

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.sample_bytes


OUTPUT_FORMATS: dict[str, OutputFormat] = {
    "pcm16_8k": OutputFormat("raw-8khz-16bit-mono-pcm", 8000, "pcm16", 2, 0x00),
    "pcm16_16k": OutputFormat("raw-16khz-16bit-mono-pcm", 16000, "pcm16", 2, 0x00),
    "pcm16_24k": OutputFormat("raw-24khz-16bit-mono-pcm", 24000, "pcm16", 2, 0x00),
    "mulaw_8k": OutputFormat("raw-8khz-8bit-mono-mulaw", 8000, "mulaw", 1, 0xFF),
    "alaw_8k": OutputFormat("raw-8khz-8bit-mono-alaw", 8000, "alaw", 1, 0xD5),
}


class _Cancelled(Exception):
    """Internal: ``stop_playback`` was called for this synthesis."""


@dataclass(eq=False)
class _Active:
    cancel: asyncio.Event


@dataclass(frozen=True)
class _Ready:
    url: str
    key: SecretStr


class _Framer:
    """Re-chunks an arbitrary byte stream into whole 20 ms frames, holding back the tail so the last chunk is known."""

    def __init__(self, fmt: OutputFormat) -> None:
        self._fmt = fmt
        self._chunk = fmt.frame_bytes * FRAMES_PER_CHUNK
        self._pending = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._pending += data
        out: list[bytes] = []
        while len(self._pending) > self._chunk:  # strictly more: whatever is emitted here cannot be the last chunk
            out.append(bytes(self._pending[: self._chunk]))
            del self._pending[: self._chunk]
        return out

    def finish(self) -> bytes | None:
        """The final chunk padded to a whole number of frames, or ``None`` when no audio arrived at all."""
        if not self._pending:
            return None
        pad = -len(self._pending) % self._fmt.frame_bytes
        tail = bytes(self._pending) + bytes([self._fmt.silence]) * pad
        self._pending.clear()
        return tail


async def _close(response: httpx.Response) -> None:
    with contextlib.suppress(httpx.HTTPError, OSError):
        await response.aclose()


async def _wait_for(event: asyncio.Event) -> bool:
    await event.wait()
    return True


async def _next_piece(
    iterator: AsyncIterator[bytes], cancel_wait: "asyncio.Future[bool]", timeout_s: float
) -> bytes | None:
    """Next body bytes (``None`` at the end), racing the read against ``stop_playback`` and an idle timeout."""

    async def read() -> bytes | None:
        return await anext(iterator, None)

    task = asyncio.ensure_future(read())
    waiting: set[asyncio.Future[Any]] = {task, cancel_wait}
    done, _ = await asyncio.wait(waiting, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
    if task in done:
        return task.result()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if cancel_wait in done:
        raise _Cancelled
    raise ProviderTimeout(PROVIDER, STAGE, timeout_s)


class AzureTextToSpeech:
    meta = ProviderMeta(provider=PROVIDER, simulated=False, model="neural")

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._metrics = metrics or Metrics()
        self._timeout_s = settings.provider_timeout_s
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
            metrics=self._metrics,
        )
        self._active: dict[str, set[_Active]] = {}

    @staticmethod
    def _resolve_url(settings: Settings) -> tuple[str | None, str | None]:
        if settings.azure_speech_endpoint:
            base = https_origin(settings.azure_speech_endpoint)
            if base is None:
                return None, "SPARTA_AZURE_SPEECH_ENDPOINT must be an https URL"
            return f"{base}/tts/cognitiveservices/v1", None
        if region := valid_region(settings.azure_speech_region):
            return f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", None
        return None, "Azure Speech region or endpoint is not configured"

    def _require_ready(self) -> _Ready:
        if self._problem or self._url is None:
            raise ProviderUnavailable(PROVIDER, STAGE, self._problem or "not configured")
        if not self._key:
            raise ProviderUnavailable(PROVIDER, STAGE, "Azure Speech key is not configured")
        return _Ready(self._url, self._key)

    async def aclose(self) -> None:
        for actives in list(self._active.values()):
            for active in actives:
                active.cancel.set()
        if self._owns_http:
            await self._http.aclose()

    async def list_voices(self, locale: str | None = None) -> list[VoiceOption]:
        """The verified catalogue. Not a network call: availability in the resource's region is not checked."""
        return voices_for(locale)

    async def stop_playback(self, playback_id: str) -> None:
        """Cancel every in-flight synthesis registered under ``playback_id`` (its request ``trace_id``)."""
        for active in list(self._active.get(playback_id, ())):
            active.cancel.set()

    def _prepare(self, request: SynthesisRequest) -> tuple[OutputFormat, str]:
        fmt = OUTPUT_FORMATS.get(request.output_format)
        if fmt is None:
            raise ProviderRejected(PROVIDER, STAGE, "unsupported output format")
        text = request.text.translate(_XML_ILLEGAL).strip()
        if not text:
            raise ProviderRejected(PROVIDER, STAGE, "nothing to synthesise")
        if len(text) > MAX_TEXT_CHARS:
            raise ProviderRejected(PROVIDER, STAGE, "text is too long")
        if request.locale not in DEFAULT_VOICES:
            raise ProviderRejected(PROVIDER, STAGE, "unsupported locale")
        voice = request.voice_id or DEFAULT_VOICES[request.locale]
        if not is_known_voice(voice, request.locale):
            raise ProviderRejected(PROVIDER, STAGE, "unknown voice for this locale")
        if not math.isfinite(request.rate):
            raise ProviderRejected(PROVIDER, STAGE, "invalid speaking rate")
        style = request.style.strip() if request.style else None
        if style is not None and not _STYLE.fullmatch(style):
            raise ProviderRejected(PROVIDER, STAGE, "invalid speaking style")
        return fmt, build_ssml(text, request.locale, voice, request.rate, style or None)

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        """Yield 20 ms-aligned audio chunks; the last one has ``final=True``. Errors surface on first iteration."""
        ready = self._require_ready()
        fmt, ssml = self._prepare(request)
        active = _Active(asyncio.Event())
        if request.trace_id:
            self._active.setdefault(request.trace_id, set()).add(active)
        cancel_wait = asyncio.ensure_future(_wait_for(active.cancel))
        response: httpx.Response | None = None
        produced = 0
        started = False
        try:
            response = await self._open(ready, fmt, ssml, request.trace_id, cancel_wait)
            if response is None:
                return
            framer = _Framer(fmt)
            seq = 0
            started = True
            iterator = response.aiter_bytes()
            while (piece := await _next_piece(iterator, cancel_wait, self._timeout_s)) is not None:
                for data in framer.feed(piece):
                    if active.cancel.is_set():  # barge-in: never hand out audio that was already buffered
                        return
                    produced += len(data)
                    yield AudioChunk(data=data, sample_rate=fmt.sample_rate, encoding=fmt.encoding, seq=seq)
                    seq += 1
            tail = framer.finish()
            if tail is None:
                raise ProviderError(PROVIDER, STAGE, "no audio returned")
            if active.cancel.is_set():
                return
            produced += len(tail)
            yield AudioChunk(data=tail, sample_rate=fmt.sample_rate, encoding=fmt.encoding, seq=seq, final=True)
        except _Cancelled:
            return
        except ProviderError as exc:
            if started:
                self._stream_failed(type(exc).__name__)
            raise
        except (httpx.HTTPError, OSError) as exc:
            self._stream_failed("stream_interrupted")
            mapped = error_for_transport(PROVIDER, STAGE, exc, self._timeout_s)
            if isinstance(mapped, ProviderTimeout):
                raise mapped from None
            raise ProviderError(PROVIDER, STAGE, "audio stream interrupted") from None
        finally:
            cancel_wait.cancel()
            await asyncio.gather(cancel_wait, return_exceptions=True)
            if request.trace_id:
                peers = self._active.get(request.trace_id, set())
                peers.discard(active)
                if not peers:
                    self._active.pop(request.trace_id, None)
            if response is not None:
                await _close(response)
            if produced:
                self._metrics.inc(AUDIO_SECONDS, produced / fmt.bytes_per_second, provider=PROVIDER, direction="tts")

    def _stream_failed(self, kind: str) -> None:
        self._caller.breaker.failure()
        self._metrics.inc(PROVIDER_ERRORS, provider=PROVIDER, stage=STAGE, kind=kind)

    async def _open(
        self, ready: _Ready, fmt: OutputFormat, ssml: str, trace_id: str, cancel_wait: "asyncio.Future[bool]"
    ) -> httpx.Response | None:
        """Send the request with retries and return a response whose body is still unread (``None`` if stopped)."""
        attempt = asyncio.ensure_future(self._caller.call(lambda: self._send(ready, fmt, ssml), trace_id=trace_id))
        waiting: set[asyncio.Future[Any]] = {attempt, cancel_wait}
        await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        if not attempt.done():
            attempt.cancel()
            await asyncio.gather(attempt, return_exceptions=True)
        if attempt.cancelled():
            return None
        response = attempt.result()
        if cancel_wait.done():
            await _close(response)
            return None
        return response

    async def _send(self, ready: _Ready, fmt: OutputFormat, ssml: str) -> httpx.Response:
        request = self._http.build_request(
            "POST",
            ready.url,
            headers={
                "Ocp-Apim-Subscription-Key": ready.key.get_secret_value(),
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": fmt.header,
                "User-Agent": USER_AGENT,
            },
            content=ssml.encode("utf-8", errors="replace"),
            timeout=self._timeout_s,
        )
        try:
            response = await self._http.send(request, stream=True, follow_redirects=False)
        except (httpx.HTTPError, OSError) as exc:
            raise error_for_transport(PROVIDER, STAGE, exc, self._timeout_s) from None
        error = error_for_status(
            PROVIDER, STAGE, response.status_code, retry_after_seconds(response, self._clock.now())
        )
        if error is not None:
            await _close(response)
            raise error
        return response
