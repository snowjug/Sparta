"""The AudioSocket media layer on its own: wire format, pacing, one connection, and who may connect.

No Asterisk is involved: the other end of each connection is a few lines of test code speaking the wire format that was
read from the 22.12.0 sources. The pacing tests use a virtual clock, so they say nothing about real timing (that is
measured in the Docker SIP end-to-end test, with its own labels).
"""

import asyncio
import random
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest

from sparta.clock import VirtualClock
from sparta.observability.metrics import MEDIA_REJECTED, Metrics
from sparta.telephony.asterisk.pacer import FramePacer
from sparta.telephony.asterisk.protocol import (
    FRAME_BYTES,
    HANGUP_MESSAGE,
    KIND_AUDIO,
    KIND_DTMF,
    KIND_HANGUP,
    KIND_UUID,
    AudioSocketError,
    audio_message,
    check_audio,
    encode,
    parse_dtmf,
    parse_uuid,
    read_message,
)
from sparta.telephony.asterisk.server import AudioSocketServer, PeerPolicy
from sparta.telephony.asterisk.session import AudioSocketSession, MediaLimits

FRAME = bytes(range(160)) * 2  # 320 bytes: a recognisable 20 ms frame
MEDIA_ID = uuid.UUID("12345678-1234-4234-8234-123456789abc")


def reader_with(data: bytes, *, eof: bool = True) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    if eof:
        reader.feed_eof()
    return reader


# ------------------------------------------------------------------------------------------ wire format
def test_a_message_is_one_bytes_object_with_a_big_endian_length():
    assert encode(KIND_AUDIO, FRAME) == b"\x10\x01\x40" + FRAME
    assert HANGUP_MESSAGE == b"\x00\x00\x00"
    assert audio_message(b"\x01\x02") == b"\x10\x00\x02\x01\x02"


@pytest.mark.parametrize("frame", [b"", b"\x01", b"\x01\x02\x03"])
def test_audio_that_is_not_whole_samples_is_never_sent(frame):
    with pytest.raises(ValueError):
        audio_message(frame)


async def test_messages_round_trip_and_a_clean_close_between_messages_is_not_an_error():
    reader = reader_with(encode(KIND_UUID, MEDIA_ID.bytes) + encode(KIND_AUDIO, FRAME) + encode(KIND_HANGUP))
    assert await read_message(reader) == (KIND_UUID, MEDIA_ID.bytes)
    assert await read_message(reader) == (KIND_AUDIO, FRAME)
    assert await read_message(reader) == (KIND_HANGUP, b"")
    assert await read_message(reader) is None


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"\x10\x01", "truncated_header"),
        (b"\x10\x01\x40" + FRAME[:100], "truncated_payload"),
        (b"\x10\x10\x00" + bytes(4096), "oversized"),
    ],
)
async def test_a_malformed_message_is_a_protocol_error_not_a_crash(data, reason):
    with pytest.raises(AudioSocketError) as caught:
        await read_message(reader_with(data), max_payload=1024)
    assert caught.value.reason == reason


async def test_random_garbage_only_ever_raises_the_protocol_error():
    rng = random.Random(7)
    for _ in range(200):
        reader = reader_with(rng.randbytes(rng.randrange(0, 600)))
        try:
            while await read_message(reader, max_payload=300) is not None:
                pass
        except AudioSocketError:
            pass


def test_the_media_id_dtmf_and_audio_are_parsed_strictly():
    assert parse_uuid(MEDIA_ID.bytes) == str(MEDIA_ID)
    for bad in (b"", MEDIA_ID.bytes[:15], MEDIA_ID.bytes + b"\x00"):
        with pytest.raises(AudioSocketError):
            parse_uuid(bad)
    assert [parse_dtmf(c.encode()) for c in "09*#D"] == list("09*#D")
    for bad in (b"", b"12", b"x", b"\x00"):
        with pytest.raises(AudioSocketError):
            parse_dtmf(bad)
    assert check_audio(FRAME) == FRAME
    for bad in (b"", b"\x00", FRAME[:-1]):
        with pytest.raises(AudioSocketError):
            check_audio(bad)


