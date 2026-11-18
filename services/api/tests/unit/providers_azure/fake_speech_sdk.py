"""A scripted fake of the parts of ``azure.cognitiveservices.speech`` that the streaming STT adapter uses.

It mimics the real SDK's threading: callbacks fire on a thread of their own, never on the event loop's thread. Names and
signatures are checked against the real SDK by ``test_stt_azure_sdk.py::test_the_names_used_exist_in_the_real_sdk`` when the
SDK is installed.
"""

import enum
import json
import threading
from types import SimpleNamespace
from typing import Any, ClassVar


class ResultReason(enum.Enum):
    RecognizedSpeech = 3
    RecognizingSpeech = 2
    NoMatch = 0


class CancellationReason(enum.Enum):
    Error = 1
    EndOfStream = 2


class CancellationErrorCode(enum.Enum):
    NoError = 0
    AuthenticationFailure = 1
    BadRequestParameters = 2
    TooManyRequests = 3
    ConnectionFailure = 4
    ServiceTimeout = 5
    RuntimeError = 8


class PropertyId(enum.Enum):
    SpeechServiceConnection_LanguageIdMode = 1
    SpeechServiceConnection_AutoDetectSourceLanguageResult = 2
    SpeechServiceResponse_JsonResult = 3
    SpeechServiceResponse_RecognitionLatencyMs = 4


class OutputFormat(enum.Enum):
    Simple = 0
    Detailed = 1


class Signal:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self.callbacks.append(callback)

    def fire(self, event: Any) -> None:
        for callback in list(self.callbacks):
            callback(event)


class Done:
    def __init__(self, value: Any = None) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value


class SpeechConfig:
    def __init__(self, subscription: str | None = None, region: str | None = None, endpoint: str | None = None) -> None:
        self.subscription, self.region, self.endpoint = subscription, region, endpoint
        self.output_format: Any = None
        self.speech_recognition_language: str | None = None
        self.properties: dict[Any, str] = {}

    def set_property(self, property_id: Any, value: str) -> None:
        self.properties[property_id] = value


class AudioStreamFormat:
    def __init__(self, samples_per_second: int, bits_per_sample: int = 16, channels: int = 1) -> None:
        self.samples_per_second, self.bits_per_sample, self.channels = samples_per_second, bits_per_sample, channels


class PushAudioInputStream:
    def __init__(self, stream_format: AudioStreamFormat) -> None:
        self.format = stream_format
        self.chunks: list[bytes] = []
        self.closed = False
        self.on_write: Any = None
        self.on_close: Any = None
        self.write_threads: set[int] = set()

    def write(self, data: bytes) -> None:
        self.write_threads.add(threading.get_ident())
        self.chunks.append(bytes(data))
        if self.on_write:
            self.on_write(len(self.chunks))

    def close(self) -> None:
        self.closed = True
        if self.on_close:
            self.on_close()


class AudioConfig:
    def __init__(self, stream: PushAudioInputStream) -> None:
        self.stream = stream


class AutoDetectSourceLanguageConfig:
    def __init__(self, languages: list[str]) -> None:
        self.languages = languages


class Scenario:
    """What the fake service does: partials while audio arrives, then a final (or an error) once the audio ends."""

    def __init__(
        self,
        *,
        partials: tuple[str, ...] = (),
        final: dict[str, Any] | None = None,
        error: CancellationErrorCode | None = None,
        never_stops: bool = False,
        no_match: bool = False,
        stop_error: bool = False,
        start_error: bool = False,
    ) -> None:
        self.partials, self.final, self.error = partials, final, error
        self.never_stops, self.no_match, self.stop_error, self.start_error = (
            never_stops,
            no_match,
            stop_error,
            start_error,
        )
        self.callback_threads: set[int] = set()


