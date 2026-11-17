"""Simulated speech-to-text: honest about what it cannot do.

It cannot transcribe audio. For uploaded clips it returns the caller-supplied ``transcript_hint`` (so the audio path can
be exercised end to end in tests and demos) and otherwise refuses with ``ProviderRejected``. It can, however, turn a
known transcript into believable *partial* transcript events, which is what the live view needs to animate.
"""

from collections.abc import AsyncIterator, Sequence

from sparta.providers.base import (
    ProviderMeta,
    ProviderRejected,
    SttStream,
    TranscriptEvent,
    TranscriptResult,
    Usage,
)

STAGE = "stt"
NOTE = (
    "Simulator STT cannot transcribe audio. Provide a transcript, "
    "or configure Azure Speech (SPARTA_STT_PROVIDER=azure)."
)


def partial_events(text: str, language: str | None, words_per_step: int = 2) -> list[TranscriptEvent]:
    """Progressive partial transcripts for ``text`` ending in the final transcript."""
    words = text.split()
    events: list[TranscriptEvent] = []
    for end in range(words_per_step, len(words), words_per_step):
        events.append(TranscriptEvent(kind="partial", text=" ".join(words[:end]), language=language, confidence=0.6))
    events.append(TranscriptEvent(kind="final", text=text, language=language, confidence=0.95))
    return events


class _NullStream:
    """A stream that accepts audio and never recognises anything (the simulator has no acoustic model)."""

    def __init__(self) -> None:
        self.bytes_received = 0
        self._stopped = False

    async def push_audio(self, chunk: bytes) -> None:
        self.bytes_received += len(chunk)

    async def flush(self) -> None:
        return None

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        return
        yield  # pragma: no cover - makes this an (empty) async generator

    async def stop_stream(self) -> None:
        self._stopped = True


class SimulatedSpeechToText:
    meta = ProviderMeta(provider="simulator", simulated=True, model="none")

    async def start_stream(
        self, *, candidate_locales: Sequence[str], locale_hint: str | None, trace_id: str, sample_rate: int = 16000
    ) -> SttStream:
        return _NullStream()

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
        if not transcript_hint or not transcript_hint.strip():
            raise ProviderRejected("simulator", STAGE, NOTE)
        text = transcript_hint.strip()
        return TranscriptResult(
            text=text,
            language=locale_hint,
            confidence=None,
            segments=partial_events(text, locale_hint),
            audio_seconds=0.0,
            usage=Usage(requests=0),
            simulated=True,
        )
