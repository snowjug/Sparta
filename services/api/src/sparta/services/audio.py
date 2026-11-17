"""Uploaded-audio path: validate, transcribe in memory, then run the transcript through the normal turn pipeline.

Audio is never written to disk or stored. With the simulator STT there is no acoustic model, so an upload needs a
``transcript_hint`` (the clip is then only validated and the hint is used as the transcript); without one the request is
refused with ``stt_unavailable`` instead of inventing a transcript.
"""

import logging
import time

from sparta.config import Settings
from sparta.domain.enums import TurnSource
from sparta.language.registry import load_registry
from sparta.observability import metrics as mt
from sparta.observability.metrics import Metrics
from sparta.observability.tracing import new_trace_id
from sparta.providers.base import ProviderRejected, SpeechToTextProvider
from sparta.services.audio_validation import validate_audio
from sparta.services.calls import CallService
from sparta.services.dto import Principal, TurnResult
from sparta.services.errors import InvalidInput, SttUnavailable

log = logging.getLogger("sparta.audio")
MAX_HINT_CHARS = 1000


class AudioService:
    def __init__(self, *, settings: Settings, calls: CallService, stt: SpeechToTextProvider, metrics: Metrics) -> None:
        self.settings, self.calls, self.stt, self.metrics = settings, calls, stt, metrics
        self._supported = set(load_registry().supported_codes())

    async def submit_upload(
        self,
        principal: Principal,
        call_id: str,
        data: bytes,
        content_type: str | None,
        *,
        language_hint: str | None,
        transcript_hint: str | None,
    ) -> TurnResult:
        info = validate_audio(
            data, content_type, max_bytes=self.settings.max_audio_bytes, max_seconds=self.settings.max_audio_seconds
        )
        if language_hint and language_hint not in self._supported:
            raise InvalidInput(f"Unsupported language hint '{language_hint[:16]}'.")
        if transcript_hint and len(transcript_hint) > MAX_HINT_CHARS:
            raise InvalidInput("The transcript hint is too long.")
        await self.calls.assert_owner(principal, call_id)  # a stranger's call id never reaches a provider
        async with self.calls.db.uow() as repo:
            enabled = tuple((await repo.get_preferences(principal.id)).enabled_languages)
        started = time.perf_counter()
        try:
            result = await self.stt.transcribe(
                data,
                content_type=info.content_type,
                candidate_locales=enabled,
                locale_hint=language_hint,
                trace_id=new_trace_id(),
                transcript_hint=transcript_hint,
            )
        except ProviderRejected as exc:
            if self.stt.meta.simulated:
                raise SttUnavailable(exc.message) from None
            raise InvalidInput("The speech service could not read this audio.") from None
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        text = result.text.strip()
        if not text:
            raise InvalidInput("No speech was recognised in this audio.")
        if not result.simulated:
            self.metrics.inc(
                mt.AUDIO_SECONDS, result.audio_seconds or (info.duration_s or 0.0), provider=self.stt.meta.provider
            )
        return await self.calls.submit_turn(
            principal,
            call_id,
            text,
            source=TurnSource.UPLOADED_AUDIO,
            language_hint=result.language or language_hint,
            stt_confidence=result.confidence,
            stt_ms=None if result.simulated else elapsed_ms,
        )