# ------------------------------------------------------------------------------------------------ pacer
async def pace(clock: VirtualClock, pacer: FramePacer, frames: int) -> list[float]:
    """The virtual time at which each of ``frames`` frames may be sent, with the clock jumping to every deadline."""
    stamps: list[float] = []

    async def drive() -> None:
        while True:
            delta = clock.next_delta("media")
            if delta is None:
                await asyncio.sleep(0)
            else:
                await clock.advance(delta)

    driver = asyncio.ensure_future(drive())
    try:
        for _ in range(frames):
            await pacer.wait_turn()
            stamps.append(round(clock.monotonic(), 3))
    finally:
        driver.cancel()
        await asyncio.gather(driver, return_exceptions=True)
    return stamps


async def test_frames_leave_a_little_ahead_of_real_time_and_then_every_20_ms():
    clock = VirtualClock()
    stamps = await pace(clock, FramePacer(clock, lead_s=0.040), 8)
    assert stamps == [0.0, 0.0, 0.0, 0.02, 0.04, 0.06, 0.08, 0.1]


async def test_a_stalled_loop_restarts_the_timeline_instead_of_sending_a_catch_up_burst():
    clock = VirtualClock()
    pacer = FramePacer(clock, lead_s=0.040, resync_s=0.100)
    first = await pace(clock, pacer, 6)
    await clock.advance(0.5)  # the event loop stalled for half a second
    after = await pace(clock, pacer, 4)
    assert pacer.resyncs == 1
    assert after[0] == pytest.approx(first[-1] + 0.5, abs=0.001)  # sent at once, not "caught up" earlier
    assert after[1:] == pytest.approx([after[0] + 0.02 * n for n in (1, 2, 3)], abs=0.001)


async def test_a_small_delay_within_the_resync_window_is_absorbed_without_a_resync():
    clock = VirtualClock()
    pacer = FramePacer(clock, lead_s=0.040, resync_s=0.100)
    await pace(clock, pacer, 6)
    await clock.advance(0.07)
    await pace(clock, pacer, 2)
    assert pacer.resyncs == 0


async def test_the_pacer_knows_when_the_far_end_will_have_played_everything():
    clock = VirtualClock()
    pacer = FramePacer(clock, lead_s=0.040)
    assert pacer.remaining_s() == 0.0
    await pace(clock, pacer, 10)
    assert pacer.remaining_s() == pytest.approx(0.06, abs=0.001)  # the lead plus the frame just sent


# ----------------------------------------------------------------------------------------------- session
@dataclass
class Wire:
    """Both ends of one TCP connection: the session under test and a client that plays Asterisk."""

    session: AudioSocketSession
    client_reader: asyncio.StreamReader
    client_writer: asyncio.StreamWriter
    clock: VirtualClock
    audio: list[bytes] = field(default_factory=list)
    dtmf: list[str] = field(default_factory=list)

    async def on_audio(self, pcm: bytes) -> None:
        self.audio.append(pcm)

    async def on_dtmf(self, digit: str) -> None:
        self.dtmf.append(digit)

    def send(self, data: bytes) -> None:
        self.client_writer.write(data)

    async def client_messages(self, count: int) -> list[tuple[int, bytes]]:
        out: list[tuple[int, bytes]] = []
        for _ in range(count):
            message = await asyncio.wait_for(read_message(self.client_reader), 2)
            assert message is not None
            out.append(message)
        return out


@asynccontextmanager
async def wire(limits: MediaLimits | None = None) -> AsyncIterator[Wire]:
    clock = VirtualClock()
    accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.get_running_loop().create_future()
    )

    def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set_result((reader, writer))

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client_reader, client_writer = await asyncio.open_connection("127.0.0.1", port)
    reader, writer = await asyncio.wait_for(accepted, 2)
    session = AudioSocketSession(reader, writer, peer="127.0.0.1", clock=clock, limits=limits)
    try:
        yield Wire(session, client_reader, client_writer, clock)
    finally:
        await session.close()
        client_writer.close()
        server.close()
        await server.wait_closed()


