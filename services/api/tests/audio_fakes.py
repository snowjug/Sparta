"""Scripted stand-ins for speech recognition, shared by the audio-pipeline unit and integration tests."""

import asyncio
from array import array
from dataclasses import dataclass, field

from sparta.providers.base import ProviderMeta, TranscriptEvent

RATE = 16000


def pcm(ms: int, amplitude: int = 0) -> bytes:
    return array("h", [amplitude] * (RATE * ms // 1000)).tobytes()


VOICED = pcm(20, 3000)
SILENT = pcm(20)


@dataclass
class Script:
    text: str = "tell me the otp"
    language: str | None = "en-IN"
    confidence: float | None = 0.9
    release: asyncio.Event | None = None  # the recogniser answers only once this is set
    flush_error: Exception | None = None
    partial_text: str | None = None


class FakeStream:
    def __init__(self, script: Script) -> None:
        self.script = script
        self.pushed: list[bytes] = []
        self.stopped = False
        self._events: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()

    async def push_audio(self, chunk: bytes) -> None:
        self.pushed.append(chunk)
        if self.script.partial_text and len(self.pushed) == 3:
            self._events.put_nowait(TranscriptEvent(kind="partial", text=self.script.partial_text))

    async def flush(self) -> None:
        if self.script.release is not None:
            await self.script.release.wait()
        if self.script.flush_error is not None:
            raise self.script.flush_error
        self._events.put_nowait(
            TranscriptEvent(
                kind="final", text=self.script.text, language=self.script.language, confidence=self.script.confidence
            )
        )

    async def events(self):
        while True:
            event = await self._events.get()
            if event is None:
                self._events.put_nowait(None)
                return
            yield event

    async def stop_stream(self) -> None:
        self.stopped = True
        self._events.put_nowait(None)


class FakeStt:
    """A non-simulated recogniser that answers with the next script for each utterance."""

    meta = ProviderMeta(provider="fake-stt", simulated=False)

    def __init__(self, *scripts: Script, start_error: Exception | None = None) -> None:
        self.scripts = list(scripts) or [Script()]
        self.start_error = start_error
        self.streams: list[FakeStream] = []
        self.calls: list[dict] = []

    async def start_stream(self, *, candidate_locales, locale_hint, trace_id, sample_rate=16000):
        self.calls.append({"locales": list(candidate_locales), "hint": locale_hint, "rate": sample_rate})
        if self.start_error is not None:
            error, self.start_error = self.start_error, None
            raise error
        stream = FakeStream(self.scripts[min(len(self.streams), len(self.scripts) - 1)])
        self.streams.append(stream)
        return stream


@dataclass
class FakeSink:
    speaking: float | None = 0.0
    turns: list[dict] = field(default_factory=list)
    partials: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    barge_ins: int = 0
    started: int = 0
    ended: list[bool] = field(default_factory=list)

    def speaking_remaining_s(self, call_id: str) -> float | None:
        return self.speaking

    def caller_speech_started(self, call_id: str) -> None:
        self.started += 1

    def caller_speech_ended(self, call_id: str, produced_turn: bool) -> None:
        self.ended.append(produced_turn)

    async def provider_barge_in(self, call_id: str) -> object:
        self.barge_ins += 1
        return object()

    async def provider_partial(self, call_id: str, text: str, language_hint: str | None) -> None:
        self.partials.append(text)

    async def submit_provider_turn(self, call_id, text, *, language_hint=None, stt_confidence=None, stt_ms=None):
        self.turns.append({"text": text, "language": language_hint, "confidence": stt_confidence, "stt_ms": stt_ms})
        return object()

    async def provider_error(self, call_id: str | None, stage: str, message: str) -> None:
        self.errors.append((stage, message))
