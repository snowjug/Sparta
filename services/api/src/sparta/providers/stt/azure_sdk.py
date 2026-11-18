"""Azure AI Speech streaming recognition through the Speech SDK: live partial transcripts and language identification.

The REST adapter in :mod:`sparta.providers.stt.azure` sends one finished utterance per request and can never produce a
partial transcript. A phone call needs the recogniser to work *while the caller is still talking*: this adapter opens one
SDK recogniser per utterance, feeds it the PCM the voice-activity detector hands over, forwards ``recognizing`` events as
partial transcripts and ``recognized`` events as final ones, and ends when the detector says the utterance is over.

* **Nothing here has been run against a live Azure Speech resource.** It is exercised against a fake of the SDK and, when
  the SDK is installed, a contract test checks that every SDK name used here exists.
* The SDK is optional (``pip install 'sparta-api[azure]'``) and imported lazily. Its callbacks arrive on SDK threads and
  are handed to the event loop with ``call_soon_threadsafe``; every blocking SDK call runs in a worker thread.
* Error details of the SDK are never forwarded (they can quote endpoints and request ids): a cancellation becomes a
  static message chosen by its error code.
* One-shot transcription of an uploaded clip is delegated to the REST adapter.
"""

import asyncio
import contextlib
import importlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from types import ModuleType
from typing import Any

from sparta.clock import Clock, SystemClock
from sparta.config import Settings
from sparta.observability.metrics import PROVIDER_LATENCY_MS, Metrics
from sparta.providers.azure_common import https_origin, valid_region
from sparta.providers.base import (
    ProviderError,
    ProviderMeta,
    ProviderRejected,
    ProviderUnavailable,
    SpeechToTextProvider,
    SttStream,
    TranscriptEvent,
    TranscriptResult,
)
from sparta.providers.stt.azure import MIN_UTTERANCE_MS, AzureSpeechToText, _locales

log = logging.getLogger("sparta.stt.sdk")

PROVIDER = "azure-speech"
STAGE = "stt"
FINAL_TIMEOUT_S = 10.0  # how long a flushed utterance may wait for the service before it is given up
START_TIMEOUT_S = 8.0
MAX_QUEUED_EVENTS = 256
TICKS_PER_MS = 10_000  # the SDK reports offsets and durations in 100-nanosecond ticks

SdkLoader = Callable[[], ModuleType]


def load_sdk() -> ModuleType:
    return importlib.import_module("azure.cognitiveservices.speech")


def sdk_available() -> bool:
    try:
        load_sdk()
    except ImportError:
        return False
    return True


def _static_error(sdk: Any, details: Any) -> ProviderError:
    """A sanitised error from a cancellation: chosen by error code, never built from the SDK's own text."""
    code = getattr(getattr(details, "error_code", None), "name", "")
    if code in {"AuthenticationFailure", "Forbidden"}:
        return ProviderRejected(PROVIDER, STAGE, "authentication failed", status=401)
    if code in {"BadRequestParameters", "BadRequest"}:
        return ProviderRejected(PROVIDER, STAGE, "request rejected (unsupported locale or audio format)", status=400)
    if code == "TooManyRequests":
        return ProviderError(PROVIDER, STAGE, "rate limited", retryable=True, status=429)
    if code in {"ConnectionFailure", "ServiceTimeout", "ServiceUnavailable", "RuntimeError", "ServiceError"}:
        return ProviderError(PROVIDER, STAGE, "speech service unavailable", retryable=True)
    return ProviderError(PROVIDER, STAGE, "speech recognition failed")