async def test_the_media_id_must_be_the_first_message_and_arrive_in_time():
    async with wire() as w:
        w.send(encode(KIND_UUID, MEDIA_ID.bytes))
        assert await w.session.handshake() == str(MEDIA_ID)


@pytest.mark.parametrize(
    ("first", "reason"),
    [
        (encode(KIND_AUDIO, b"\x01\x02"), "first_message_not_id"),
        (encode(KIND_UUID, MEDIA_ID.bytes[:15]), "bad_uuid"),
        (encode(KIND_UUID, bytes(100)), "oversized"),
        (b"", "handshake_timeout"),
    ],
)
async def test_a_connection_that_does_not_open_with_a_valid_media_id_is_refused(first, reason):
    async with wire(MediaLimits(handshake_timeout_s=0.1)) as w:
        w.send(first)
        with pytest.raises(AudioSocketError) as caught:
            await w.session.handshake()
        assert caught.value.reason == reason


async def test_a_connection_closed_before_the_media_id_is_refused():
    async with wire() as w:
        w.client_writer.close()
        with pytest.raises(AudioSocketError) as caught:
            await w.session.handshake()
        assert caught.value.reason == "closed_before_id"


async def run_session(w: Wire) -> str:
    return await asyncio.wait_for(w.session.run(on_audio=w.on_audio, on_dtmf=w.on_dtmf), 3)


async def test_caller_audio_and_dtmf_are_delivered_in_order_until_asterisk_hangs_up():
    async with wire() as w:
        for n in range(5):
            w.send(encode(KIND_AUDIO, bytes([n]) * 320))
        w.send(encode(KIND_DTMF, b"7") + encode(KIND_HANGUP))
        assert await run_session(w) == "hangup"
        assert b"".join(w.audio) == b"".join(bytes([n]) * 320 for n in range(5))
        assert w.dtmf == ["7"]
        assert w.session.stats["frames_in"] == 5 and w.session.stats["dtmf"] == 1
        assert w.session.first_audio_at is not None


async def test_a_clean_close_is_a_hangup_and_a_reset_is_not_a_crash():
    async with wire() as w:
        w.client_writer.close()
        assert await run_session(w) == "hangup"
    async with wire() as w:
        w.client_writer.transport.abort()
        assert await run_session(w) in {"hangup", "reset"}


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (encode(0x7F, b"x"), "unexpected_message"),
        (encode(KIND_UUID, MEDIA_ID.bytes), "unexpected_message"),  # an id is only ever the first message
        (encode(KIND_AUDIO, b"\x01\x02\x03"), "bad_audio"),
        (encode(KIND_AUDIO, b""), "bad_audio"),
        (encode(KIND_DTMF, b"x"), "bad_dtmf"),
        (b"\x10\x10\x01" + bytes(4100), "oversized"),  # 4097 bytes announced: one over the limit
        (b"\x10\x01\x40" + FRAME[:50], "truncated_payload"),
    ],
)
async def test_a_peer_that_breaks_the_protocol_ends_the_session_with_a_reason(data, reason):
    async with wire() as w:
        w.send(data)
        if reason == "truncated_payload":
            w.client_writer.close()
        assert await run_session(w) == f"protocol:{reason}"
        assert w.session.stats["protocol_errors"] == 1


async def test_a_connection_that_goes_quiet_is_closed_by_the_idle_timeout():
    async with wire(MediaLimits(idle_timeout_s=0.1)) as w:
        w.send(encode(KIND_AUDIO, FRAME))
        assert await run_session(w) == "idle"


async def test_a_slow_consumer_loses_the_oldest_audio_and_the_reader_never_blocks():
    async with wire(MediaLimits(queue_frames=10)) as w:
        release = asyncio.Event()

        async def slow(pcm: bytes) -> None:
            await release.wait()
            w.audio.append(pcm)

        for n in range(60):
            w.send(encode(KIND_AUDIO, bytes([n]) * 320))
        w.send(encode(KIND_HANGUP))
        reading = asyncio.ensure_future(w.session.run(on_audio=slow, on_dtmf=w.on_dtmf))
        assert await asyncio.wait_for(reading, 3) == "hangup"  # reading finished although nobody consumed anything
        assert w.session.stats["frames_in"] == 60
        assert w.session.stats["dropped_frames"] >= 40


