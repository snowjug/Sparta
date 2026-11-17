"""Real-time caller audio: voice-activity detection -> speech recognition -> caller turns.

Providers that carry the caller's media (Azure Communication Services media streaming) hand raw PCM to
``CallService.caller_audio``; this pipeline turns that stream into the same ``submit_provider_turn`` calls that typed,
scripted and uploaded-audio turns use, so everything downstream (language detection, risk rules, replies) is shared.

Per call, in the event loop of the media socket:

* a **voice-activity detector** (energy based by default, see ``providers/vad``) marks utterance boundaries;
* a short **pre-roll** of the audio before the detected start is kept so the first syllable is not cut off;
* **one recognition stream per utterance** receives that utterance's audio; it is finalised in a background task so the
  media socket never waits for the recogniser (the caller's next words keep flowing and the VAD keeps running);
* finished utterances are **delivered strictly in order**, whatever order the recogniser answers in;
* speech that starts while the assistant is talking is a **barge-in**: the call service stops the playback;
* recogniser failures are reported as degraded ``provider.error`` events and never stop the pipeline.

Nothing here stores audio: chunks live in memory until the recogniser has them and are dropped afterwards.
"""

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sparta.providers.base import (
    ProviderError,
    SpeechToTextProvider,
    SttStream,
    TranscriptEvent,
    VoiceActivityProvider,
)

log = logging.getLogger("sparta.audio_pipeline")

BYTES_PER_SAMPLE = 2
PARTIAL_MIN_INTERVAL_S = 0.15
FINAL_WAIT_S = 20.0  # a recogniser that never answers must not block the following utterances forever


@dataclass(frozen=True)
class PipelineConfig:
    pre_roll_ms: int = 300  # audio kept from before the VAD declared speech
    max_utterance_ms: int = 20_000  # a longer monologue is cut here and recognised in pieces
    max_pending_utterances: int = 4  # finished utterances waiting for the recogniser; more are dropped (and reported)


class PipelineSink(Protocol):
    """What the pipeline needs from the call service (``CallService`` implements it)."""

    def speaking_remaining_s(self, call_id: str) -> float | None: ...

    def caller_speech_started(self, call_id: str) -> None: ...

    def caller_speech_ended(self, call_id: str, produced_turn: bool) -> None: ...

    async def provider_barge_in(self, call_id: str) -> object: ...

    async def provider_partial(self, call_id: str, text: str, language_hint: str | None) -> None: ...

    async def submit_provider_turn(
        self,
        call_id: str,
        text: str,
        *,
        language_hint: str | None = None,
        stt_confidence: float | None = None,
        stt_ms: float | None = None,
    ) -> object | None: ...

    async def provider_error(self, call_id: str | None, stage: str, message: str) -> None: ...


@dataclass(eq=False)
class _Utterance:
    stream: SttStream
    sample_rate: int
    audio_ms: int = 0
    finals: list[TranscriptEvent] = field(default_factory=list)
    failed: bool = False
    finished_at: float = 0.0
    done: asyncio.Event = field(default_factory=asyncio.Event)
    consumer: "asyncio.Task[None] | None" = None
    flusher: "asyncio.Task[None] | None" = None