class SdkSttStream:
    """One utterance: an SDK recogniser over a push stream. Methods follow :class:`SttStream`."""

    def __init__(
        self,
        sdk: Any,
        recogniser: Any,
        push: Any,
        loop: asyncio.AbstractEventLoop,
        *,
        sample_rate: int,
        metrics: Metrics,
        clock: Clock,
    ) -> None:
        self._sdk = sdk
        self._recogniser = recogniser
        self._push = push
        self._loop = loop
        self._sample_rate = sample_rate
        self._metrics = metrics
        self._clock = clock
        self._events: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._stopped_signal = asyncio.Event()
        self._error: ProviderError | None = None
        self._pushed_ms = 0
        self._closed_input = False
        self._stopped = False
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------------------- SDK thread -> event loop
    def _post(self, callback: Callable[..., None], *args: Any) -> None:
        with contextlib.suppress(RuntimeError):  # the loop is closed: the call is over, drop the event
            self._loop.call_soon_threadsafe(callback, *args)

    def on_recognizing(self, evt: Any) -> None:
        result = evt.result
        text = (getattr(result, "text", "") or "").strip()
        if text:
            self._post(self._emit, TranscriptEvent(kind="partial", text=text, language=self._language(result)))

    def on_recognized(self, evt: Any) -> None:
        result = evt.result
        reason = getattr(result, "reason", None)
        if reason == self._sdk.ResultReason.RecognizedSpeech:
            text = (getattr(result, "text", "") or "").strip()
            self._post(
                self._emit,
                TranscriptEvent(
                    kind="final",
                    text=text,
                    language=self._language(result),
                    confidence=self._confidence(result),
                    offset_ms=max(int(getattr(result, "offset", 0)) // TICKS_PER_MS, 0),
                    duration_ms=max(int(getattr(result, "duration", 0)) // TICKS_PER_MS, 0),
                ),
            )
            latency = self._property(result, "SpeechServiceResponse_RecognitionLatencyMs")
            if latency and latency.isdigit():
                self._metrics.observe(PROVIDER_LATENCY_MS, float(latency), provider=PROVIDER, stage="stt_service")

    def on_canceled(self, evt: Any) -> None:
        details = getattr(evt, "cancellation_details", None) or getattr(evt.result, "cancellation_details", None)
        reason = getattr(details, "reason", None)
        if reason == getattr(self._sdk.CancellationReason, "Error", object()):
            self._post(self._fail, _static_error(self._sdk, details))
        else:
            self._post(self._stopped_signal.set)

    def on_session_stopped(self, _evt: Any) -> None:
        self._post(self._stopped_signal.set)

    # ----------------------------------------------------------------------------- event loop side
    def _emit(self, event: TranscriptEvent) -> None:
        if self._events.qsize() >= MAX_QUEUED_EVENTS:
            self._events.get_nowait()
        self._events.put_nowait(event)

    def _fail(self, error: ProviderError) -> None:
        self._error = error
        self._stopped_signal.set()

    def _property(self, result: Any, name: str) -> str:
        properties = getattr(result, "properties", None)
        key = getattr(self._sdk.PropertyId, name, None)
        if properties is None or key is None:
            return ""
        try:
            return str(properties.get(key) or "")
        except Exception:  # a property the SDK does not know for this result type
            return ""

    def _language(self, result: Any) -> str | None:
        value = self._property(result, "SpeechServiceConnection_AutoDetectSourceLanguageResult")
        return value or None

    def _confidence(self, result: Any) -> float | None:
        """Confidence of the best hypothesis from the detailed JSON result (``NBest[0].Confidence``)."""
        raw = self._property(result, "SpeechServiceResponse_JsonResult")
        if not raw:
            return None
        try:
            best = json.loads(raw)["NBest"][0]["Confidence"]
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        return min(max(float(best), 0.0), 1.0) if isinstance(best, int | float) else None

    # ------------------------------------------------------------------------------ SttStream
    async def push_audio(self, chunk: bytes) -> None:
        if self._stopped or self._closed_input or not chunk:
            return
        try:
            self._push.write(chunk)
        except Exception:
            raise ProviderError(PROVIDER, STAGE, "audio could not be handed to the recogniser") from None
        self._pushed_ms += len(chunk) * 1000 // (self._sample_rate * 2)

    async def flush(self) -> None:
        async with self._lock:
            if self._stopped:
                return
            if not self._closed_input:
                self._closed_input = True
                with contextlib.suppress(Exception):
                    self._push.close()  # end of audio: the service finalises what it has
            if self._pushed_ms < MIN_UTTERANCE_MS:
                self._emit(TranscriptEvent(kind="final", text="", duration_ms=self._pushed_ms))
                await self._shutdown()
                return
            try:
                await asyncio.wait_for(self._stopped_signal.wait(), FINAL_TIMEOUT_S)
            except TimeoutError:
                await self._shutdown()
                raise ProviderError(
                    PROVIDER, STAGE, "the speech service did not answer in time", retryable=True
                ) from None
            error = self._error
            await self._shutdown()
            if error is not None:
                raise error

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                self._events.put_nowait(None)  # later iterators must terminate too
                return
            yield event

    async def stop_stream(self) -> None:
        async with self._lock:
            await self._shutdown()

    async def _shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if not self._closed_input:
            self._closed_input = True
            with contextlib.suppress(Exception):
                self._push.close()
        recogniser = self._recogniser
        with contextlib.suppress(Exception):
            await asyncio.to_thread(lambda: recogniser.stop_continuous_recognition_async().get())
        self._events.put_nowait(None)


class SdkSpeechToText:
    """:class:`SpeechToTextProvider` with live streaming (Speech SDK) and one-shot upload transcription (REST)."""

    def __init__(
        self,
        settings: Settings,
        *,
        rest: AzureSpeechToText,
        sdk_loader: SdkLoader = load_sdk,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._settings = settings
        self._rest = rest
        self._load = sdk_loader
        self._clock = clock or SystemClock()
        self._metrics = metrics or Metrics()
        self.meta = ProviderMeta(provider=PROVIDER, simulated=False, model="speech-sdk-streaming", version=None)

    async def aclose(self) -> None:
        await self._rest.aclose()

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
        return await self._rest.transcribe(
            audio,
            content_type=content_type,
            candidate_locales=candidate_locales,
            locale_hint=locale_hint,
            trace_id=trace_id,
            transcript_hint=transcript_hint,
        )

    def _speech_config(self, sdk: Any, locales: list[str]) -> Any:
        settings = self._settings
        key = settings.azure_speech_key
        if key is None:
            raise ProviderUnavailable(PROVIDER, STAGE, "Azure Speech key is not configured")
        if settings.azure_speech_endpoint:
            base = https_origin(settings.azure_speech_endpoint)
            if base is None:
                raise ProviderUnavailable(PROVIDER, STAGE, "SPARTA_AZURE_SPEECH_ENDPOINT must be an https URL")
            config = sdk.SpeechConfig(subscription=key.get_secret_value(), endpoint=base)
        else:
            region = valid_region(settings.azure_speech_region)
            if region is None:
                raise ProviderUnavailable(PROVIDER, STAGE, "Azure Speech region or endpoint is not configured")
            if len(locales) > 1:
                # Continuous language identification needs the v2 endpoint (Microsoft documents it for every SDK
                # language). UNVERIFIED against a live call; a custom-domain endpoint is passed through unchanged.
                config = sdk.SpeechConfig(
                    subscription=key.get_secret_value(),
                    endpoint=f"wss://{region}.stt.speech.microsoft.com/speech/universal/v2",
                )
            else:
                config = sdk.SpeechConfig(subscription=key.get_secret_value(), region=region)
        config.output_format = sdk.OutputFormat.Detailed  # adds NBest[].Confidence to every result
        if len(locales) == 1:
            config.speech_recognition_language = locales[0]
        else:
            config.set_property(sdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous")
        return config

    def _build(self, sdk: Any, locales: list[str], sample_rate: int) -> tuple[Any, Any]:
        config = self._speech_config(sdk, locales)
        stream_format = sdk.audio.AudioStreamFormat(samples_per_second=sample_rate, bits_per_sample=16, channels=1)
        push = sdk.audio.PushAudioInputStream(stream_format=stream_format)
        audio = sdk.audio.AudioConfig(stream=push)
        if len(locales) == 1:
            recogniser = sdk.SpeechRecognizer(speech_config=config, audio_config=audio)
        else:
            detect = sdk.languageconfig.AutoDetectSourceLanguageConfig(languages=locales)
            recogniser = sdk.SpeechRecognizer(
                speech_config=config, audio_config=audio, auto_detect_source_language_config=detect
            )
        return recogniser, push

    async def start_stream(
        self, *, candidate_locales: Sequence[str], locale_hint: str | None, trace_id: str, sample_rate: int = 16000
    ) -> SttStream:
        try:
            sdk = self._load()
        except ImportError:
            raise ProviderUnavailable(
                PROVIDER, STAGE, "the azure-cognitiveservices-speech package is not installed"
            ) from None
        if not 8000 <= sample_rate <= 48000:
            raise ProviderRejected(PROVIDER, STAGE, "unsupported sample rate")
        locales = _locales(candidate_locales, locale_hint)
        if not locales:
            locales = ["en-IN"]
        loop = asyncio.get_running_loop()
        try:
            recogniser, push = await asyncio.to_thread(self._build, sdk, locales, sample_rate)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError(PROVIDER, STAGE, "the recogniser could not be created") from None
        stream = SdkSttStream(
            sdk, recogniser, push, loop, sample_rate=sample_rate, metrics=self._metrics, clock=self._clock
        )
        recogniser.recognizing.connect(stream.on_recognizing)
        recogniser.recognized.connect(stream.on_recognized)
        recogniser.canceled.connect(stream.on_canceled)
        recogniser.session_stopped.connect(stream.on_session_stopped)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(lambda: recogniser.start_continuous_recognition_async().get()), START_TIMEOUT_S
            )
        except TimeoutError:
            await stream.stop_stream()
            raise ProviderError(PROVIDER, STAGE, "the speech service did not start in time", retryable=True) from None
        except Exception:
            await stream.stop_stream()
            raise ProviderError(PROVIDER, STAGE, "the speech service could not be reached", retryable=True) from None
        return stream


def build_stt(settings: Settings, rest: AzureSpeechToText, *, clock: Clock, metrics: Metrics) -> SpeechToTextProvider:
    """Streaming through the SDK when it is available and not switched off, otherwise the REST adapter."""
    mode = settings.azure_speech_streaming
    if mode == "off" or (mode == "auto" and not sdk_available()):
        return rest
    return SdkSpeechToText(settings, rest=rest, clock=clock, metrics=metrics)
