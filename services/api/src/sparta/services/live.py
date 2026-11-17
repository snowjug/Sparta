"""Live-event fan-out to WebSocket subscribers, with single-use connection tickets.

Events are persisted by the call service *before* they are published here, so the hub is purely a delivery mechanism:
a subscriber that falls behind is told to resync from ``GET /calls/{id}/events`` rather than blocking call handling.
"""

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sparta.domain.models import LiveEvent
from sparta.services.kv import KeyValueStore

log = logging.getLogger("sparta.live")
CHANNEL_PREFIX = "sparta:live:"
TICKET_TTL_S = 60
RESYNC = "stream.resync"


@dataclass
class Subscription:
    user_id: str
    call_id: str | None
    queue: asyncio.Queue[LiveEvent | None] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    closed: bool = False

    async def events(self) -> AsyncIterator[LiveEvent]:
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    def deliver(self, event: LiveEvent) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # The reader is too slow: drop the backlog and tell it to resync from the persisted event log.
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(LiveEvent(type=RESYNC, call_id=event.call_id, seq=event.seq, data={}))

    def close(self) -> None:
        self.closed = True
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(None)


class LiveHub:
    def __init__(self, kv: KeyValueStore, *, instance_id: str | None = None, max_per_user: int = 10) -> None:
        self._kv = kv
        self._instance = instance_id or secrets.token_hex(4)
        self._subs: list[Subscription] = []
        self._max_per_user = max_per_user
        self._listener: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------------------------------ tickets
    async def issue_ticket(self, user_id: str, call_id: str | None) -> str:
        ticket = secrets.token_urlsafe(24)
        await self._kv.set(f"ticket:{ticket}", json.dumps({"u": user_id, "c": call_id}), TICKET_TTL_S)
        return ticket

    async def redeem_ticket(self, ticket: str) -> tuple[str, str | None] | None:
        """Single use: the ticket is gone after the first successful or failed redemption."""
        raw = await self._kv.getdel(f"ticket:{ticket}")
        if raw is None:
            return None
        data = json.loads(raw)
        return str(data["u"]), data.get("c")

    # ------------------------------------------------------------------------------------ subscriptions
    def subscribe(self, user_id: str, call_id: str | None) -> Subscription | None:
        if sum(1 for s in self._subs if s.user_id == user_id) >= self._max_per_user:
            return None
        sub = Subscription(user_id=user_id, call_id=call_id)
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub.close()
        with contextlib.suppress(ValueError):
            self._subs.remove(sub)

    def connection_count(self, user_id: str | None = None) -> int:
        return sum(1 for s in self._subs if user_id is None or s.user_id == user_id)

    # ---------------------------------------------------------------------------------------- publishing
    def _deliver_local(self, user_id: str, event: LiveEvent) -> None:
        for sub in list(self._subs):
            if sub.user_id == user_id and (sub.call_id is None or sub.call_id == event.call_id):
                sub.deliver(event)

    async def publish(self, user_id: str, event: LiveEvent) -> None:
        self._deliver_local(user_id, event)
        if self._kv.remote:
            payload = json.dumps({"i": self._instance, "u": user_id, "e": event.model_dump(mode="json")})
            await self._kv.publish(f"{CHANNEL_PREFIX}{user_id}", payload)

    async def start(self) -> None:
        if self._kv.remote and self._listener is None:
            self._listener = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for _channel, raw in self._kv.subscribe(f"{CHANNEL_PREFIX}*"):
                try:
                    msg = json.loads(raw)
                    if msg["i"] == self._instance:
                        continue  # already delivered locally
                    self._deliver_local(str(msg["u"]), LiveEvent.model_validate(msg["e"]))
                except (ValueError, KeyError):
                    log.warning("dropped malformed live message")
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        for sub in list(self._subs):
            self.unsubscribe(sub)