def make_result(
    text: str,
    reason: ResultReason,
    *,
    language: str | None = None,
    confidence: float | None = None,
    offset_ticks: int = 0,
    duration_ticks: int = 0,
    latency_ms: int | None = None,
) -> Any:
    props: dict[Any, str] = {}
    if language:
        props[PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult] = language
    if confidence is not None:
        props[PropertyId.SpeechServiceResponse_JsonResult] = json.dumps({"NBest": [{"Confidence": confidence}]})
    if latency_ms is not None:
        props[PropertyId.SpeechServiceResponse_RecognitionLatencyMs] = str(latency_ms)
    return SimpleNamespace(text=text, reason=reason, properties=props, offset=offset_ticks, duration=duration_ticks)


class SpeechRecognizer:
    created: ClassVar[list["SpeechRecognizer"]] = []
    scenario: ClassVar[Scenario] = Scenario()

    def __init__(
        self,
        speech_config: SpeechConfig,
        audio_config: AudioConfig,
        auto_detect_source_language_config: AutoDetectSourceLanguageConfig | None = None,
    ) -> None:
        self.config, self.audio = speech_config, audio_config
        self.auto_detect = auto_detect_source_language_config
        self.recognizing, self.recognized, self.canceled = Signal(), Signal(), Signal()
        self.session_stopped = Signal()
        self.started = False
        self.stopped = False
        self._first_audio = threading.Event()
        self._partials_thread: threading.Thread | None = None
        audio_config.stream.on_write = self._audio_arrived
        audio_config.stream.on_close = self._audio_ended
        SpeechRecognizer.created.append(self)

    def start_continuous_recognition_async(self) -> Done:
        if SpeechRecognizer.scenario.start_error:
            raise RuntimeError("could not connect https://secret.example.com?key=SECRET")
        self.started = True
        return Done()

    def stop_continuous_recognition_async(self) -> Done:
        if SpeechRecognizer.scenario.stop_error:
            raise RuntimeError("stop failed")
        self.stopped = True
        return Done()

    def _run(self, work: Any) -> threading.Thread:
        def target() -> None:
            SpeechRecognizer.scenario.callback_threads.add(threading.get_ident())
            work()

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread

    def _audio_arrived(self, count: int) -> None:
        if count == 1:
            partials = SpeechRecognizer.scenario.partials

            def emit() -> None:
                for text in partials:
                    self.recognizing.fire(SimpleNamespace(result=make_result(text, ResultReason.RecognizingSpeech)))

            self._partials_thread = self._run(emit)

    def _audio_ended(self) -> None:
        scenario = SpeechRecognizer.scenario

        def finish() -> None:
            if self._partials_thread is not None:
                self._partials_thread.join(timeout=5)  # the service sends every partial before the final
            if scenario.never_stops:
                return
            if scenario.error is not None:
                details = SimpleNamespace(
                    reason=CancellationReason.Error,
                    error_code=scenario.error,
                    error_details="WebSocket upgrade failed https://secret.example.com key=SECRET",
                )
                self.canceled.fire(SimpleNamespace(cancellation_details=details, result=SimpleNamespace()))
            elif scenario.no_match:
                self.recognized.fire(SimpleNamespace(result=make_result("", ResultReason.NoMatch)))
            elif scenario.final is not None:
                extra = {k: v for k, v in scenario.final.items() if k != "text"}
                result = make_result(scenario.final["text"], ResultReason.RecognizedSpeech, **extra)
                self.recognized.fire(SimpleNamespace(result=result))
            self.session_stopped.fire(SimpleNamespace())

        self._run(finish)


def make_sdk(scenario: Scenario | None = None) -> SimpleNamespace:
    """A module-like object. Each call resets the recorded recognisers."""
    SpeechRecognizer.created = []
    SpeechRecognizer.scenario = scenario or Scenario()
    return SimpleNamespace(
        SpeechConfig=SpeechConfig,
        SpeechRecognizer=SpeechRecognizer,
        OutputFormat=OutputFormat,
        PropertyId=PropertyId,
        ResultReason=ResultReason,
        CancellationReason=CancellationReason,
        audio=SimpleNamespace(
            AudioStreamFormat=AudioStreamFormat, PushAudioInputStream=PushAudioInputStream, AudioConfig=AudioConfig
        ),
        languageconfig=SimpleNamespace(AutoDetectSourceLanguageConfig=AutoDetectSourceLanguageConfig),
    )
