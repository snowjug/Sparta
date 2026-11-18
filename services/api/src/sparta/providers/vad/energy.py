"""Energy-based voice-activity detection over PCM16 mono audio.

Deliberately simple and deterministic (no model, no native dependency): RMS energy per 20 ms frame with a minimum
speech duration, a hangover before declaring the speech ended, and a silence timeout. It is the default VAD for
uploaded audio and provider media streams; a neural VAD can replace it behind the same protocol.
"""

import math
from array import array

from sparta.providers.base import VadEvent

FRAME_MS = 20


class EnergyVad:
    def __init__(
        self,
        *,
        threshold_rms: float = 600.0,
        min_speech_ms: int = 120,
        hangover_ms: int = 500,
        silence_timeout_ms: int = 8000,
    ) -> None:
        self.threshold_rms = threshold_rms
        self.min_speech_ms = min_speech_ms
        self.hangover_ms = hangover_ms
        self.silence_timeout_ms = silence_timeout_ms
        self.reset()

    def reset(self) -> None:
        self._t_ms = 0
        self._speaking = False
        self._voiced_run = 0
        self._unvoiced_run = 0
        self._silence_started_at = 0
        self._timeout_fired = False
        self._carry = b""

    @staticmethod
    def _rms(samples: "array[int]") -> float:
        if not samples:
            return 0.0
        return math.sqrt(sum(s * s for s in samples) / len(samples))

    def process(self, pcm16: bytes, sample_rate: int) -> list[VadEvent]:
        frame_bytes = sample_rate * FRAME_MS // 1000 * 2
        data = self._carry + pcm16
        events: list[VadEvent] = []
        offset = 0
        while offset + frame_bytes <= len(data):
            frame = array("h")
            frame.frombytes(data[offset : offset + frame_bytes])
            offset += frame_bytes
            self._t_ms += FRAME_MS
            events.extend(self._step(self._rms(frame) >= self.threshold_rms))
        self._carry = data[offset:]
        return events

    def _step(self, voiced: bool) -> list[VadEvent]:
        out: list[VadEvent] = []
        if voiced:
            self._voiced_run += FRAME_MS
            self._unvoiced_run = 0
            if not self._speaking and self._voiced_run >= self.min_speech_ms:
                self._speaking = True
                self._timeout_fired = False
                out.append(VadEvent("speech_started", self._t_ms - self._voiced_run))
        else:
            self._voiced_run = 0
            self._unvoiced_run += FRAME_MS
            if self._speaking and self._unvoiced_run >= self.hangover_ms:
                self._speaking = False
                self._silence_started_at = self._t_ms - self._unvoiced_run
                out.append(VadEvent("speech_ended", self._silence_started_at))
            if (
                not self._speaking
                and not self._timeout_fired
                and self._t_ms - self._silence_started_at >= self.silence_timeout_ms
            ):
                self._timeout_fired = True
                out.append(VadEvent("silence_timeout", self._t_ms))
        return out