async def test_one_failing_audio_handler_does_not_stop_the_call_hearing_the_caller():
    async with wire() as w:
        calls: list[bytes] = []

        async def flaky(pcm: bytes) -> None:
            calls.append(pcm)
            if len(calls) == 1:
                raise RuntimeError("pipeline hiccup")

        w.send(encode(KIND_AUDIO, FRAME))
        reading = asyncio.ensure_future(w.session.run(on_audio=flaky, on_dtmf=w.on_dtmf))
        await asyncio.sleep(0.05)
        w.send(encode(KIND_AUDIO, FRAME) + encode(KIND_HANGUP))
        assert await asyncio.wait_for(reading, 3) == "hangup"
        assert len(calls) == 2


async def chunks(*sizes: int) -> AsyncIterator[bytes]:
    for n, size in enumerate(sizes):
        yield bytes([n + 1]) * size


async def drive_media(clock: VirtualClock, until: asyncio.Future[object] | asyncio.Task[object]) -> None:
    while not until.done():
        delta = clock.next_delta("media")
        if delta is None:
            await asyncio.sleep(0.001)
        else:
            await clock.advance(delta)


async def test_speech_is_cut_into_exact_20_ms_frames_each_sent_in_one_message_and_the_last_is_padded():
    async with wire() as w:
        sending = asyncio.ensure_future(w.session.send_audio_stream(chunks(100, 333, 500, 17)))  # 950 bytes, odd cuts
        await drive_media(w.clock, sending)
        assert await sending is True
        messages = await w.client_messages(3)
        assert [kind for kind, _ in messages] == [KIND_AUDIO] * 3
        assert all(len(payload) == FRAME_BYTES for _, payload in messages)
        stream = b"".join(payload for _, payload in messages)
        assert stream[:100] == bytes([1]) * 100 and stream[100:433] == bytes([2]) * 333
        assert stream[933:950] == bytes([4]) * 17 and stream[950:] == bytes(960 - 950)  # silence pads the last frame
        assert w.session.stats["frames_out"] == 3


async def test_speech_takes_as_long_as_it_lasts_so_playback_is_reported_finished_on_time():
    async with wire() as w:
        sending = asyncio.ensure_future(w.session.send_audio_stream(chunks(*[FRAME_BYTES] * 25)))  # 500 ms
        await drive_media(w.clock, sending)
        assert await sending is True
        assert w.clock.monotonic() == pytest.approx(0.5, abs=0.001)


async def test_cancelling_speech_stops_sending_at_once():
    async with wire() as w:
        sending = asyncio.ensure_future(w.session.send_audio_stream(chunks(*[FRAME_BYTES] * 200)))  # four seconds

        async def until_ten_frames() -> None:
            while w.session.stats["frames_out"] < 10:
                delta = w.clock.next_delta("media")
                await w.clock.advance(delta) if delta is not None else await asyncio.sleep(0.001)

        await asyncio.wait_for(until_ten_frames(), 3)
        sending.cancel()
        await asyncio.gather(sending, return_exceptions=True)
        sent = w.session.stats["frames_out"]
        await w.clock.advance(1.0)
        await asyncio.sleep(0.05)
        assert w.session.stats["frames_out"] == sent <= 12  # nothing after the stop, and not much was ahead of it
        assert not w.session.closed  # stopping a line is not ending the call


async def test_speech_to_a_connection_the_peer_has_closed_reports_failure_instead_of_hanging():
    async with wire() as w:
        w.client_writer.transport.abort()
        await asyncio.sleep(0.05)
        sending = asyncio.ensure_future(w.session.send_audio_stream(chunks(*[FRAME_BYTES] * 50)))
        await drive_media(w.clock, sending)
        assert await asyncio.wait_for(sending, 3) is False
        assert w.session.closed


async def test_closing_with_a_hang_up_tells_asterisk_first_so_its_dialplan_continues():
    async with wire() as w:
        await w.session.close(hang_up=True)
        assert w.session.closed
        assert await asyncio.wait_for(w.client_reader.read(), 2) == HANGUP_MESSAGE


