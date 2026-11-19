"""Real local speech for the Docker SIP end-to-end test: Piper speaks the caller's lines and faster-whisper reads back what the
caller heard. Both run in the TEST process (the Sparta API container runs its own copies of the same engines), so the test
environment needs the ``local-speech`` extra and the models fetched with ``python -m sparta models fetch``.

The caller is therefore a machine voice, not a person: this proves the audio path with real recognition and real synthesis,
not how Sparta understands a human on a phone.
"""

import os
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sparta.config import Settings
from sparta.providers.base import SynthesisRequest
from sparta.providers.stt.local import LocalSpeechToText
from sparta.providers.tts.local import LocalTextToSpeech

RATE = 8000


def models_dir() -> Path | None:
    raw = os.environ.get("SPARTA_LOCAL_MODEL_DIR", "")
    return Path(raw) if raw else None


@dataclass
class Speech:
    """One recogniser and one synthesiser, loaded once and reused for the whole session."""

    stt: LocalSpeechToText
    tts: LocalTextToSpeech

    @classmethod
    def load(cls, directory: Path) -> "Speech":
        settings = Settings(_env_file=None, local_model_dir=str(directory), stt_provider="local", tts_provider="local")
        return cls(LocalSpeechToText(settings), LocalTextToSpeech(settings))

    async def close(self) -> None:
        await self.stt.aclose()
        await self.tts.aclose()

    async def speak(self, text: str, locale: str) -> bytes:
        """``text`` as 8 kHz PCM16 in the voice installed for ``locale`` (what a caller's microphone would carry)."""
        request = SynthesisRequest(text=text, locale=locale, voice_id=None, output_format="pcm16_8k")  # type: ignore[arg-type]
        return b"".join([chunk.data async for chunk in self.tts.synthesize_stream(request)])

    async def hear(self, pcm: bytes, *, locale: str | None, candidates: Sequence[str] = ("en-IN", "hi-IN", "kn-IN")):
        """What the recogniser makes of 8 kHz PCM16: its final transcript event."""
        stream = await self.stt.start_stream(
            candidate_locales=list(candidates), locale_hint=locale, trace_id="e2e-caller", sample_rate=RATE
        )
        step = RATE // 50 * 2
        for start in range(0, len(pcm), step):
            await stream.push_audio(pcm[start : start + step])
        await stream.flush()
        events = [event async for event in stream.events()]
        return events[-1] if events else None


def words(text: str) -> list[str]:
    """Lower-case words without accents or punctuation, so a transcript can be compared with what was meant."""
    folded = unicodedata.normalize("NFKD", text.lower())
    return re.findall(
        r"[a-z0-9\u0900-\u097f\u0c80-\u0cff]+", "".join(c for c in folded if not unicodedata.combining(c))
    )


def word_error_rate(expected: str, heard: str) -> float:
    """Word error rate (edit distance over words) of ``heard`` against ``expected``; 0.0 is a perfect match."""
    want, got = words(expected), words(heard)
    if not want:
        return 0.0 if not got else 1.0
    previous = list(range(len(got) + 1))
    for i, w in enumerate(want, 1):
        row = [i]
        for j, g in enumerate(got, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (w != g)))
        previous = row
    return previous[-1] / len(want)
