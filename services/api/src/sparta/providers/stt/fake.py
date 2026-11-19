"""Fake speech-to-text for tests and local plumbing checks (never production).

It does not recognise speech. It reads the tone-coded line id that a test caller plays (see ``providers/fake_tone.py``) from
the utterance's audio and answers with the phrase registered for that id, so a call that goes through SIP, Asterisk and the
media bridge proves that real samples arrived at the right rate and byte order. Audio that carries no intact burst yields an
empty transcript, exactly as noise would.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from sparta.providers.base import ProviderMeta, SttStream, TranscriptEvent, TranscriptResult
from sparta.providers.fake_tone import decode_line_id
from sparta.providers.stt.fake_phrases import phrase_for
from sparta.providers.stt.simulator import SimulatedSpeechToText

MAX_BUFFER_SECONDS = 6  # the burst opens an utterance: later audio is dropped instead of buffered


class _FakeToneStream:
    def __init__(self, sample_rate: int) -> None:
        self._rate = sample_rate
        self._cap = sample_rate * 2 * MAX_BUFFER_SECONDS
        self._buffer = bytearray()
        self._events: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self.bytes_received = 0

    async def push_audio(self, chunk: bytes) -> None:
        self.bytes_received += len(chunk)
        if len(self._buffer) < self._cap:
            self._buffer += chunk[: self._cap - len(self._buffer)]

    async def flush(self) -> None:
        line_id = await asyncio.to_thread(decode_line_id, bytes(self._buffer), self._rate)
        phrase = phrase_for(line_id) if line_id is not None else None
        self._events.put_nowait(
            TranscriptEvent(
                kind="final",
                text=phrase.text if phrase else "",
                language=phrase.locale if phrase else None,
                confidence=0.99 if phrase else 0.0,
            )
        )

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                self._events.put_nowait(None)
                return
            yield event

    async def stop_stream(self) -> None:
        self._events.put_nowait(None)


class FakeToneSpeechToText:
    meta = ProviderMeta(provider="fake-tone", simulated=True, model="tone-coded")
    consumes_audio = True  # it reads the samples, unlike the simulator, which cannot take audio at all

    def __init__(self) -> None:
        self._uploads = SimulatedSpeechToText()

    async def start_stream(
        self, *, candidate_locales: Sequence[str], locale_hint: str | None, trace_id: str, sample_rate: int = 16000
    ) -> SttStream:
        return _FakeToneStream(sample_rate)

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
        return await self._uploads.transcribe(
            audio,
            content_type=content_type,
            candidate_locales=candidate_locales,
            locale_hint=locale_hint,
            trace_id=trace_id,
            transcript_hint=transcript_hint,
        )
