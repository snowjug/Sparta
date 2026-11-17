"""Simulated text-to-speech: timing-only. It produces no audio, only the duration the playback would take.

The browser demo speaks assistant lines with the device's own speech synthesis; telephony adapters use real audio from
Azure Speech. The simulator exists so timing, barge-in and live state behave realistically without credentials.
"""

from collections.abc import AsyncIterator

from sparta.domain.models import VoiceOption
from sparta.providers.base import AudioChunk, ProviderMeta, SynthesisRequest
from sparta.providers.tts.catalog import voices_for
from sparta.providers.tts.ssml import estimate_duration_ms

CHUNK_MS = 200


class SimulatedTextToSpeech:
    meta = ProviderMeta(provider="simulator", simulated=True, model="timing-only")

    def __init__(self) -> None:
        self.stopped: set[str] = set()

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        total = estimate_duration_ms(request.text, request.locale, request.rate)
        chunks = max(1, total // CHUNK_MS)
        for seq in range(chunks):
            yield AudioChunk(data=b"", sample_rate=16000, encoding="pcm16", seq=seq, final=seq == chunks - 1)

    async def stop_playback(self, playback_id: str) -> None:
        self.stopped.add(playback_id)

    async def list_voices(self, locale: str | None = None) -> list[VoiceOption]:
        return voices_for(locale)
