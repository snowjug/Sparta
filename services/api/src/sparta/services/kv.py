"""Ephemeral shared state: rate-limit counters, single-use WebSocket tickets, call locks and live-event fan-out.

``MemoryKV`` serves development, tests and single-instance deployments. ``RedisKV`` provides the same behaviour across
instances (rate limits that hold behind a load balancer, call locks, cross-instance live events).
"""

import asyncio
import contextlib
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from sparta.clock import Clock, SystemClock


class LockTimeout(RuntimeError):
    pass


class KeyValueStore(Protocol):
    remote: bool  # True when events published here reach other instances

    async def incr(self, key: str, ttl_s: int) -> int: ...

    async def set(self, key: str, value: str, ttl_s: int) -> None: ...

    async def get(self, key: str) -> str | None: ...

    async def getdel(self, key: str) -> str | None: ...

    def lock(
        self, name: str, ttl_s: float = 30.0, wait_s: float = 10.0
    ) -> "contextlib.AbstractAsyncContextManager[None]": ...

    async def publish(self, channel: str, message: str) -> None: ...

    def subscribe(self, pattern: str) -> "AsyncIterator[tuple[str, str]]": ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class MemoryKV:
    remote = False

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._data: dict[str, tuple[str, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._subscribers: list[tuple[str, asyncio.Queue[tuple[str, str]]]] = []

    def _alive(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires <= self._clock.monotonic():
            del self._data[key]
            return None
        return value

    async def incr(self, key: str, ttl_s: int) -> int:
        current = self._alive(key)
        expires = self._data[key][1] if current is not None else self._clock.monotonic() + ttl_s
        value = int(current or 0) + 1
        self._data[key] = (str(value), expires)
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (value, self._clock.monotonic() + ttl_s)

    async def get(self, key: str) -> str | None:
        return self._alive(key)

    async def getdel(self, key: str) -> str | None:
        value = self._alive(key)
        self._data.pop(key, None)
        return value

    @asynccontextmanager
    async def lock(self, name: str, ttl_s: float = 30.0, wait_s: float = 10.0) -> AsyncIterator[None]:
        lock = self._locks.setdefault(name, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), timeout=wait_s)
        except TimeoutError as exc:
            raise LockTimeout(name) from exc
        try:
            yield
        finally:
            lock.release()

    async def publish(self, channel: str, message: str) -> None:
        for pattern, queue in list(self._subscribers):
            if _match(pattern, channel):
                queue.put_nowait((channel, message))

    async def subscribe(self, pattern: str) -> AsyncIterator[tuple[str, str]]:
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        entry = (pattern, queue)
        self._subscribers.append(entry)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.remove(entry)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._data.clear()


def _match(pattern: str, channel: str) -> bool:
    return channel.startswith(pattern[:-1]) if pattern.endswith("*") else channel == pattern


_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class RedisKV:
    remote = True

    def __init__(self, url: str | None = None, client: object | None = None) -> None:
        if client is None:
            import redis.asyncio as redis

            client = redis.from_url(url or "redis://localhost:6379/0", decode_responses=True)
        self._r = client

    async def incr(self, key: str, ttl_s: int) -> int:
        value = int(await self._r.incr(key))  # type: ignore[attr-defined]
        if value == 1:
            await self._r.expire(key, ttl_s)  # type: ignore[attr-defined]
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._r.set(key, value, ex=ttl_s)  # type: ignore[attr-defined]

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)  # type: ignore[attr-defined,no-any-return]

    async def getdel(self, key: str) -> str | None:
        return await self._r.getdel(key)  # type: ignore[attr-defined,no-any-return]

    @asynccontextmanager
    async def lock(self, name: str, ttl_s: float = 30.0, wait_s: float = 10.0) -> AsyncIterator[None]:
        token = secrets.token_hex(8)
        key = f"sparta:lock:{name}"
        deadline = time.monotonic() + wait_s
        while not await self._r.set(key, token, nx=True, px=int(ttl_s * 1000)):  # type: ignore[attr-defined]
            if time.monotonic() >= deadline:
                raise LockTimeout(name)
            await asyncio.sleep(0.02)
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                await self._r.eval(_RELEASE, 1, key, token)  # type: ignore[attr-defined]

    async def publish(self, channel: str, message: str) -> None:
        await self._r.publish(channel, message)  # type: ignore[attr-defined]

    async def subscribe(self, pattern: str) -> AsyncIterator[tuple[str, str]]:
        pubsub = self._r.pubsub()  # type: ignore[attr-defined]
        await pubsub.psubscribe(pattern)
        try:
            async for message in pubsub.listen():
                if message.get("type") == "pmessage":
                    yield str(message["channel"]), str(message["data"])
        finally:
            with contextlib.suppress(Exception):
                await pubsub.punsubscribe(pattern)
                await pubsub.aclose()

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())  # type: ignore[attr-defined]
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._r.aclose()  # type: ignore[attr-defined]
