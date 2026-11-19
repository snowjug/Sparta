"""Shared kit for the Asterisk provider tests: the dialplan's HTTP callbacks and a peer that plays Asterisk's side of the
AudioSocket connection, speaking tone-coded audio (see ``sparta.providers.fake_tone``).

The app runs on a virtual clock. Speech is paced on it (tag ``media``), so ``Kit`` drives exactly those sleeps and
nothing else: virtual time moves only while Sparta is sending audio. That keeps the tests quick and deterministic, and it
means nothing measured here is real timing (the Docker SIP end-to-end test measures that, with its own labels).
"""

import asyncio
import base64
import uuid
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlencode

import httpx

from conftest import ApiEnv
from sparta.providers.fake_tone import (
    BURST_MS,
    encode_line_id,
    find_bursts,
    silence,
    tone,
    tone_duration_ms,
)
from sparta.telephony.asterisk import AsteriskTelephonyProvider
from sparta.telephony.asterisk.protocol import (
    KIND_AUDIO,
    KIND_DTMF,
    KIND_UUID,
    AudioSocketError,
    encode,
    read_message,
)

API = "/api/v1"
SECRET = "asterisk-test-secret-0123456789abcdef"
OWNER: dict[str, str] = {}  # the default development owner: Atharv, the name the assistant introduces itself with
RATE = 8000
ASTERISK: dict[str, object] = {
    "telephony_provider": "asterisk",
    "asterisk_webhook_secret": SECRET,
    "asterisk_media_bind": "127.0.0.1",
    "asterisk_media_port": 0,
    "asterisk_media_peers": ["127.0.0.1"],
    "stt_provider": "fake",
    "tts_provider": "fake",
}
OPENING = "Hi, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding?"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def basic(secret: str = SECRET, user: str = "asterisk") -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()}


