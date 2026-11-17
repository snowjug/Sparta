"""Live events of one call get unique, gap-free sequence numbers when the unlocked partial-transcript path races the
timers that run under the per-call lock (the Simulator Lab autoplay failure) on a file-backed SQLite database."""

import asyncio
import logging
from contextlib import asynccontextmanager

from call_harness import OWNER, Harness, make_settings

from sparta.clock import VirtualClock
from sparta.services.container import Container
from sparta.services.notifier import RecordingPushNotifier


@asynccontextmanager
async def file_backed_container(tmp_path):
    """A non-hermetic container: real file database (migrated by Alembic) with several pooled connections."""
    settings = make_settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'live.db').as_posix()}", auto_migrate=True)
    container = await Container.build(settings, clock=VirtualClock(), notifier=RecordingPushNotifier())
    await container.start()
    try:
        yield container
    finally:
        await container.stop()


async def test_partial_transcripts_racing_the_playback_timer_never_collide(tmp_path, caplog):
    async with file_backed_container(tmp_path) as c:
        h = Harness(c)
        created = await h.start(number=None)
        rt = c.calls._runtimes[created.id]
        until_finished = rt.speaking_until - c.clock.monotonic()
        assert until_finished > 0  # the opening line is still playing: its completion timer is pending

        with caplog.at_level(logging.ERROR):
            partials = [c.calls.submit_partial(OWNER, created.id, f"partial {i}", "en-IN") for i in range(25)]
            await asyncio.gather(c.clock.advance(until_finished + 0.001), *partials)
            await h.idle(created.id)

        failures = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        assert not failures, failures
        events = await c.calls.events(OWNER, created.id, 0)
        assert [e.seq for e in events] == list(range(1, len(events) + 1))
        kinds = [e.type for e in events]
        assert kinds.count("transcript.partial") == 25 and "assistant.finished" in kinds


async def test_partials_and_a_full_turn_share_one_gap_free_sequence(tmp_path, caplog):
    async with file_backed_container(tmp_path) as c:
        h = Harness(c)
        created = await h.start(number=None)
        await h.settle(created.id)
        with caplog.at_level(logging.ERROR):
            partials = [c.calls.submit_partial(OWNER, created.id, f"p{i}", "en-IN") for i in range(10)]
            await asyncio.gather(*partials)
            await h.say(created.id, "Hello, this is Priya about the tuition fees")
            more = [c.calls.submit_partial(OWNER, created.id, f"q{i}", "en-IN") for i in range(10)]
            await asyncio.gather(*more)
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        seqs = [e.seq for e in await c.calls.events(OWNER, created.id, 0)]
        assert seqs == list(range(1, len(seqs) + 1))
