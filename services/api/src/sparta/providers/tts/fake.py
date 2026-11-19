"""Fake text-to-speech for tests and local plumbing checks (never production).

It does not speak. Every line becomes audio that a recording can verify: a tone-coded burst that identifies the line
(``providers/fake_tone.line_id_for``) followed by a steady tone for the rest of the estimated duration. Only PCM16 formats
are produced, because the fake exists for the local SIP path (8 kHz) and its tests.
"""

from collections.abc import AsyncIterator

from sparta.domain.models import VoiceOption
from sparta.providers.base import AudioChunk, ProviderMeta, ProviderRejected, SynthesisRequest
from sparta.providers.fake_tone import BURST_MS, FILLER_AMPLITUDE, FILLER_HZ, encode_line_id, line_id_for, tone
from sparta.providers.tts.catalog import voices_for
from sparta.providers.tts.ssml import estimate_duration_ms

CHUNK_MS = 200
MIN_LINE_MS = BURST_MS + 200
_RATES = {"pcm16_8k": 8000, "pcm16_16k": 16000, "pcm16_24k": 24000}


class FakeToneTextToSpeech:
    meta = ProviderMeta(provider="fake-tone", simulated=True, model="tone-coded")
    produces_audio = True  # unlike the simulator, which only reports how long speaking would take

    def __init__(self) -> None:
        self.stopped: set[str] = set()

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        rate = _RATES.get(request.output_format)
        if rate is None:
            raise ProviderRejected("fake-tone", "tts", "the fake synthesiser only produces 16-bit PCM")
        total_ms = max(MIN_LINE_MS, estimate_duration_ms(request.text, request.locale, request.rate))
        audio = encode_line_id(line_id_for(request.text), rate) + tone(
            FILLER_HZ, total_ms - BURST_MS, rate, FILLER_AMPLITUDE
        )
        step = rate * CHUNK_MS // 1000 * 2
        for seq, offset in enumerate(range(0, len(audio), step)):
            yield AudioChunk(
                data=audio[offset : offset + step],
                sample_rate=rate,
                encoding="pcm16",
                seq=seq,
                final=offset + step >= len(audio),
            )

    async def stop_playback(self, playback_id: str) -> None:
        self.stopped.add(playback_id)

    async def list_voices(self, locale: str | None = None) -> list[VoiceOption]:
        return voices_for(locale)