class AudioPipeline:
    def __init__(
        self,
        *,
        call_id: str,
        sink: PipelineSink,
        stt: SpeechToTextProvider,
        vad: VoiceActivityProvider,
        locales: Callable[[], tuple[Sequence[str], str | None]],
        trace_id: str = "",
        config: PipelineConfig | None = None,
    ) -> None:
        self.call_id = call_id
        self._sink = sink
        self._stt = stt
        self._vad = vad
        self._locales = locales
        self._trace_id = trace_id
        self._cfg = config or PipelineConfig()
        self._pre_roll: deque[tuple[bytes, int]] = deque()
        self._pre_roll_ms = 0
        self._current: _Utterance | None = None
        self._ready: asyncio.Queue[_Utterance | None] = asyncio.Queue()
        self._pending = 0
        self._background: set[asyncio.Task[Any]] = set()
        self._deliverer: asyncio.Task[None] | None = None
        self._idle = asyncio.Event()
        self._idle.set()
        self._last_language: str | None = None
        self._closed = False

    # ------------------------------------------------------------------------------------------- feeding
    async def feed(self, pcm16: bytes, sample_rate: int) -> None:
        """Process one chunk of caller audio (PCM16 mono). Never raises for provider problems."""
        if self._closed or not pcm16:
            return
        chunk_ms = len(pcm16) * 1000 // (sample_rate * BYTES_PER_SAMPLE)
        started = ended = False
        for event in self._vad.process(pcm16, sample_rate):
            if event.kind == "speech_started":
                started = True
            elif event.kind == "speech_ended":
                ended = True
        if started and self._current is None:
            await self._begin_utterance(pcm16, chunk_ms, sample_rate)
        elif self._current is not None:
            await self._push(self._current, pcm16, chunk_ms)
            if self._current is not None and self._current.audio_ms >= self._cfg.max_utterance_ms:
                self._finish_utterance()  # a very long monologue is recognised in pieces
                if not ended:
                    await self._begin_utterance(b"", 0, sample_rate, continuation=True)
        else:
            self._remember(pcm16, chunk_ms)
        if ended and self._current is not None:
            self._finish_utterance()

    def _remember(self, pcm16: bytes, chunk_ms: int) -> None:
        self._pre_roll.append((pcm16, chunk_ms))
        self._pre_roll_ms += chunk_ms
        while self._pre_roll and self._pre_roll_ms - self._pre_roll[0][1] >= self._cfg.pre_roll_ms:
            _, dropped_ms = self._pre_roll.popleft()
            self._pre_roll_ms -= dropped_ms

    async def _begin_utterance(
        self, pcm16: bytes, chunk_ms: int, sample_rate: int, *, continuation: bool = False
    ) -> None:
        if not continuation:
            self._sink.caller_speech_started(self.call_id)
            remaining = self._sink.speaking_remaining_s(self.call_id)
            if remaining:  # the assistant is talking: the caller barged in
                self._spawn(lambda: self._sink.provider_barge_in(self.call_id))
        candidates, hint = self._locales()
        try:
            stream = await self._stt.start_stream(
                candidate_locales=list(candidates),
                locale_hint=hint or self._last_language,
                trace_id=self._trace_id,
                sample_rate=sample_rate,
            )
        except ProviderError as exc:
            self._pre_roll.clear()
            self._pre_roll_ms = 0
            await self._report(exc)
            return
        utterance = _Utterance(stream=stream, sample_rate=sample_rate)
        utterance.consumer = asyncio.create_task(self._consume(utterance))
        self._background.add(utterance.consumer)
        utterance.consumer.add_done_callback(self._background.discard)
        self._current = utterance
        backlog = list(self._pre_roll)
        self._pre_roll.clear()
        self._pre_roll_ms = 0
        for data, ms in backlog:
            await self._push(utterance, data, ms)
        if pcm16:
            await self._push(utterance, pcm16, chunk_ms)

    async def _push(self, utterance: _Utterance, pcm16: bytes, chunk_ms: int) -> None:
        if utterance.failed:
            return
        try:
            await utterance.stream.push_audio(pcm16)
            utterance.audio_ms += chunk_ms
        except ProviderError as exc:
            utterance.failed = True
            await self._report(exc)

    # ------------------------------------------------------------------------------------ finishing
    def _finish_utterance(self) -> None:
        utterance, self._current = self._current, None
        if utterance is None:
            return
        utterance.finished_at = time.monotonic()
        if self._pending >= self._cfg.max_pending_utterances:
            utterance.failed = True
            self._spawn(
                lambda: self._sink.provider_error(
                    self.call_id, "stt", "speech recognition is behind; an utterance was dropped"
                )
            )
            self._spawn(lambda: self._discard(utterance))
            return
        self._pending += 1
        self._idle.clear()
        utterance.flusher = asyncio.create_task(self._flush(utterance))
        self._background.add(utterance.flusher)
        utterance.flusher.add_done_callback(self._background.discard)
        self._ready.put_nowait(utterance)
        if self._deliverer is None or self._deliverer.done():
            self._deliverer = asyncio.create_task(self._deliver_loop())

    async def _flush(self, utterance: _Utterance) -> None:
        try:
            if not utterance.failed:
                await utterance.stream.flush()
        except ProviderError as exc:
            utterance.failed = True
            await self._report(exc)
        except Exception:
            utterance.failed = True
            log.exception("speech recognition flush failed")
        finally:
            with contextlib.suppress(Exception):
                await utterance.stream.stop_stream()

    async def _discard(self, utterance: _Utterance) -> None:
        with contextlib.suppress(Exception):
            await utterance.stream.stop_stream()
        utterance.done.set()

    async def _consume(self, utterance: _Utterance) -> None:
        """Forward partials as live captions and collect finals until the stream ends."""
        last_partial = ""
        last_partial_at = 0.0
        try:
            async for event in utterance.stream.events():
                if event.kind == "partial":
                    now = time.monotonic()
                    if event.text and event.text != last_partial and now - last_partial_at >= PARTIAL_MIN_INTERVAL_S:
                        last_partial, last_partial_at = event.text, now
                        await self._sink.provider_partial(self.call_id, event.text, event.language)
                else:
                    utterance.finals.append(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            utterance.failed = True
            log.exception("speech recognition stream failed")
        finally:
            utterance.done.set()

    # ----------------------------------------------------------------------------------- delivering
    async def _deliver_loop(self) -> None:
        while True:
            utterance = await self._ready.get()
            if utterance is None:
                return
            try:
                await self._deliver(utterance)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("delivering a recognised turn failed")
            finally:
                self._pending = max(0, self._pending - 1)
                if self._pending == 0 and self._ready.empty():
                    self._idle.set()

    async def _deliver(self, utterance: _Utterance) -> None:
        try:
            await asyncio.wait_for(utterance.done.wait(), FINAL_WAIT_S)
        except TimeoutError:
            await self._sink.provider_error(self.call_id, "stt", "speech recognition did not answer in time")
            self._sink.caller_speech_ended(self.call_id, produced_turn=False)
            return
        text = " ".join(t for t in (f.text.strip() for f in utterance.finals) if t)
        if utterance.failed or not text:
            self._sink.caller_speech_ended(self.call_id, produced_turn=False)
            return
        language = next((f.language for f in utterance.finals if f.language), None)
        confidences = [f.confidence for f in utterance.finals if f.confidence is not None]
        if language:
            self._last_language = language
        result = await self._sink.submit_provider_turn(
            self.call_id,
            text,
            language_hint=language,
            stt_confidence=min(confidences) if confidences else None,
            stt_ms=round((time.monotonic() - utterance.finished_at) * 1000.0, 1),
        )
        if result is None:
            self._sink.caller_speech_ended(self.call_id, produced_turn=False)

    # ------------------------------------------------------------------------------------ plumbing
    def _spawn(self, factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        """Run a side effect in the background. The coroutine is created inside the task, so closing never leaks one."""
        task = asyncio.create_task(self._guard(factory))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    @staticmethod
    async def _guard(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("audio pipeline side effect failed")

    async def _report(self, exc: ProviderError) -> None:
        try:
            await self._sink.provider_error(self.call_id, exc.stage, exc.message)
        except Exception:
            log.exception("could not report a speech recognition problem")

    async def drain(self, within_s: float = 5.0) -> None:
        """Wait until every finished utterance has been delivered (graceful shutdown and tests)."""
        if self._current is not None:
            self._finish_utterance()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._idle.wait(), within_s)

    async def aclose(self) -> None:
        """Stop everything and drop buffered audio. Safe to call from inside one of the pipeline's own tasks."""
        if self._closed:
            return
        self._closed = True
        current = self._current
        self._current = None
        self._pre_roll.clear()
        self._pre_roll_ms = 0
        self._ready.put_nowait(None)
        me = asyncio.current_task()
        tasks = [t for t in (*self._background, self._deliverer) if t is not None and t is not me and not t.done()]
        for task in tasks:
            task.cancel()
        if current is not None:
            with contextlib.suppress(Exception):
                await current.stream.stop_stream()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._idle.set()