# ------------------------------------------------------------------------------------- who may connect
async def test_peers_are_matched_by_address_range_and_host_name(monkeypatch: pytest.MonkeyPatch):
    clock = VirtualClock()
    lookups: list[str] = []

    async def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        lookups.append(host)
        if host == "asterisk":
            return [(2, 1, 6, "", ("172.20.0.5", 0))]
        raise OSError("no such host")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    peers = PeerPolicy(["127.0.0.1", "10.1.0.0/16", "asterisk", "ghost"], clock=clock, resolve_ttl_s=30)
    assert await peers.allows("127.0.0.1")
    assert await peers.allows("10.1.200.3")
    assert await peers.allows("::ffff:127.0.0.1")  # an IPv4 peer seen on a dual-stack socket
    assert await peers.allows("172.20.0.5")  # the host name resolved
    assert not await peers.allows("172.20.0.6")
    assert not await peers.allows("10.2.0.1")
    assert not await peers.allows("not an address")
    assert not await peers.allows("")
    count = lookups.count("asterisk")
    await peers.allows("172.20.0.5")
    assert lookups.count("asterisk") == count  # cached
    await clock.advance(31)
    await peers.allows("172.20.0.5")
    assert lookups.count("asterisk") == count + 1  # and refreshed when the answer may have changed


@asynccontextmanager
async def listening(
    peers: list[str], handler, *, max_connections: int = 4
) -> AsyncIterator[tuple[AudioSocketServer, Metrics]]:
    metrics = Metrics()
    server = AudioSocketServer(
        host="127.0.0.1",
        port=0,
        peers=PeerPolicy(peers, clock=VirtualClock()),
        handler=handler,
        max_connections=max_connections,
        metrics=metrics,
    )
    await server.start()
    try:
        yield server, metrics
    finally:
        await server.aclose()


async def closed_by_peer(reader: asyncio.StreamReader) -> bool:
    """Whether the other end closed on us: end of stream, or (on Windows, with unread data) a connection reset."""
    try:
        return await asyncio.wait_for(reader.read(), 2) == b""
    except ConnectionResetError:
        return True


async def test_a_connection_from_an_unlisted_peer_is_dropped_before_a_byte_is_read():
    handled: list[str] = []

    async def handler(reader, writer, peer):
        handled.append(peer)

    async with listening(["10.9.9.9"], handler) as (server, metrics):
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        writer.write(encode(KIND_UUID, MEDIA_ID.bytes))
        assert await closed_by_peer(reader)
        assert handled == []
        assert metrics.counter(MEDIA_REJECTED, provider="asterisk", reason="peer_not_allowed") == 1


async def test_connections_over_the_limit_are_dropped_and_the_listener_survives_a_failing_handler():
    gate = asyncio.Event()

    async def handler(reader, writer, peer):
        await gate.wait()
        raise RuntimeError("handler bug")

    async with listening(["127.0.0.1"], handler, max_connections=2) as (server, metrics):
        held = [await asyncio.open_connection("127.0.0.1", server.port) for _ in range(2)]
        await asyncio.sleep(0.05)
        reader, _writer = await asyncio.open_connection("127.0.0.1", server.port)
        assert await closed_by_peer(reader)
        assert metrics.counter(MEDIA_REJECTED, provider="asterisk", reason="too_many_connections") == 1
        gate.set()
        await asyncio.sleep(0.05)
        assert server.connections == 0  # the failed handlers cleaned up
        assert server.listening
        for _r, w in held:
            w.close()


async def test_closing_the_listener_ends_every_open_connection():
    started = asyncio.Event()

    async def handler(reader, writer, peer):
        started.set()
        await asyncio.sleep(60)

    async with listening(["127.0.0.1"], handler) as (server, _):
        reader, _writer = await asyncio.open_connection("127.0.0.1", server.port)
        await asyncio.wait_for(started.wait(), 2)
        await server.aclose()
        assert not server.listening and server.connections == 0
        assert await closed_by_peer(reader)