@dataclass
class Peer:
    """Asterisk's side of one media connection: sends caller audio, records what Sparta sends back."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    rx: bytearray = field(default_factory=bytearray)
    others: list[tuple[int, bytes]] = field(default_factory=list)
    eof: asyncio.Event = field(default_factory=asyncio.Event)
    error: str | None = None
    task: asyncio.Task[None] | None = None
    _found: list[tuple[int, int]] = field(default_factory=list)
    _resume_ms: int = 0

    @classmethod
    async def connect(cls, port: int, media_id: str | None, *, announce: bool = True) -> Self:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        peer = cls(reader, writer)
        if announce and media_id is not None:
            writer.write(encode(KIND_UUID, uuid.UUID(media_id).bytes))
            await writer.drain()
        peer.task = asyncio.ensure_future(peer._read())
        return peer

    async def _read(self) -> None:
        try:
            while True:
                message = await read_message(self.reader, max_payload=1 << 16)
                if message is None:
                    return
                kind, payload = message
                if kind == KIND_AUDIO:
                    self.rx.extend(payload)
                else:
                    self.others.append((kind, payload))
        except AudioSocketError as exc:
            self.error = exc.reason
        except (ConnectionError, OSError):
            pass
        finally:
            self.eof.set()

    # ----------------------------------------------------------------------------------- what Sparta said
    def lines(self) -> list[tuple[int, int]]:
        """The assistant lines heard so far as ``(offset ms, line id)``. Only audio that arrived since the last call is
        scanned (the scan is pure Python, and a poll loop would otherwise rescan the whole recording every time)."""
        total_ms = len(self.rx) * 1000 // (RATE * 2)
        for offset, ident in find_bursts(bytes(self.rx), RATE, start_ms=self._resume_ms):
            self._found.append((offset, ident))
            self._resume_ms = offset + BURST_MS
        self._resume_ms = max(self._resume_ms, total_ms - BURST_MS)  # a burst cut off by the end is rescanned later
        return list(self._found)

    def audible_ms(self) -> int:
        return tone_duration_ms(bytes(self.rx), RATE)

    async def wait_lines(self, count: int, timeout_s: float = 15.0) -> list[tuple[int, int]]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            found = self.lines()
            if len(found) >= count:
                return found
            await asyncio.sleep(0.01)
        raise AssertionError(f"heard {len(self.lines())} assistant lines, expected {count}")

    async def wait_closed(self, timeout_s: float = 10.0) -> bool:
        try:
            await asyncio.wait_for(self.eof.wait(), timeout_s)
        except TimeoutError:
            return False
        return True

    @property
    def hung_up_by_sparta(self) -> bool:
        return any(kind == 0x00 for kind, _ in self.others) or self.eof.is_set()

    # ------------------------------------------------------------------------------------- what we say
    async def send_audio(self, pcm: bytes) -> None:
        for start in range(0, len(pcm), 320):
            self.writer.write(encode(KIND_AUDIO, pcm[start : start + 320]))
        await self.writer.drain()

    async def say(self, phrase_id: int, *, voiced_ms: int = 300, silence_ms: int = 900) -> None:
        """One utterance: the phrase's tone burst, some voiced filler, then silence long enough to end the utterance."""
        await self.send_audio(
            encode_line_id(phrase_id, RATE) + tone(700, voiced_ms, RATE, 8000) + silence(silence_ms, RATE)
        )

    async def dtmf(self, digits: str) -> None:
        for digit in digits:
            self.writer.write(encode(KIND_DTMF, digit.encode()))
        await self.writer.drain()

    async def send_raw(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def close(self) -> None:
        self.writer.close()
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class Kit:
    """The dialplan's side of the HTTP callbacks plus the media clock driver. Use as ``async with Kit(env) as kit``."""

    def __init__(self, env: ApiEnv) -> None:
        provider = env.container.providers.telephony
        assert isinstance(provider, AsteriskTelephonyProvider)
        self.env = env
        self.provider = provider
        self.peers: list[Peer] = []
        self.media_running = asyncio.Event()
        self.media_running.set()
        self._stop = asyncio.Event()
        self._driver: asyncio.Task[None] | None = None
        self._counter = 0

    async def __aenter__(self) -> Self:
        self._driver = asyncio.ensure_future(self._drive())
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._stop.set()
        if self._driver is not None:
            await self._driver
        for peer in self.peers:
            await peer.close()

    async def _drive(self) -> None:
        clock = self.env.clock
        while not self._stop.is_set():
            await self.media_running.wait()
            delta = clock.next_delta("media")
            if delta is None:
                await asyncio.sleep(0.001)
            else:
                await clock.advance(delta)

    # ----------------------------------------------------------------------------------- HTTP callbacks
    def channel(self) -> str:
        self._counter += 1
        return f"1700000000.{self._counter}"

    async def post(
        self, path: str, fields: dict[str, str], headers: dict[str, str] | None = None, *, content: bytes | None = None
    ) -> httpx.Response:
        body = content if content is not None else urlencode(fields).encode()
        auth = basic() if headers is None else headers  # an empty dict means "no credentials", not "default ones"
        return await self.env.client.post(f"{API}/webhooks/asterisk/{path}", content=body, headers={**FORM, **auth})

    async def incoming(self, channel: str | None = None, **extra: str) -> httpx.Response:
        fields = {"channel": channel or self.channel(), "caller": "6001", "exten": "6000", **extra}
        return await self.post("incoming", fields)

    async def accept(self, channel: str | None = None, **extra: str) -> tuple[str, str]:
        """``(channel, media id)`` of an accepted call."""
        channel = channel or self.channel()
        reply = await self.incoming(channel, **extra)
        assert reply.status_code == 200 and reply.text.startswith("ACCEPT "), reply.text
        return channel, reply.text.split()[1]

    async def connect(self, media_id: str | None, *, announce: bool = True) -> Peer:
        peer = await Peer.connect(self.provider.media_port, media_id, announce=announce)
        self.peers.append(peer)
        return peer

    async def call(self, **extra: str) -> tuple[str, Peer]:
        """A call that Asterisk accepted and connected, after the assistant's first line has been heard."""
        channel, media_id = await self.accept(**extra)
        peer = await self.connect(media_id)
        await peer.wait_lines(1)
        return channel, peer

    async def next_step(self, channel: str) -> str:
        return (await self.post("next", {"channel": channel})).text

    async def ended(self, channel: str, status: str = "-") -> httpx.Response:
        return await self.post("ended", {"channel": channel, "status": status})

    # ---------------------------------------------------------------------------------------- the owner
    async def calls(self) -> list[dict[str, Any]]:
        reply = await self.env.client.get(f"{API}/calls", headers=OWNER)
        assert reply.status_code == 200, reply.text
        return reply.json()["items"]

    async def detail(self, call_id: str) -> dict[str, Any]:
        reply = await self.env.client.get(f"{API}/calls/{call_id}", headers=OWNER)
        assert reply.status_code == 200, reply.text
        return reply.json()

    async def only_call(self) -> dict[str, Any]:
        items = await self.calls()
        assert len(items) == 1, items
        return items[0]

    async def transcript(self, call_id: str) -> list[tuple[str, str]]:
        return [(t["speaker"], t["text"]) for t in (await self.detail(call_id))["turns"]]

    async def until(self, condition: Any, what: str, timeout_s: float = 10.0) -> None:
        """Wait (real time) for an async or sync condition; the call service works on worker threads."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            result = condition()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out waiting for: {what}")

    async def until_ended(self, call_id: str, timeout_s: float = 10.0) -> dict[str, Any]:
        async def done() -> bool:
            return (await self.detail(call_id))["status"] != "active"

        await self.until(done, "the call to end", timeout_s)
        return await self.detail(call_id)

    async def owner_action(self, call_id: str, action: str) -> httpx.Response:
        return await self.env.client.post(f"{API}/calls/{call_id}/{action}", headers=OWNER)
