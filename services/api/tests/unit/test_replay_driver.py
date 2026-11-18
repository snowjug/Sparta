"""The replay driver waits by the clock, not by counting polls.

A fixed number of polls is a time limit that depends on the platform: on Windows a 4 ms sleep returns at once (the timer
resolution is coarser than that), so 1500 polls were about 1.6 s and overlapping replays gave up with a 500.
"""

from types import SimpleNamespace

import pytest

from sparta.services import simulator
from sparta.services.simulator import ReplayDriver


def driver_whose_call_is_busy_for(polls_busy: int) -> tuple[ReplayDriver, dict[str, int]]:
    polls = {"n": 0}

    def is_busy(_call_id: str) -> bool:
        polls["n"] += 1
        return polls["n"] <= polls_busy

    driver = ReplayDriver.__new__(ReplayDriver)  # only the call service is used here, so no virtual-clock container
    driver.c = SimpleNamespace(calls=SimpleNamespace(is_busy=is_busy))  # type: ignore[assignment]
    return driver, polls


async def test_a_call_that_stays_busy_for_many_polls_is_waited_for(monkeypatch):
    monkeypatch.setattr(simulator, "REPLAY_POLL_S", 0)  # sleeps that return at once, as on Windows
    driver, polls = driver_whose_call_is_busy_for(6000)  # four times the old fixed budget of 1500 polls
    await driver._idle("call_x")
    assert polls["n"] >= 6000


async def test_a_call_that_never_goes_quiet_times_out_at_the_deadline(monkeypatch):
    monkeypatch.setattr(simulator, "REPLAY_POLL_S", 0)
    driver, _ = driver_whose_call_is_busy_for(10**9)
    with pytest.raises(TimeoutError, match="did not go quiet"):
        await driver._idle("call_x", timeout_s=0.05)
