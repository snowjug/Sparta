"""Real-time pacing of 20 ms audio frames.

Asterisk writes every frame it receives to the call immediately and does not pace it, so Sparta must send speech at the
speed it is played. Frames go out ``lead`` ahead of their play time: enough for the far end's buffer to stay filled, little
enough that a stop (barge-in) leaves at most about ``lead`` of audio that can no longer be recalled.

If the event loop stalls for longer than ``resync`` the timeline restarts from now instead of sending a catch-up burst:
time really did pass, and Asterisk re-bases its RTP timestamps on a burst longer than about 80 ms, which only adds jitter.
"""

from sparta.clock import Clock

FRAME_S = 0.020
DEFAULT_LEAD_S = 0.040
DEFAULT_RESYNC_S = 0.100


class FramePacer:
    def __init__(
        self,
        clock: Clock,
        *,
        frame_s: float = FRAME_S,
        lead_s: float = DEFAULT_LEAD_S,
        resync_s: float = DEFAULT_RESYNC_S,
    ) -> None:
        self._clock = clock
        self._frame_s = frame_s
        self._lead_s = lead_s
        self._resync_s = resync_s
        self._origin: float | None = None
        self._count = 0
        self.resyncs = 0

    @property
    def frames(self) -> int:
        return self._count

    def remaining_s(self) -> float:
        """Seconds until the far end has played everything sent so far (assuming it plays in real time)."""
        if self._origin is None:
            return 0.0
        return max(0.0, self._origin + self._count * self._frame_s - self._clock.monotonic())

    async def wait_turn(self) -> None:
        """Return when the next frame may be sent. Call it once before every frame."""
        now = self._clock.monotonic()
        if self._origin is None:
            self._origin = now
        due = self._origin + max(0.0, self._count * self._frame_s - self._lead_s)
        wait = due - now
        if wait > 0:
            await self._clock.sleep(wait, tag="media")
        elif -wait > self._resync_s:
            self._origin += now - due
            self.resyncs += 1
        self._count += 1
