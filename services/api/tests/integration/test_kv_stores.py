"""Contract tests for the shared-state stores.

``MemoryKV`` always runs. ``RedisKV`` runs against a real Redis when ``SPARTA_TEST_REDIS_URL`` is set (CI provides one;
locally: ``docker run --rm -p 6379:6379 redis:7-alpine``). Keys are unique per test, so a shared Redis is never flushed.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

import pytest
import pytest_asyncio

from sparta.services.kv import KeyValueStore, LockTimeout, MemoryKV, RedisKV

REDIS_URL = os.environ.get("SPARTA_TEST_REDIS_URL")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="SPARTA_TEST_REDIS_URL is not set")


def _name(label: str) -> str:
    return f"test:{uuid.uuid4().hex[:12]}:{label}"


def _store_params() -> list[object]:
    params: list[object] = [pytest.param("memory", id="memory")]
    if REDIS_URL:
        params.append(pytest.param("redis", id="redis"))
    return params


@pytest_asyncio.fixture(params=_store_params())
async def kv(request: pytest.FixtureRequest) -> AsyncIterator[KeyValueStore]:
    store: KeyValueStore = MemoryKV() if request.param == "memory" else RedisKV(REDIS_URL)
    yield store
    await store.aclose()


@pytest_asyncio.fixture
async def redis_kv() -> AsyncIterator[RedisKV]:
    store = RedisKV(REDIS_URL)
    yield store
    await store.aclose()


async def test_values_and_counters_expire(kv: KeyValueStore) -> None:
    counter, value = _name("counter"), _name("value")
    assert [await kv.incr(counter, 1) for _ in range(3)] == [1, 2, 3]
    await kv.set(value, "x", 1)
    assert await kv.get(value) == "x"
    await asyncio.sleep(1.2)
    assert await kv.get(value) is None
    assert await kv.incr(counter, 1) == 1  # the window restarted


async def test_getdel_is_single_use(kv: KeyValueStore) -> None:
    key = _name("ticket")
    await kv.set(key, "owner", 30)
    assert await kv.getdel(key) == "owner"
    assert await kv.getdel(key) is None
    assert await kv.get(key) is None


async def test_lock_serialises_critical_sections(kv: KeyValueStore) -> None:
    name = _name("lock")
    state = {"count": 0, "inside": 0, "most_inside": 0}

    async def worker() -> None:
        async with kv.lock(name, ttl_s=10, wait_s=10):
            state["inside"] += 1
            state["most_inside"] = max(state["most_inside"], state["inside"])
            seen = state["count"]
            await asyncio.sleep(0.005)  # a lost update is certain here without mutual exclusion
            state["count"] = seen + 1
            state["inside"] -= 1

    await asyncio.gather(*(worker() for _ in range(10)))
    assert state == {"count": 10, "inside": 0, "most_inside": 1}


async def test_lock_times_out_while_held_and_frees_on_exit(kv: KeyValueStore) -> None:
    name = _name("lock")
    async with kv.lock(name, ttl_s=10, wait_s=1):
        with pytest.raises(LockTimeout):
            async with kv.lock(name, ttl_s=10, wait_s=0.1):
                pytest.fail("a second holder got the lock")
    async with kv.lock(name, ttl_s=10, wait_s=1):
        pass


async def test_lock_is_released_when_the_body_raises(kv: KeyValueStore) -> None:
    name = _name("lock")
    with pytest.raises(RuntimeError):
        async with kv.lock(name, ttl_s=10, wait_s=1):
            raise RuntimeError("boom")
    async with kv.lock(name, ttl_s=10, wait_s=0.5):
        pass


async def test_publish_reaches_subscribers_of_the_matching_pattern(kv: KeyValueStore) -> None:
    prefix = _name("live")
    stream = cast("AsyncGenerator[tuple[str, str], None]", kv.subscribe(f"{prefix}:*"))
    first = asyncio.ensure_future(anext(stream))
    try:
        # A subscription starts when the consumer does and delivery is at most once, so publish until it is heard.
        async with asyncio.timeout(5):
            while not first.done():
                await kv.publish(f"{prefix}:user_1", "hello")
                await kv.publish(f"other:{prefix}", "ignored")
                await asyncio.sleep(0.05)
        assert first.result() == (f"{prefix}:user_1", "hello")
    finally:
        first.cancel()
        await stream.aclose()


async def test_ping(kv: KeyValueStore) -> None:
    assert await kv.ping() is True


async def test_an_unreachable_redis_reports_not_ready_instead_of_raising() -> None:
    store = RedisKV("redis://127.0.0.1:1/0")
    try:
        assert await store.ping() is False
    finally:
        await store.aclose()


@needs_redis
async def test_the_previous_holder_cannot_free_a_lock_it_no_longer_owns(redis_kv: RedisKV) -> None:
    name = _name("lock")
    first = redis_kv.lock(name, ttl_s=0.2, wait_s=1)
    await first.__aenter__()
    await asyncio.sleep(0.4)  # the lease lapses while the first holder is still inside
    second = redis_kv.lock(name, ttl_s=10, wait_s=1)
    await second.__aenter__()
    await first.__aexit__(None, None, None)  # the stale holder lets go
    with pytest.raises(LockTimeout):
        async with redis_kv.lock(name, ttl_s=10, wait_s=0.1):
            pytest.fail("the stale holder released a lock that now belongs to someone else")
    await second.__aexit__(None, None, None)
    async with redis_kv.lock(name, ttl_s=10, wait_s=1):
        pass
